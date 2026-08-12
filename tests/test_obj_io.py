"""Phase 2: OBJ read/write round trip with exact decimal handling.

ROADMAP Phase 2 exit criterion -- loading and re-writing `tiny.obj` with no
embedding produces a file whose non-`v` lines are byte-identical and whose `v`
lines are numerically identical at precision P, negative coordinates included.

The float-avoidance tests (SPEC 3) matter more than they look: a one-ULP error
in a coordinate's low digits corrupts extraction from that pair onward.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from objstego import DEFAULT_PRECISION
from objstego.obj_io import (
    ObjParseError,
    format_coordinate,
    parse_coordinate,
    parse_obj,
    read_obj,
    render_obj,
    write_obj,
)

TINY = Path(__file__).parent / "data" / "tiny.obj"
P = DEFAULT_PRECISION


# ---------------------------------------------------------------------------
# Coordinate primitives (SPEC 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [
        ("1.234567", 1234567),
        ("-0.891234", -891234),
        ("3.000010", 3000010),
        ("0.000000", 0),
        ("-0.000500", -500),
        ("12.345678", 12345678),
        ("-5.400000", -5400000),
        ("0.000001", 1),
    ],
)
def test_parse_coordinate_matches_the_tiny_fixture(token, expected):
    assert parse_coordinate(token, P) == expected


@pytest.mark.parametrize(
    "token,expected",
    [
        ("1", 1000000),  # no fractional part at all
        ("1.", 1000000),
        (".5", 500000),
        ("-.5", -500000),
        ("+1.5", 1500000),
        ("1.5", 1500000),
        ("00001.500000", 1500000),
    ],
)
def test_parse_coordinate_accepts_the_legal_shorthands(token, expected):
    assert parse_coordinate(token, P) == expected


@pytest.mark.parametrize(
    "token,expected",
    [
        ("1.5e-3", 1500),
        ("1.5E-3", 1500),
        ("-1.5e-3", -1500),
        ("1e2", 100000000),
        ("1.234567e0", 1234567),
    ],
)
def test_parse_coordinate_handles_scientific_notation(token, expected):
    """SPEC 3: legal but rare. Handle it exactly or reject it -- never mis-parse."""
    assert parse_coordinate(token, P) == expected


def test_parse_coordinate_truncates_rather_than_rounds():
    """SPEC 3 says pad or truncate to exactly P digits. 8 would round up."""
    assert parse_coordinate("1.2345678", P) == 1234567
    assert parse_coordinate("-1.2345678", P) == -1234567


def test_parse_coordinate_is_exact_where_float_would_not_be():
    """The reason SPEC 3 forbids the float path, stated as an executable case.

    It takes a large coordinate to expose this at P=6, but the failure mode is
    silent and unrecoverable when it happens: `low` is wrong, so every pair from
    there on decodes to garbage.
    """
    token = "244741255286.655659"

    assert parse_coordinate(token, P) == 244741255286655659
    # The naive implementation the spec rules out, off by 21 on this input:
    assert round(float(token) * 10**P) == 244741255286655680


def test_low_digits_are_exact_for_the_float_counterexample():
    """What actually matters: `V mod 1000`, the carrier itself (SPEC 3)."""
    token = "244741255286.655659"

    assert parse_coordinate(token, P) % 1000 == 659
    assert round(float(token) * 10**P) % 1000 == 680


@pytest.mark.parametrize(
    "token", ["", "   ", "abc", "1.2.3", ".", "-", "1,5", "nan", "inf", "0x10", "1_000"]
)
def test_parse_coordinate_rejects_non_numbers(token):
    with pytest.raises(ObjParseError):
        parse_coordinate(token, P)


@pytest.mark.parametrize(
    "value,expected",
    [
        (1234567, "1.234567"),
        (-891234, "-0.891234"),
        (0, "0.000000"),
        (-500, "-0.000500"),
        (1, "0.000001"),
        (-1, "-0.000001"),
        (12345678, "12.345678"),
    ],
)
def test_format_coordinate(value, expected):
    assert format_coordinate(value, P) == expected


def test_format_coordinate_never_emits_negative_zero():
    assert format_coordinate(0, P) == "0.000000"
    assert not format_coordinate(0, P).startswith("-")


@pytest.mark.parametrize("precision", [1, 2, 3, 6, 9, 15])
@pytest.mark.parametrize("value", [0, 1, -1, 999, -999, 123456789, -123456789])
def test_format_then_parse_is_the_identity(value, precision):
    assert parse_coordinate(format_coordinate(value, precision), precision) == value


def test_every_rendered_coordinate_has_exactly_p_decimals():
    """SPEC 12.3. Precision drift silently breaks extraction."""
    for value in (0, 1, -1, 7, -7, 10**9, -(10**9)):
        for precision in (1, 3, 6, 12):
            rendered = format_coordinate(value, precision)
            assert len(rendered.split(".")[1]) == precision


# ---------------------------------------------------------------------------
# Phase 2 exit criterion
# ---------------------------------------------------------------------------


def test_tiny_obj_round_trips_byte_for_byte():
    """The fixture is already at P=6, so the whole file should be unchanged."""
    original = TINY.read_bytes()
    document = read_obj(TINY, P)

    assert render_obj(document).encode() == original


def test_tiny_obj_non_vertex_lines_are_byte_identical():
    """SPEC 12.2, checked line by line rather than in aggregate."""
    original = TINY.read_text().split("\n")
    rebuilt = render_obj(read_obj(TINY, P)).split("\n")

    assert len(original) == len(rebuilt)
    for before, after in zip(original, rebuilt):
        if not before.startswith("v "):
            assert before == after


def test_tiny_obj_negative_coordinates_survive():
    document = read_obj(TINY, P)
    coordinates = document.coordinates()

    assert -891234 in coordinates
    assert -1999999 in coordinates
    assert -5400000 in coordinates
    assert -500 in coordinates
    assert "-0.891234" in render_obj(document)
    assert "-0.000500" in render_obj(document)


def test_tiny_obj_vertex_and_coordinate_counts():
    document = read_obj(TINY, P)

    assert document.vertex_count == 4
    assert len(document.coordinates()) == 12


def test_coordinates_are_flattened_in_file_order():
    """SPEC 5: x, y, z, x, y, z, ... This ordering is shared by hide and extract."""
    document = read_obj(TINY, P)

    assert document.coordinates()[:6] == [1234567, -891234, 3000010, 2345890, 500000, -1999999]


def test_write_then_read_preserves_bytes(tmp_path):
    document = read_obj(TINY, P)
    target = tmp_path / "out.obj"

    write_obj(target, render_obj(document))

    assert target.read_bytes() == TINY.read_bytes()


# ---------------------------------------------------------------------------
# Substituting coordinates
# ---------------------------------------------------------------------------


def test_render_substitutes_new_coordinates():
    document = read_obj(TINY, P)
    coordinates = document.coordinates()
    coordinates[0] = 1234512  # the golden vector's a', SPEC 9

    rendered = render_obj(document, coordinates)

    assert "v 1.234512 -0.891234 3.000010" in rendered


def test_substitution_leaves_non_vertex_lines_alone():
    document = read_obj(TINY, P)
    coordinates = [0] * len(document.coordinates())

    rendered = render_obj(document, coordinates)

    assert "# tiny.obj - hand-checkable fixture" in rendered
    assert "f 1 2 3" in rendered
    assert rendered.count("v 0.000000 0.000000 0.000000") == 4


def test_render_rejects_a_wrong_length_coordinate_stream():
    document = read_obj(TINY, P)

    with pytest.raises(ValueError, match="expected 12 coordinates"):
        render_obj(document, [0] * 11)


# ---------------------------------------------------------------------------
# Formatting and layout preservation
# ---------------------------------------------------------------------------


def test_extra_tokens_on_a_vertex_line_are_preserved(tmp_path):
    """SPEC 5: only the first three numeric tokens participate."""
    source = "v 1.000000 2.000000 3.000000 0.5 1.0 0.0 0.25\nf 1 1 1\n"
    document = parse_obj(source, P)

    assert document.coordinates() == [1000000, 2000000, 3000000]
    assert render_obj(document) == source

    rendered = render_obj(document, [4000000, 5000000, 6000000])
    assert rendered == "v 4.000000 5.000000 6.000000 0.5 1.0 0.0 0.25\nf 1 1 1\n"


def test_unusual_whitespace_is_preserved():
    source = "  v\t1.000000   2.000000\t\t3.000000  \n"
    document = parse_obj(source, P)

    assert document.coordinates() == [1000000, 2000000, 3000000]
    assert render_obj(document) == source


def test_crlf_line_endings_are_preserved():
    source = "# comment\r\nv 1.000000 2.000000 3.000000\r\nf 1 1 1\r\n"
    document = parse_obj(source, P)

    assert render_obj(document) == source
    assert "\r\n" in render_obj(document, [0, 0, 0])


def test_missing_final_newline_is_not_invented():
    source = "v 1.000000 2.000000 3.000000"
    document = parse_obj(source, P)

    assert render_obj(document) == source
    assert not render_obj(document).endswith("\n")


def test_vertex_lines_are_normalised_to_p_decimals():
    """Input at the wrong precision is rewritten; that is the point of P."""
    source = "v 1.5 -2 3.1234567890\n"
    document = parse_obj(source, P)

    assert render_obj(document) == "v 1.500000 -2.000000 3.123456\n"


@pytest.mark.parametrize("keyword", ["vn", "vt", "vp"])
def test_other_v_prefixed_keywords_are_not_vertices(keyword):
    """vn/vt/vp are normals, texture coords and parameter vertices -- not carriers."""
    source = f"{keyword} 1.5 2.5 3.5\nv 1.000000 2.000000 3.000000\n"
    document = parse_obj(source, P)

    assert document.vertex_count == 1
    assert render_obj(document).startswith(f"{keyword} 1.5 2.5 3.5\n")


def test_blank_lines_and_comments_pass_through():
    source = "# header\n\n\nv 1.000000 2.000000 3.000000\n\n# trailing\n"
    document = parse_obj(source, P)

    assert render_obj(document) == source


def test_non_utf8_bytes_survive(tmp_path):
    """A comment in some legacy encoding must not break the passthrough guarantee."""
    source = b"# caf\xe9 latin-1\nv 1.000000 2.000000 3.000000\nf 1 1 1\n"
    mesh = tmp_path / "legacy.obj"
    mesh.write_bytes(source)

    document = read_obj(mesh, P)
    target = tmp_path / "out.obj"
    write_obj(target, render_obj(document))

    assert target.read_bytes() == source


# ---------------------------------------------------------------------------
# Error handling (SPEC 11)
# ---------------------------------------------------------------------------


def test_file_with_no_vertices_parses_as_empty():
    """Whether that is fatal is the caller's decision, not the parser's."""
    document = parse_obj("# just a comment\nf 1 2 3\n", P)

    assert document.vertex_count == 0
    assert document.coordinates() == []


def test_empty_file_parses():
    document = parse_obj("", P)

    assert document.vertex_count == 0
    assert render_obj(document) == ""


@pytest.mark.parametrize(
    "source,message",
    [
        ("v 1.0 2.0\n", "three coordinates"),
        ("v\n", "three coordinates"),
        ("v 1.0\n", "three coordinates"),
        ("v 1.0 abc 3.0\n", "not a number"),
    ],
)
def test_malformed_vertex_lines_raise_a_readable_error(source, message):
    with pytest.raises(ObjParseError, match=message):
        parse_obj(source, P)


def test_parse_error_reports_the_line_number():
    source = "# header\nv 1.0 2.0 3.0\nv 1.0 2.0\n"

    with pytest.raises(ObjParseError, match="line 3"):
        parse_obj(source, P)


def test_reading_a_missing_file_raises_obj_parse_error(tmp_path):
    with pytest.raises(ObjParseError, match="cannot read"):
        read_obj(tmp_path / "nope.obj", P)


def test_binary_garbage_does_not_crash(tmp_path):
    """SPEC 11: not valid OBJ -- handled, no traceback."""
    mesh = tmp_path / "garbage.obj"
    mesh.write_bytes(bytes(range(256)))

    try:
        document = read_obj(mesh, P)
    except ObjParseError:
        pass  # a clean refusal is an acceptable outcome
    else:
        assert document.vertex_count == 0
