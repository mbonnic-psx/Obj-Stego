"""Parse and rebuild Wavefront OBJ files with exact decimal coordinate handling.

Two guarantees define this module (SPEC 12):

1. Every line that is not a `v` line survives byte-identical.
2. Every coordinate is carried as an exact scaled integer -- never through
   `float` -- and written back at exactly `P` decimal places.

Guarantee 2 is not fussiness. A coordinate that round-trips through a float can
land one unit-in-the-last-place away from where it started, and a single
off-by-one in a coordinate's low digits corrupts extraction from that pair
onward (SPEC 3).

This module knows about files and text. It knows nothing about payloads, bits,
or PVD.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "ObjParseError",
    "VertexRecord",
    "ObjDocument",
    "parse_coordinate",
    "format_coordinate",
    "parse_obj",
    "render_obj",
    "read_obj",
    "write_obj",
]

#: OBJ separates tokens with spaces and tabs. Line terminators are stripped
#: before tokenising, so they never appear here.
_WHITESPACE = " \t"

#: Coordinates are decoded and re-encoded with surrogateescape so that a file
#: containing bytes which are not valid UTF-8 -- a comment in some legacy
#: encoding, say -- still round-trips byte-for-byte.
_ENCODING = "utf-8"
_ERRORS = "surrogateescape"


class ObjParseError(Exception):
    """The file is not usable as an OBJ mesh.

    Carries a message written for the person running the tool, including the
    1-based line number where that is meaningful. SPEC 11 requires these to
    surface as clean messages, never tracebacks.
    """


# ---------------------------------------------------------------------------
# Coordinate primitives (SPEC 3)
# ---------------------------------------------------------------------------


def parse_coordinate(token: str, precision: int) -> int:
    """Return `token` as an integer scaled by ``10**precision``, exactly.

    The fractional part is padded with zeros or **truncated** to exactly
    `precision` digits; truncation is applied to the magnitude, so the result is
    symmetric about zero. Scientific notation is converted through `Decimal`,
    whose parsing and 'f' formatting are both exact and context-independent.

    Raises :class:`ObjParseError` if the token is not a number.
    """
    text = token.strip()
    if not text:
        raise ObjParseError("empty coordinate")

    # Decimal handles exponents, leading '+', and bare '.5' uniformly. Its 'f'
    # format is exact -- it does not consult the context precision the way
    # Decimal *arithmetic* does -- so this cannot silently round a long token.
    if "e" in text or "E" in text:
        try:
            text = format(Decimal(text), "f")
        except (InvalidOperation, ValueError):
            raise ObjParseError(f"not a number: {token!r}") from None

    negative = text.startswith("-")
    if text[0] in "+-":
        text = text[1:]

    whole, dot, fraction = text.partition(".")
    if dot and "." in fraction:
        raise ObjParseError(f"not a number: {token!r}")
    if not whole and not fraction:
        raise ObjParseError(f"not a number: {token!r}")
    # Not str.isdigit(): that accepts non-ASCII digits such as U+0661, which
    # int() would then happily parse into a value we could never render back.
    if not all(character in "0123456789" for character in whole + fraction):
        raise ObjParseError(f"not a number: {token!r}")

    # ljust pads short fractions, the slice truncates long ones -- together they
    # force exactly `precision` digits without ever consulting a float.
    fraction = fraction.ljust(precision, "0")[:precision]
    magnitude = int((whole or "0") + fraction)

    return -magnitude if negative else magnitude


def format_coordinate(value: int, precision: int) -> str:
    """Render a scaled integer with exactly `precision` decimal places.

    The inverse of :func:`parse_coordinate` for any value it produces. Negative
    zero is never emitted: ``-0.000000`` cannot arise because a value of 0 has
    no sign to carry.
    """
    if precision < 0:
        raise ValueError("precision must not be negative")

    sign = "-" if value < 0 else ""
    digits = str(abs(value))
    if precision == 0:
        return sign + digits

    # One extra digit so there is always something left of the decimal point.
    digits = digits.rjust(precision + 1, "0")
    return f"{sign}{digits[:-precision]}.{digits[-precision:]}"


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class VertexRecord:
    """One `v` line, split so it can be rebuilt without disturbing its layout.

    A line is reassembled as::

        indent + keyword + sep[0] + coord[0] + sep[1] + coord[1]
               + sep[2] + coord[2] + trailing + terminator

    `trailing` holds everything after the third coordinate verbatim -- a `w`
    component, per-vertex colour, an inline comment, trailing whitespace. SPEC 5
    says only the first three numeric tokens participate; keeping the remainder
    as opaque text is what makes that literally true.
    """

    line_index: int
    indent: str
    keyword: str
    separators: Tuple[str, str, str]
    values: Tuple[int, int, int]
    trailing: str
    terminator: str

    def render(self, values: Optional[Sequence[int]], precision: int) -> str:
        """Rebuild this line, substituting `values` if given."""
        coords = self.values if values is None else values
        parts = [self.indent, self.keyword]
        for separator, value in zip(self.separators, coords):
            parts.append(separator)
            parts.append(format_coordinate(value, precision))
        parts.append(self.trailing)
        parts.append(self.terminator)
        return "".join(parts)


@dataclasses.dataclass(frozen=True)
class ObjDocument:
    """A parsed mesh: raw lines, plus the `v` lines located and decoded.

    `lines` holds every line of the source verbatim, terminators included.
    `vertices` indexes into it. Rendering rebuilds only the vertex lines, which
    is how the byte-identical passthrough guarantee is enforced structurally
    rather than by convention.
    """

    lines: Tuple[str, ...]
    vertices: Tuple[VertexRecord, ...]
    precision: int

    def coordinates(self) -> List[int]:
        """Flatten to ``x, y, z, x, y, z, ...`` in file order (SPEC 5).

        This ordering is the traversal that hide and extract must share; it is
        defined once, here.
        """
        flat: List[int] = []
        for vertex in self.vertices:
            flat.extend(vertex.values)
        return flat

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _split_lines(text: str) -> List[str]:
    """Split on ``\\n`` only, keeping terminators.

    Deliberately not ``str.splitlines``, which also breaks on ``\\v``, ``\\f``,
    ``\\x1c`` and ``U+2028``. Those are ordinary bytes inside an OBJ comment,
    and splitting on them would rewrite the file.
    """
    pieces = text.split("\n")
    lines = [piece + "\n" for piece in pieces[:-1]]
    if pieces[-1]:
        lines.append(pieces[-1])
    return lines


def _split_terminator(line: str) -> Tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


def _next_token(body: str, start: int) -> Tuple[str, str, int]:
    """Return ``(separator, token, next_index)`` from `start`, preserving spacing."""
    cursor = start
    while cursor < len(body) and body[cursor] in _WHITESPACE:
        cursor += 1
    separator = body[start:cursor]

    end = cursor
    while end < len(body) and body[end] not in _WHITESPACE:
        end += 1
    return separator, body[cursor:end], end


def _parse_vertex_line(
    line: str, line_index: int, precision: int
) -> Optional[VertexRecord]:
    """Return a record if `line` is a `v` line, else None.

    Only the exact keyword `v` qualifies -- `vn`, `vt` and `vp` are normals,
    texture coordinates and parameter-space vertices, and carry nothing.
    """
    body, terminator = _split_terminator(line)

    indent_end = 0
    while indent_end < len(body) and body[indent_end] in _WHITESPACE:
        indent_end += 1
    indent = body[:indent_end]

    keyword_end = indent_end
    while keyword_end < len(body) and body[keyword_end] not in _WHITESPACE:
        keyword_end += 1
    keyword = body[indent_end:keyword_end]

    if keyword != "v":
        return None

    separators: List[str] = []
    values: List[int] = []
    cursor = keyword_end
    for axis in range(3):
        separator, token, cursor = _next_token(body, cursor)
        if not token:
            raise ObjParseError(
                f"line {line_index + 1}: 'v' line needs three coordinates, "
                f"found {axis}"
            )
        try:
            values.append(parse_coordinate(token, precision))
        except ObjParseError as exc:
            raise ObjParseError(f"line {line_index + 1}: {exc}") from None
        separators.append(separator)

    return VertexRecord(
        line_index=line_index,
        indent=indent,
        keyword=keyword,
        separators=(separators[0], separators[1], separators[2]),
        values=(values[0], values[1], values[2]),
        trailing=body[cursor:],
        terminator=terminator,
    )


def parse_obj(text: str, precision: int) -> ObjDocument:
    """Parse OBJ source into an :class:`ObjDocument`.

    A file with no `v` lines parses successfully with zero vertices; deciding
    whether that is fatal belongs to the caller, since it is fatal for hiding
    but merely empty for inspection. Malformed `v` lines always raise, because
    there is no safe way to guess what was meant.
    """
    if precision < 1:
        raise ValueError("precision must be at least 1")

    lines = _split_lines(text)
    vertices = [
        record
        for index, line in enumerate(lines)
        if (record := _parse_vertex_line(line, index, precision)) is not None
    ]
    return ObjDocument(
        lines=tuple(lines), vertices=tuple(vertices), precision=precision
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_obj(
    document: ObjDocument, coordinates: Optional[Iterable[int]] = None
) -> str:
    """Rebuild the source text, optionally substituting new coordinates.

    `coordinates` is the flat ``x, y, z, ...`` stream from
    :meth:`ObjDocument.coordinates`, in the same order and of the same length.
    Passing None re-renders the parsed values, which is the identity check the
    Phase 2 exit criterion asks for.

    Guarantees: non-`v` lines are copied without inspection, and every `v` line
    is written with exactly ``document.precision`` decimals per coordinate.
    """
    if coordinates is None:
        replacements = None
    else:
        flat = list(coordinates)
        expected = 3 * len(document.vertices)
        if len(flat) != expected:
            raise ValueError(
                f"expected {expected} coordinates for "
                f"{len(document.vertices)} vertices, got {len(flat)}"
            )
        replacements = flat

    out = list(document.lines)
    for position, vertex in enumerate(document.vertices):
        values = (
            None
            if replacements is None
            else replacements[3 * position : 3 * position + 3]
        )
        out[vertex.line_index] = vertex.render(values, document.precision)
    return "".join(out)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def read_obj(path: Path, precision: int) -> ObjDocument:
    """Read and parse an OBJ file.

    Opened in binary and decoded with surrogateescape so bytes that are not
    valid UTF-8 survive to be written back unchanged.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ObjParseError(f"cannot read {path}: {exc.strerror}") from None
    return parse_obj(raw.decode(_ENCODING, _ERRORS), precision)


def write_obj(path: Path, text: str) -> None:
    """Write rendered OBJ text, reversing :func:`read_obj`'s decoding exactly."""
    try:
        Path(path).write_bytes(text.encode(_ENCODING, _ERRORS))
    except OSError as exc:
        raise ObjParseError(f"cannot write {path}: {exc.strerror}") from None
