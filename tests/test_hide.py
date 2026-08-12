"""Phase 5: whole-mesh embedding.

ROADMAP Phase 5 exit criterion -- a short text file embeds into `tiny.obj` and
into a real mesh without error, and the output still loads in a mesh viewer.

The viewer check is a human one. What is machine-checkable is everything that
would make a viewer refuse the file, plus the SPEC 12 invariants: byte-identical
passthrough, exact precision, the displacement bound, and determinism.

`_read_back` is a deliberately independent reimplementation of extraction,
written against the pvd primitives. Phase 6 builds the real one; until then this
is what proves hide produced something recoverable rather than merely plausible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from objstego import DEFAULT_LOW, DEFAULT_PRECISION, hide, payload_capacity
from objstego.bits import HEADER_BITS, StreamError, parse_stream, unpack_header
from objstego.cli import EXIT_ERROR, EXIT_OK, main
from objstego.obj_io import parse_obj
from objstego.pvd import capacity_bits, extract_bits, pair_usable
from objstego.ranges import range_table

DATA = Path(__file__).parent / "data"
TINY = DATA / "tiny.obj"
CAR = DATA / "car.obj"
P = DEFAULT_PRECISION
L = DEFAULT_LOW


def _read_back(stego: str, precision: int = P, low: int = L) -> bytes:
    """Walk the stego mesh and recover the payload, using only pvd primitives.

    Stops as soon as the length header says it has everything, exactly as
    SPEC 8 specifies. Reading on would be wrong as well as wasteful: pairs past
    the payload were never written to, and one of them may sit in the top
    bucket's dead zone, which carries no valid bit group at all.
    """
    table = range_table(low)
    lows = [value % table.mod for value in parse_obj(stego, precision).coordinates()]

    bits: list[int] = []
    for index in range(0, len(lows) - 1, 2):
        a, b = lows[index], lows[index + 1]
        _, upper = table.find(abs(b - a))
        if not pair_usable(a, b, upper, table.mod):
            continue
        bits.extend(extract_bits(a, b, table))
        if len(bits) >= HEADER_BITS and len(bits) >= HEADER_BITS + unpack_header(bits):
            break
    return parse_stream(bits)


@pytest.fixture(params=["tiny", "car"])
def mesh(request):
    return (TINY if request.param == "tiny" else CAR).read_text()


# ---------------------------------------------------------------------------
# The exit criterion
# ---------------------------------------------------------------------------


def test_a_short_text_file_embeds_and_reads_back():
    """ROADMAP Phase 5's exit criterion, on the real mesh."""
    payload = b"attack at dawn"

    stego, result = hide(CAR.read_text(), payload)

    assert result.complete
    assert _read_back(stego) == payload


def test_car_mesh_capacity():
    """711 vertices, 1066 pairs, 70% of them usable."""
    cover = CAR.read_text()

    assert capacity_bits(parse_obj(cover, P).coordinates(), range_table(L)) == 5075
    assert payload_capacity(cover) == 630


def test_tiny_obj_cannot_hold_even_the_header():
    """tiny.obj is a parser fixture, not a capacity one.

    Four vertices give six pairs, only two of which are usable, for 14 bits --
    less than the 32-bit length header. It can never carry a payload, not even
    an empty one. Embedding into it must still succeed quietly and leave a
    valid mesh; SPEC 7 makes that a warning, not an error.
    """
    cover = TINY.read_text()

    assert capacity_bits(parse_obj(cover, P).coordinates(), range_table(L)) == 14
    assert payload_capacity(cover) == 0

    stego, result = hide(cover, b"")

    assert not result.complete
    assert result.embedded_bits == 14
    assert parse_obj(stego, P).vertex_count == 4


def test_tiny_obj_yields_no_payload_when_read_back():
    """Its bits are real but truncated, so framing rejects them cleanly."""
    stego, _ = hide(TINY.read_text(), b"hello")

    with pytest.raises(StreamError):
        _read_back(stego)


# ---------------------------------------------------------------------------
# SPEC 12 invariants
# ---------------------------------------------------------------------------


def test_non_vertex_lines_are_byte_identical(mesh):
    """SPEC 12.2. The car mesh brings mtllib, o, vn, vt, s, usemtl and f lines."""
    stego, _ = hide(mesh, b"payload")

    before = mesh.split("\n")
    after = stego.split("\n")
    assert len(before) == len(after)
    for original, rebuilt in zip(before, after):
        if not original.startswith("v "):
            assert original == rebuilt


def test_every_coordinate_keeps_exactly_p_decimals(mesh):
    """SPEC 12.3. Precision drift silently breaks extraction."""
    stego, _ = hide(mesh, b"payload")

    for line in stego.split("\n"):
        if line.startswith("v "):
            for token in line.split()[1:4]:
                assert len(token.split(".")[1]) == P


def test_no_coordinate_moves_more_than_the_bound(mesh):
    """SPEC 12.5: at most 10**(L-P) units on any axis, so 0.001 by default."""
    stego, _ = hide(mesh, b"payload" * 20)

    before = parse_obj(mesh, P).coordinates()
    after = parse_obj(stego, P).coordinates()
    assert len(before) == len(after)

    bound = 10 ** (L)  # in scaled units: 10**L over 10**P is 10**(L-P)
    for original, moved in zip(before, after):
        assert abs(moved - original) < bound


def test_hide_is_deterministic(mesh):
    """SPEC 12.4."""
    first, _ = hide(mesh, b"repeatable")
    second, _ = hide(mesh, b"repeatable")

    assert first == second


def test_an_empty_payload_still_produces_a_valid_mesh(mesh):
    """SPEC 12.6 and SPEC 11's empty-message case."""
    stego, result = hide(mesh, b"")

    assert result.stream_bits == 32  # header only
    assert parse_obj(stego, P).vertex_count == parse_obj(mesh, P).vertex_count


def test_an_empty_payload_round_trips_on_a_mesh_that_can_hold_it():
    stego, result = hide(CAR.read_text(), b"")

    assert result.complete
    assert _read_back(stego) == b""


def test_the_line_count_and_trailing_newline_survive(mesh):
    stego, _ = hide(mesh, b"payload")

    assert stego.count("\n") == mesh.count("\n")
    assert stego.endswith("\n") == mesh.endswith("\n")


# ---------------------------------------------------------------------------
# Payload shapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\x00",
        b"a",
        b"attack at dawn",
        "héllo — 世界 🎲".encode("utf-8"),
        bytes(range(256)),
    ],
)
def test_payload_types_round_trip_through_the_car_mesh(payload):
    stego, result = hide(CAR.read_text(), payload)

    assert result.complete
    assert _read_back(stego) == payload


def test_a_payload_filling_the_whole_capacity():
    cover = CAR.read_text()
    payload = bytes(range(256)) * (payload_capacity(cover) // 256)

    stego, result = hide(cover, payload)

    assert result.complete
    assert _read_back(stego) == payload


# ---------------------------------------------------------------------------
# Overflow (SPEC 7)
# ---------------------------------------------------------------------------


def test_an_oversized_payload_embeds_a_prefix_and_reports_it():
    """SPEC 7: do not pre-check the fit. Embed what fits, then say so."""
    cover = CAR.read_text()
    payload = b"x" * (payload_capacity(cover) + 500)

    stego, result = hide(cover, payload)

    assert not result.complete
    assert result.embedded_bits < result.stream_bits
    assert result.embedded_bits == 5075  # every usable bit was consumed
    assert parse_obj(stego, P).vertex_count == parse_obj(cover, P).vertex_count


def test_capacity_is_the_exact_boundary_between_fitting_and_not():
    cover = CAR.read_text()
    limit = payload_capacity(cover)

    assert hide(cover, b"x" * limit)[1].complete
    assert not hide(cover, b"x" * (limit + 1))[1].complete


# ---------------------------------------------------------------------------
# The walk (SPEC 5, 6, 7)
# ---------------------------------------------------------------------------


def test_unusable_pairs_are_left_untouched():
    """A skipped pair consumes no bits and keeps its exact cover value."""
    cover = CAR.read_text()
    stego, result = hide(cover, b"z" * 40)

    table = range_table(L)
    before = parse_obj(cover, P).coordinates()
    after = parse_obj(stego, P).coordinates()

    skipped_unchanged = 0
    for index in range(0, len(before) - 1, 2):
        a, b = before[index] % table.mod, before[index + 1] % table.mod
        _, upper = table.find(abs(b - a))
        if not pair_usable(a, b, upper, table.mod):
            assert after[index] == before[index]
            assert after[index + 1] == before[index + 1]
            skipped_unchanged += 1

    # The walk stops once the payload is exhausted, so the reported count covers
    # only the skips it reached -- never more than the mesh actually contains.
    assert 0 < result.pairs_skipped <= skipped_unchanged


def test_a_trailing_odd_coordinate_is_never_touched():
    """SPEC 5. car.obj has 2133 coordinates, so exactly one is unpaired."""
    cover = CAR.read_text()
    before = parse_obj(cover, P).coordinates()
    assert len(before) % 2 == 1

    stego, _ = hide(cover, b"x" * 600)
    after = parse_obj(stego, P).coordinates()

    assert after[-1] == before[-1]


def test_pairs_beyond_the_payload_are_left_alone():
    """Embedding stops once the stream is exhausted, leaving the rest of the mesh
    byte-identical -- which is most of it for a small payload."""
    cover = CAR.read_text()
    stego, result = hide(cover, b"hi")

    before = parse_obj(cover, P).coordinates()
    after = parse_obj(stego, P).coordinates()
    changed = sum(1 for x, y in zip(before, after) if x != y)

    assert result.stream_bits == 48  # 32-bit header + 2 payload bytes
    assert changed <= 2 * result.pairs_used
    assert changed < len(before) // 10


def test_negative_coordinates_round_trip_through_hiding():
    """car.obj has 641 of them; floor-modulo must absorb the sign (SPEC 3)."""
    cover = CAR.read_text()
    stego, _ = hide(cover, b"negative coordinates")

    after = parse_obj(stego, P).coordinates()
    assert sum(1 for value in after if value < 0) > 0
    assert _read_back(stego) == b"negative coordinates"


# ---------------------------------------------------------------------------
# Other values of L
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("low", [1, 2, 3, 4])
def test_round_trip_at_other_values_of_l(low):
    """L is the capacity/distortion knob; every setting must round-trip."""
    cover = CAR.read_text()
    payload = b"tunable"

    stego, result = hide(cover, payload, low=low)

    assert result.complete
    assert _read_back(stego, low=low) == payload


def test_capacity_grows_with_l():
    cover = CAR.read_text()
    capacities = [payload_capacity(cover, low=low) for low in (1, 2, 3, 4)]

    assert capacities == sorted(capacities)
    assert capacities[0] < capacities[-1]


def test_smaller_l_moves_coordinates_less():
    """The whole point of L: it trades capacity against distortion."""
    cover = CAR.read_text()
    before = parse_obj(cover, P).coordinates()

    worst = {}
    for low in (1, 3):
        stego, _ = hide(cover, b"x" * 20, low=low)
        after = parse_obj(stego, P).coordinates()
        worst[low] = max(abs(x - y) for x, y in zip(before, after))

    assert worst[1] < 10
    assert worst[1] < worst[3]


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("precision,low", [(0, 1), (6, 0), (3, 4), (6, -1)])
def test_invalid_parameters_are_rejected(precision, low):
    with pytest.raises(ValueError):
        hide("v 1.0 2.0 3.0\n", b"x", precision=precision, low=low)


def test_a_mesh_with_no_vertices_carries_nothing():
    stego, result = hide("# just a comment\nf 1 2 3\n", b"payload")

    assert not result.complete
    assert result.embedded_bits == 0
    assert stego == "# just a comment\nf 1 2 3\n"


# ---------------------------------------------------------------------------
# Through the CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    cover = tmp_path / "car.obj"
    cover.write_bytes(CAR.read_bytes())
    message = tmp_path / "secret.txt"
    message.write_bytes(b"attack at dawn")
    return tmp_path, cover, message


def test_cli_hide_writes_the_default_output_name(workspace, capsys):
    tmp_path, cover, message = workspace

    code = main(["--hide", "-m", str(message), "-c", str(cover)])
    out = capsys.readouterr().out

    assert code == EXIT_OK
    stego = tmp_path / "car_stego.obj"
    assert stego.exists()
    assert _read_back(stego.read_text()) == b"attack at dawn"
    assert "hid 14 of 14 bytes" in out


def test_cli_reports_payload_bytes_not_header_bits(workspace, capsys):
    """Regression: the summary counted the 32-bit header as payload, so a
    14-byte message was reported as "hid 17 of 14 bytes"."""
    _, cover, message = workspace

    main(["--hide", "-m", str(message), "-c", str(cover)])
    out = capsys.readouterr().out

    assert "hid 14 of 14 bytes" in out


def test_cli_warns_on_an_oversized_payload_and_still_exits_zero(workspace, capsys):
    """SPEC 11: embed what fits, warn, exit 0."""
    tmp_path, cover, _ = workspace
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 2000)

    code = main(["--hide", "-m", str(big), "-c", str(cover)])
    captured = capsys.readouterr()

    assert code == EXIT_OK
    assert "message too large" in captured.err
    assert "1370 bytes were dropped" in captured.err
    assert (tmp_path / "car_stego.obj").exists()


def test_cli_random_fills_the_capacity(workspace, capsys):
    tmp_path, cover, _ = workspace

    code = main(["--hide", "-m", "random", "-c", str(cover)])
    captured = capsys.readouterr()

    assert code == EXIT_OK
    assert "hid 630 of 630 bytes" in captured.out
    assert captured.err == ""
    assert len(_read_back((tmp_path / "car_stego.obj").read_text())) == 630


def test_cli_rejects_a_mesh_with_no_vertices(tmp_path, capsys):
    cover = tmp_path / "flat.obj"
    cover.write_text("# nothing here\nf 1 2 3\n")
    message = tmp_path / "m.txt"
    message.write_bytes(b"hi")

    code = main(["--hide", "-m", str(message), "-c", str(cover)])
    err = capsys.readouterr().err

    assert code == EXIT_ERROR
    assert "no 'v' lines" in err
    assert "Traceback" not in err


def test_cli_hide_leaves_the_cover_untouched(workspace, capsys):
    _, cover, message = workspace
    before = cover.read_bytes()

    main(["--hide", "-m", str(message), "-c", str(cover)])
    capsys.readouterr()

    assert cover.read_bytes() == before
