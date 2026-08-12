"""The PVD core: anchoring, the boundary test, and single-pair embed/extract.

This module works on plain integers in ``[0, MOD)`` -- the low-order digits of
coordinates. It knows nothing about files, meshes, or payload framing.

The whole scheme rests on one property (SPEC 6): a receiver holding only the
stego file must reach the same skip decisions the sender did. That is achieved
by repositioning each pair about an **anchor** which embedding leaves unchanged,
so the boundary test is a function of quantities the receiver can see. Every
function here is shared by both directions; nothing is implemented twice.
"""

from __future__ import annotations

import dataclasses
from typing import List, Sequence, Tuple

from .bits import Bits, StreamError, bits_to_int, build_stream, int_to_bits
from .ranges import RangeTable, bit_width

__all__ = [
    "anchor",
    "pair_usable",
    "embed_pair",
    "extract_pair",
    "embed_bits",
    "extract_bits",
    "pair_capacity",
    "capacity_bits",
    "HideResult",
    "hide",
]


def anchor(a: int, b: int) -> int:
    """Return the pair's anchor: ``ceil(m / 2)`` above its lower coordinate.

    This is the fixed point of embedding. A pair with anchor `c` and difference
    `m` is always exactly ``(c - ceil(m/2), c + floor(m/2))`` in some order, so
    moving the pair to a new difference moves both coordinates but not `c`
    (SPEC 6).

    Order-independent: ``anchor(a, b) == anchor(b, a)``.
    """
    difference = abs(b - a)
    return min(a, b) + (difference + 1) // 2


def pair_usable(a: int, b: int, upper: int, mod: int) -> bool:
    """Can this pair carry a full group of bits without leaving ``[0, MOD)``?

    Tests the worst case: the pair forced to `upper`, the maximum difference of
    its range. Smaller differences pull the coordinates inward, so they cannot
    escape a bound the extreme respects.

    **This function is the load-bearing wall of the scheme.** Hide and extract
    both call it, and they must reach identical verdicts on the same pair or
    extraction returns garbage from that point on. It is defined once, here --
    do not inline a second copy (CLAUDE.md).

    It is reproducible without the cover file because it depends only on the
    anchor, which embedding preserves, and on `upper`, which comes from the
    range that embedding never leaves.
    """
    centre = anchor(a, b)
    return 0 <= centre - (upper + 1) // 2 and centre + upper // 2 < mod


def _place(centre: int, difference: int, ascending: bool) -> Tuple[int, int]:
    """Position a pair with the given anchor and difference.

    `difference` is never negative, so both halves are ordinary non-negative
    integer division -- no signed floor/ceil, which is where two incompatible
    readings of the old rule came from (SPEC 7).

    `ascending` preserves the pair's orientation: whichever coordinate was
    larger in the cover stays larger in the stego pair.
    """
    low = centre - (difference + 1) // 2
    high = centre + difference // 2
    return (low, high) if ascending else (high, low)


def pair_capacity(a: int, b: int, table: RangeTable) -> int:
    """Bits this pair carries, or 0 if it is skipped.

    Used for capacity accounting. Never a substitute for calling
    :func:`pair_usable` at embed time -- it answers a different question.
    """
    lower, upper = table.find(abs(b - a))
    if not pair_usable(a, b, upper, table.mod):
        return 0
    return bit_width(lower, upper)


def embed_pair(a: int, b: int, value: int, table: RangeTable) -> Tuple[int, int]:
    """Embed `value` into a pair, returning the new pair (SPEC 7).

    `value` must fit the pair's bit width; the caller is expected to have taken
    it from the payload stream using that width. The pair must be usable -- an
    unusable pair carries nothing and should have been skipped.

    Guarantees: the result stays inside ``[0, mod)``, keeps the same range, is
    still accepted by :func:`pair_usable`, and satisfies
    ``extract_pair(result) == value``.
    """
    lower, upper = table.find(abs(b - a))
    width = bit_width(lower, upper)

    if not 0 <= value < (1 << width):
        raise ValueError(
            f"value {value} does not fit the {width} bits this pair carries"
        )
    if not pair_usable(a, b, upper, table.mod):
        raise ValueError(
            f"pair ({a}, {b}) is not usable and cannot carry a payload"
        )

    # The new difference stays inside [lower, upper] because value < 2**width
    # and 2**width <= upper - lower + 1. That is what keeps the pair in its own
    # range, which is what lets the receiver look up the same width (SPEC 6).
    return _place(anchor(a, b), lower + value, ascending=b >= a)


def extract_pair(a: int, b: int, table: RangeTable) -> int:
    """Recover the value a pair carries (SPEC 8).

    The inverse of :func:`embed_pair`. Reads the stego pair only; there is no
    cover, no key, and no side channel.

    The caller must check :func:`pair_usable` first -- a skipped pair carries
    nothing, and reading one would inject bits the embedder never wrote.
    """
    lower, _ = table.find(abs(b - a))
    return abs(b - a) - lower


def embed_bits(a: int, b: int, group: Bits, table: RangeTable) -> Tuple[int, int]:
    """Embed a group of bits, MSB first, into a pair.

    Convenience over :func:`embed_pair` for callers holding bits rather than an
    integer. The group must be exactly as wide as the pair carries.
    """
    lower, upper = table.find(abs(b - a))
    width = bit_width(lower, upper)
    if len(group) != width:
        raise ValueError(f"pair carries {width} bits, got {len(group)}")
    return embed_pair(a, b, bits_to_int(group), table)


def extract_bits(a: int, b: int, table: RangeTable) -> Bits:
    """Recover a pair's bits, MSB first, padded to the pair's width.

    Raises :class:`StreamError` if the pair's offset is too large for the bits
    its range carries. That is reachable only in the top bucket, which is wider
    than a power of two: at L=3 it spans 512-999, but 8 bits address only the
    first 256 of those, so a *cover* pair may naturally sit at a difference of
    768-999 that embedding can never produce (SPEC 2's documented dead zone).

    Such a pair was therefore never written to. A correct extraction stops on
    the length header before reaching one, so this fires only when the file is
    not an objstego stego mesh, or is being read with the wrong L.
    """
    lower, upper = table.find(abs(b - a))
    width = bit_width(lower, upper)
    offset = abs(b - a) - lower

    if offset >= (1 << width):
        raise StreamError(
            f"pair ({a}, {b}) has difference {abs(b - a)}, which is {offset} "
            f"above its range floor {lower} and cannot be expressed in the "
            f"{width} bits that range carries. Embedding never produces this, "
            "so the file was not written by objstego, or L is wrong."
        )

    return int_to_bits(offset, width)


# ---------------------------------------------------------------------------
# Whole-mesh embedding (SPEC 7)
# ---------------------------------------------------------------------------


def _pairs(count: int) -> range:
    """Indices of the first element of each non-overlapping pair (SPEC 5).

    A trailing odd coordinate has no partner and is left untouched. Hide and
    extract both take their pairing from here so they cannot drift apart.
    """
    return range(0, count - 1, 2)


def capacity_bits(coordinates: Sequence[int], table: RangeTable) -> int:
    """Total bits this coordinate stream can carry, header included.

    Counts only usable pairs. This is a measurement, not a permission check:
    SPEC 7 forbids pre-checking whether a payload fits, so hiding never calls
    it. Reporting and `-m random` do.
    """
    total = 0
    lows = [value % table.mod for value in coordinates]
    for index in _pairs(len(lows)):
        total += pair_capacity(lows[index], lows[index + 1], table)
    return total


@dataclasses.dataclass(frozen=True)
class HideResult:
    """The outcome of an embedding pass.

    `embedded_bits` below `stream_bits` means the payload did not fit. Deciding
    what to say about that belongs to the caller -- this module does not print.

    The pair counters describe the walk, which stops early once the payload is
    exhausted (SPEC 7). They are not a survey of the whole mesh; use
    :func:`capacity_bits` for that.
    """

    coordinates: List[int]
    embedded_bits: int
    stream_bits: int
    pairs_used: int
    pairs_skipped: int

    @property
    def complete(self) -> bool:
        """Did the entire payload fit?"""
        return self.embedded_bits >= self.stream_bits


def hide(
    coordinates: Sequence[int], payload: bytes, table: RangeTable
) -> HideResult:
    """Embed `payload` into a stream of scaled coordinates (SPEC 7).

    `coordinates` are exact integers at precision P; only each one's low `L`
    digits are touched, so no coordinate moves by as much as ``10**(L-P)`` in
    real units (SPEC 12.5).

    As much of the payload as fits is embedded and the rest is dropped -- the
    caller inspects :attr:`HideResult.complete` and warns. Pre-checking the fit
    is explicitly forbidden by SPEC 7.

    Deterministic: the same inputs always produce the same output.
    """
    stream = build_stream(payload)

    # Only the low part is modified; the high part is put back untouched.
    lows = [value % table.mod for value in coordinates]
    highs = [value - low for value, low in zip(coordinates, lows)]

    cursor = 0
    used = 0
    skipped = 0

    for index in _pairs(len(lows)):
        a, b = lows[index], lows[index + 1]
        lower, upper = table.find(abs(b - a))

        # The skip test comes first, and an unusable pair consumes no bits.
        # The extractor makes the same call on the same pair and reaches the
        # same verdict, which is how it reproduces the walk blind (SPEC 6).
        if not pair_usable(a, b, upper, table.mod):
            skipped += 1
            continue

        if cursor >= len(stream):
            break  # payload fully embedded; leave the rest of the mesh alone

        width = bit_width(lower, upper)
        # The final group may be short. Right-pad it with zeros: the length
        # header marks where the real payload ends, so the padding is inert.
        take = min(width, len(stream) - cursor)
        group = list(stream[cursor : cursor + take]) + [0] * (width - take)

        lows[index], lows[index + 1] = embed_pair(a, b, bits_to_int(group), table)
        cursor += take
        used += 1

    return HideResult(
        coordinates=[high + low for high, low in zip(highs, lows)],
        embedded_bits=cursor,
        stream_bits=len(stream),
        pairs_used=used,
        pairs_skipped=skipped,
    )
