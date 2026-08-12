"""Phase 7: SPEC 11's error table, case by case, plus the hostile-input corpus.

ROADMAP Phase 7 exit criterion -- no input in `tests/data/bad/` produces a
traceback.

SPEC 11 is a table of seven conditions with a required behaviour for each. Other
test modules cover most of them incidentally; this one covers them deliberately,
so that a regression shows up as a failure named after the rule it broke rather
than as a puzzling failure somewhere else.

The corpus sweep at the bottom is the blunt instrument: every file in `bad/`,
through both modes, asserting only that the process exits cleanly and says
something. Clean refusal and clean success are both fine. A traceback is not.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from objstego import extract, hide, payload_capacity
from objstego.bits import StreamError
from objstego.cli import EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from objstego.obj_io import ObjParseError, parse_obj

DATA = Path(__file__).parent / "data"
BAD = DATA / "bad"
SRC = Path(__file__).resolve().parents[1] / "src"

BAD_FILES = sorted(p for p in BAD.iterdir() if p.suffix == ".obj")

#: Files in bad/ that are legal OBJ and must be handled, not rejected.
LEGAL_BUT_RARE = {"scientific_notation.obj", "vertex_extra_tokens.obj", "single_vertex.obj"}


@pytest.fixture
def message(tmp_path):
    path = tmp_path / "message.txt"
    path.write_bytes(b"attack at dawn")
    return path


# ---------------------------------------------------------------------------
# SPEC 11, row by row
# ---------------------------------------------------------------------------


def test_missing_path_is_a_clean_nonzero_exit(tmp_path, message, capsys):
    """Row 1: missing / unreadable path."""
    code = main(["--hide", "-m", str(message), "-c", str(tmp_path / "absent.obj")])
    err = capsys.readouterr().err

    assert code == EXIT_ERROR
    assert "not found" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("name", ["empty.obj", "only_whitespace.obj", "no_vertices.obj"])
def test_file_with_no_vertices_is_handled(name, message, capsys):
    """Row 2: not valid OBJ, or no `v` lines."""
    code = main(["--hide", "-m", str(message), "-c", str(BAD / name)])
    err = capsys.readouterr().err

    assert code == EXIT_ERROR
    assert "no 'v' lines" in err
    assert "Traceback" not in err


def test_binary_garbage_is_handled(message, capsys):
    """Row 2, the ugly end of it."""
    code = main(["--hide", "-m", str(message), "-c", str(BAD / "binary_garbage.obj")])
    err = capsys.readouterr().err

    assert code == EXIT_ERROR
    assert "Traceback" not in err
    assert err.strip()


@pytest.mark.parametrize(
    "name",
    [
        "vertex_missing_z.obj",
        "vertex_no_coordinates.obj",
        "vertex_non_numeric.obj",
        "vertex_double_decimal.obj",
        "vertex_nan.obj",
        "comma_decimal.obj",
    ],
)
def test_malformed_vertex_lines_are_reported_with_a_line_number(name, message, capsys):
    """Row 2 again: a `v` line that cannot be parsed names the line it is on."""
    code = main(["--hide", "-m", str(message), "-c", str(BAD / name)])
    err = capsys.readouterr().err

    assert code == EXIT_ERROR
    assert "line " in err
    assert "Traceback" not in err


def test_nan_and_inf_are_rejected_rather_than_parsed():
    """float() accepts both. The decimal-string path must not (SPEC 3)."""
    for token in ("nan", "inf", "-inf", "Infinity"):
        with pytest.raises(ObjParseError):
            parse_obj(f"v {token} 2.000000 3.000000\n", 6)


def test_extra_tokens_on_a_vertex_line_survive_a_full_hide(tmp_path, capsys):
    """Row 3: `v` lines with 4+ tokens keep their extras untouched."""
    source = (BAD / "vertex_extra_tokens.obj").read_text()

    stego, _ = hide(source, b"")

    assert "1.0 0.5 0.25" in stego
    assert "0.9" in stego
    for before, after in zip(source.split("\n"), stego.split("\n")):
        if not before.startswith("v "):
            assert before == after


def test_scientific_notation_is_parsed_exactly():
    """Row 3's neighbour: legal OBJ, rare, must not be mis-parsed (SPEC 3)."""
    document = parse_obj((BAD / "scientific_notation.obj").read_text(), 6)

    assert document.coordinates()[:3] == [1500, -250_000_000, 3_000_000]


def test_message_larger_than_capacity_warns_and_exits_zero(tmp_path, capsys):
    """Row 4. The one error-shaped condition that is not an error."""
    cover = tmp_path / "car.obj"
    cover.write_bytes((DATA / "car.obj").read_bytes())
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 5000)

    code = main(["--hide", "-m", str(big), "-c", str(cover)])
    err = capsys.readouterr().err

    assert code == EXIT_OK
    assert "too large" in err
    assert (tmp_path / "car_stego.obj").exists()


def test_empty_message_file_is_handled(tmp_path, capsys):
    """Row 5."""
    cover = tmp_path / "car.obj"
    cover.write_bytes((DATA / "car.obj").read_bytes())
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")

    assert main(["--hide", "-m", str(empty), "-c", str(cover)]) == EXIT_OK
    assert main(["--extract", "-s", str(tmp_path / "car_stego.obj")]) == EXIT_OK
    capsys.readouterr()

    assert (tmp_path / "car_stego_payload.bin").read_bytes() == b""


@pytest.mark.parametrize(
    "argv",
    [
        ["--extract", "-s", "x.obj", "-m", "y.txt"],
        ["--hide", "--extract"],
        ["--hide", "-m", "y.txt", "-c", "x.obj", "-s", "z.obj"],
        [],
    ],
)
def test_incompatible_flag_combinations_are_usage_errors(argv, capsys):
    """Row 6."""
    code = main(argv)
    err = capsys.readouterr().err

    assert code == EXIT_USAGE
    assert "Traceback" not in err


@pytest.mark.parametrize("name", ["truncated_stego.obj", "implausible_header.obj"])
def test_implausible_headers_produce_no_output(name, tmp_path, capsys):
    """Row 7: a clear message and, critically, no junk file left behind."""
    target = tmp_path / "recovered.bin"

    code = main(["--extract", "-s", str(BAD / name), "-o", str(target)])
    err = capsys.readouterr().err

    assert code == EXIT_ERROR
    assert "no payload recovered" in err
    assert "Traceback" not in err
    assert not target.exists()


def test_the_implausible_header_really_does_claim_the_maximum():
    """The fixture is constructed; this pins that it still does what it claims."""
    with pytest.raises(StreamError, match="4294967295"):
        extract((BAD / "implausible_header.obj").read_text())


# ---------------------------------------------------------------------------
# The corpus sweep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", BAD_FILES, ids=lambda p: p.name)
def test_no_bad_input_produces_a_traceback_when_hiding(path, message, capsys):
    """ROADMAP Phase 7 exit criterion, hiding half."""
    code = main(["--hide", "-m", str(message), "-c", str(path)])
    captured = capsys.readouterr()

    assert code in (EXIT_OK, EXIT_ERROR)
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    assert (captured.err or captured.out).strip(), "silence is not an outcome"


@pytest.mark.parametrize("path", BAD_FILES, ids=lambda p: p.name)
def test_no_bad_input_produces_a_traceback_when_extracting(path, tmp_path, capsys):
    """ROADMAP Phase 7 exit criterion, extracting half."""
    code = main(["--extract", "-s", str(path), "-o", str(tmp_path / "out.bin")])
    captured = capsys.readouterr()

    assert code in (EXIT_OK, EXIT_ERROR)
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


@pytest.mark.parametrize("path", BAD_FILES, ids=lambda p: p.name)
def test_bad_input_never_crashes_the_real_process(path, tmp_path):
    """capsys can mask an exception escaping main(). A subprocess cannot."""
    message = tmp_path / "m.txt"
    message.write_bytes(b"hi")
    env = {"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"}

    proc = subprocess.run(
        [sys.executable, "-m", "objstego", "--hide", "-m", str(message), "-c", str(path)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode in (EXIT_OK, EXIT_ERROR)
    assert "Traceback" not in proc.stderr


@pytest.mark.parametrize("name", sorted(LEGAL_BUT_RARE))
def test_legal_but_rare_inputs_are_accepted(name):
    """The three files in bad/ that are not actually bad must still work."""
    source = (BAD / name).read_text()
    stego, result = hide(source, b"")

    assert parse_obj(stego, 6).vertex_count == parse_obj(source, 6).vertex_count
    assert result.stream_bits == 32


# ---------------------------------------------------------------------------
# Library-level guarantees
# ---------------------------------------------------------------------------


def test_the_public_api_never_leaks_an_unexpected_exception():
    """hide/extract raise only ObjParseError, StreamError or ValueError."""
    for path in BAD_FILES:
        source = path.read_bytes().decode("utf-8", "surrogateescape")
        for call in (lambda: hide(source, b"x"), lambda: extract(source)):
            try:
                call()
            except (ObjParseError, StreamError, ValueError):
                pass


def test_capacity_never_raises_on_a_parsable_mesh():
    for path in BAD_FILES:
        source = path.read_bytes().decode("utf-8", "surrogateescape")
        try:
            parse_obj(source, 6)
        except ObjParseError:
            continue
        assert payload_capacity(source) >= 0
