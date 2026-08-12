"""Phase 6: blind extraction.

ROADMAP Phase 6 exit criterion -- ``extract(hide(msg, cover)) == msg``
byte-for-byte on every fixture mesh, for ASCII text, UTF-8 with multibyte
characters, a small binary blob, and an empty file.

Narrowed, deliberately: `tiny.obj` and `cube.obj` hold less than the 32-bit
length header, so there is no payload to recover from them and the criterion
cannot apply. They are tested for a clean refusal instead, which is the
behaviour that actually matters for them.

"Blind" is the claim under test throughout. Nothing here passes a cover mesh,
a key, or a bit count to `extract` -- only the stego text and the parameters a
recipient would have been told.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from objstego import DEFAULT_LOW, DEFAULT_PRECISION, extract, hide, payload_capacity
from objstego.bits import StreamError
from objstego.cli import EXIT_ERROR, EXIT_OK, main
from objstego.obj_io import parse_obj

DATA = Path(__file__).parent / "data"
P = DEFAULT_PRECISION
L = DEFAULT_LOW

#: Meshes with room for a payload. tiny.obj and cube.obj are handled separately.
CARRIERS = ["car.obj", "suzanne.obj"]

#: The payload types ROADMAP Phase 6 names, plus a couple of awkward edges.
PAYLOADS = {
    "ascii": b"attack at dawn",
    "utf8": "héllo — 世界 🎲 naïve façade".encode("utf-8"),
    "binary": bytes(range(256)),
    "empty": b"",
    "single-null": b"\x00",
    "all-ones": b"\xff" * 32,
}


@pytest.fixture(params=CARRIERS)
def carrier(request):
    return (DATA / request.param).read_text()


# ---------------------------------------------------------------------------
# The exit criterion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_round_trip(carrier, name):
    """SPEC 12.1, over every carrier mesh and every payload type."""
    payload = PAYLOADS[name]

    stego, result = hide(carrier, payload)

    assert result.complete
    assert extract(stego) == payload


def test_round_trip_of_a_payload_filling_the_entire_capacity(carrier):
    payload = bytes(range(256)) * (payload_capacity(carrier) // 256)

    stego, result = hide(carrier, payload)

    assert result.complete
    assert extract(stego) == payload


def test_extraction_needs_only_the_stego_text(carrier):
    """The blindness claim, made literal: the cover is discarded before reading."""
    payload = b"no cover required"
    stego, _ = hide(carrier, payload)

    del carrier  # nothing below may consult it

    assert extract(stego) == payload


def test_round_trip_survives_a_write_and_read_cycle(tmp_path, carrier):
    """Through the filesystem, as a recipient would actually receive it."""
    payload = "fichier — 파일".encode("utf-8")
    stego, _ = hide(carrier, payload)
    path = tmp_path / "received.obj"
    path.write_bytes(stego.encode("utf-8"))

    assert extract(path.read_bytes().decode("utf-8")) == payload


@pytest.mark.parametrize("low", [1, 2, 3, 4])
def test_round_trip_at_every_value_of_l(low):
    cover = (DATA / "car.obj").read_text()
    payload = b"tunable"

    stego, result = hide(cover, payload, low=low)

    assert result.complete
    assert extract(stego, low=low) == payload


# ---------------------------------------------------------------------------
# Reproducing the walk (SPEC 6)
# ---------------------------------------------------------------------------


def test_extraction_reproduces_hundreds_of_skip_decisions():
    """The property the SPEC 6 amendment exists to guarantee.

    car.obj skips 319 pairs. The extractor never sees the cover, so every one
    of those skips has to be re-derived from the stego coordinates alone. One
    disagreement shifts every later bit and the payload is lost.
    """
    cover = (DATA / "car.obj").read_text()
    payload = b"x" * payload_capacity(cover)

    stego, result = hide(cover, payload)

    assert result.pairs_skipped == 319
    assert extract(stego) == payload


def test_pairs_after_the_payload_do_not_corrupt_it(carrier):
    """Most of the mesh is untouched; the header is what stops the read."""
    payload = b"tiny"
    stego, result = hide(carrier, payload)

    assert result.pairs_used < 20  # the vast majority of pairs are untouched
    assert extract(stego) == payload


def test_extracting_from_an_unmodified_cover_is_not_a_crash(carrier):
    """A plain mesh is not a stego mesh. Whatever happens, it is not a traceback."""
    try:
        recovered = extract(carrier)
    except StreamError:
        pass  # the expected outcome
    else:
        assert isinstance(recovered, bytes)


# ---------------------------------------------------------------------------
# Failure modes (SPEC 8, SPEC 11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mesh", ["tiny.obj", "cube.obj"])
def test_meshes_too_small_to_hold_a_header_refuse_cleanly(mesh):
    """Below 32 bits there is no length to read, so there is nothing to return."""
    cover = (DATA / mesh).read_text()
    assert payload_capacity(cover) == 0

    stego, _ = hide(cover, b"hello")

    with pytest.raises(StreamError, match="length header"):
        extract(stego)


def test_a_truncated_stego_mesh_is_refused():
    """Most vertices removed: the header outlives the payload it describes.

    car.obj puts its whole vertex block near the top, so the cut has to be made
    by counting `v` lines rather than by slicing a fraction of the file.
    """
    cover = (DATA / "car.obj").read_text()
    stego, _ = hide(cover, b"y" * 400)

    kept: list[str] = []
    vertices = 0
    for line in stego.split("\n"):
        if line.startswith("v "):
            vertices += 1
            if vertices > 200:
                continue
        kept.append(line)
    truncated = "\n".join(kept)

    assert parse_obj(truncated, P).vertex_count == 200

    with pytest.raises(StreamError, match="claims"):
        extract(truncated)


def test_reading_with_the_wrong_l_does_not_return_junk():
    """L defines the carrier and the range table; the wrong one must not silently
    produce plausible-looking bytes."""
    cover = (DATA / "car.obj").read_text()
    stego, _ = hide(cover, b"secret message here", low=3)

    for wrong in (1, 2, 4):
        try:
            recovered = extract(stego, low=wrong)
        except StreamError:
            continue
        assert recovered != b"secret message here"


def test_an_overflowed_hide_cannot_be_extracted():
    """hide warns and embeds a prefix; the header then describes more than the
    mesh holds, so extraction refuses rather than returning the fragment."""
    cover = (DATA / "car.obj").read_text()
    payload = b"z" * (payload_capacity(cover) + 100)

    stego, result = hide(cover, payload)
    assert not result.complete

    with pytest.raises(StreamError, match="claims"):
        extract(stego)


def test_garbage_geometry_is_refused_or_returns_bytes(tmp_path):
    """SPEC 11: an implausible header must not produce junk output."""
    source = "".join(
        f"v {i % 7}.{i * 137 % 1000:06d} {i}.000000 -{i % 3}.{i * 31 % 1000:06d}\n"
        for i in range(200)
    )

    try:
        recovered = extract(source)
    except StreamError:
        pass
    else:
        assert isinstance(recovered, bytes)


@pytest.mark.parametrize("precision,low", [(0, 1), (6, 0), (3, 4)])
def test_invalid_parameters_are_rejected(precision, low):
    with pytest.raises(ValueError):
        extract("v 1.0 2.0 3.0\n", precision=precision, low=low)


# ---------------------------------------------------------------------------
# Through the CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    cover = tmp_path / "car.obj"
    cover.write_bytes((DATA / "car.obj").read_bytes())
    message = tmp_path / "secret.txt"
    message.write_bytes("héllo — 世界".encode("utf-8"))
    return tmp_path, cover, message


def test_cli_hide_then_extract_round_trips(workspace, capsys):
    """The whole tool, end to end, the way a user drives it."""
    tmp_path, cover, message = workspace

    assert main(["--hide", "-m", str(message), "-c", str(cover)]) == EXIT_OK
    stego = tmp_path / "car_stego.obj"

    assert main(["--extract", "-s", str(stego)]) == EXIT_OK
    out = capsys.readouterr().out

    recovered = tmp_path / "car_stego_payload.bin"
    assert recovered.read_bytes() == message.read_bytes()
    assert "recovered 17 bytes" in out


def test_cli_extract_honours_an_explicit_output_path(workspace, capsys):
    tmp_path, cover, message = workspace
    main(["--hide", "-m", str(message), "-c", str(cover)])
    target = tmp_path / "recovered.txt"

    code = main(["--extract", "-s", str(tmp_path / "car_stego.obj"), "-o", str(target)])
    capsys.readouterr()

    assert code == EXIT_OK
    assert target.read_bytes() == message.read_bytes()


def test_cli_extract_round_trips_a_binary_payload(workspace, capsys):
    tmp_path, cover, _ = workspace
    blob = tmp_path / "blob.bin"
    blob.write_bytes(bytes(range(256)))

    main(["--hide", "-m", str(blob), "-c", str(cover)])
    main(["--extract", "-s", str(tmp_path / "car_stego.obj")])
    capsys.readouterr()

    assert (tmp_path / "car_stego_payload.bin").read_bytes() == bytes(range(256))


def test_cli_extract_round_trips_an_empty_payload(workspace, capsys):
    tmp_path, cover, _ = workspace
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")

    main(["--hide", "-m", str(empty), "-c", str(cover)])
    main(["--extract", "-s", str(tmp_path / "car_stego.obj")])
    capsys.readouterr()

    assert (tmp_path / "car_stego_payload.bin").read_bytes() == b""


def test_cli_extract_writes_nothing_when_it_fails(tmp_path, capsys):
    """SPEC 11: no junk output. A failed read must not leave a file behind."""
    plain = tmp_path / "plain.obj"
    plain.write_bytes((DATA / "cube.obj").read_bytes())

    code = main(["--extract", "-s", str(plain)])
    err = capsys.readouterr().err

    assert code == EXIT_ERROR
    assert "no payload recovered" in err
    assert "Traceback" not in err
    assert not (tmp_path / "plain_payload.bin").exists()


def test_cli_extract_respects_the_l_flag(workspace, capsys):
    tmp_path, cover, message = workspace
    main(["--hide", "-m", str(message), "-c", str(cover), "-L", "2"])
    target = tmp_path / "out.bin"

    code = main(
        ["--extract", "-s", str(tmp_path / "car_stego.obj"), "-o", str(target), "-L", "2"]
    )
    capsys.readouterr()

    assert code == EXIT_OK
    assert target.read_bytes() == message.read_bytes()


def test_cli_warns_that_a_cube_carries_nothing(tmp_path, capsys):
    cover = tmp_path / "cube.obj"
    cover.write_bytes((DATA / "cube.obj").read_bytes())
    message = tmp_path / "m.txt"
    message.write_bytes(b"this will not fit anywhere")

    code = main(["--hide", "-m", str(message), "-c", str(cover)])
    err = capsys.readouterr().err

    assert code == EXIT_OK  # SPEC 7: a warning, not an error
    assert "no usable vertex pairs" in err
    assert (tmp_path / "cube_stego.obj").read_bytes() == cover.read_bytes()
