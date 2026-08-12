"""Phase 3: bit utilities and the 32-bit length header.

ROADMAP Phase 3 exit criterion -- unit tests pass, including an empty payload
and bit counts that are not a whole number of bytes.

The MSB-first and big-endian conventions tested here are format-defining
(SPEC 4). Reversing either one breaks every previously produced stego file, so
these tests pin the byte order deliberately rather than incidentally.
"""

from __future__ import annotations

import random

import pytest

from objstego.bits import (
    HEADER_BITS,
    MAX_PAYLOAD_BITS,
    StreamError,
    bits_to_bytes,
    bits_to_int,
    build_stream,
    bytes_to_bits,
    int_to_bits,
    pack_header,
    parse_stream,
    unpack_header,
)


# ---------------------------------------------------------------------------
# bytes -> bits, MSB first
# ---------------------------------------------------------------------------


def test_bytes_to_bits_is_msb_first():
    """The convention, stated unambiguously: 0x80 is a leading 1, not a trailing one."""
    assert bytes_to_bits(b"\x80") == [1, 0, 0, 0, 0, 0, 0, 0]
    assert bytes_to_bits(b"\x01") == [0, 0, 0, 0, 0, 0, 0, 1]


def test_bytes_to_bits_golden_vector_payload():
    """SPEC 9's payload byte: 178 == 0xb2 == 10110010."""
    assert bytes_to_bits(b"\xb2") == [1, 0, 1, 1, 0, 0, 1, 0]
    assert bits_to_int(bytes_to_bits(b"\xb2")) == 178


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"", []),
        (b"\x00", [0] * 8),
        (b"\xff", [1] * 8),
        (b"A", [0, 1, 0, 0, 0, 0, 0, 1]),
    ],
)
def test_bytes_to_bits_known_vectors(data, expected):
    assert bytes_to_bits(data) == expected


def test_byte_order_across_multiple_bytes():
    """Earlier bytes come first; within each, the high bit leads."""
    assert bytes_to_bits(b"\x01\x80") == [0] * 7 + [1, 1] + [0] * 7


# ---------------------------------------------------------------------------
# bits -> bytes
# ---------------------------------------------------------------------------


def test_bits_to_bytes_pads_a_partial_final_group():
    """SPEC 7's right-padding rule; the header is what marks the real end."""
    assert bits_to_bytes([1]) == b"\x80"
    assert bits_to_bytes([1, 1, 1]) == b"\xe0"
    assert bits_to_bytes([1] * 9) == b"\xff\x80"


def test_bits_to_bytes_of_nothing_is_empty():
    assert bits_to_bytes([]) == b""


@pytest.mark.parametrize("bad", [2, -1, None, "1", 1.0])
def test_bits_to_bytes_rejects_non_binary_values(bad):
    with pytest.raises(ValueError):
        bits_to_bytes([0, 1, bad])


@pytest.mark.parametrize("bad", [2, -1, None, "1", 1.0])
def test_bits_to_int_rejects_non_binary_values(bad):
    with pytest.raises(ValueError):
        bits_to_int([0, 1, bad])


@pytest.mark.parametrize("bad", [1.0, 0.0, True and 1.0])
def test_a_float_is_rejected_as_a_value_error_not_a_type_error(bad):
    """Regression: `1.0 == 1`, so a value-only guard let floats through."""
    with pytest.raises(ValueError, match="must be 0 or 1"):
        bits_to_bytes([bad])
    with pytest.raises(ValueError, match="must be 0 or 1"):
        bits_to_int([bad])


def test_booleans_are_accepted_as_bits():
    """They are ints, and genuinely 0/1 -- rejecting them would be pedantry."""
    assert bits_to_int([True, False, True]) == 5
    assert bits_to_bytes([True] * 8) == b"\xff"


def test_bits_to_bytes_accepts_any_iterable():
    assert bits_to_bytes(iter([1, 1, 1, 1, 0, 0, 0, 0])) == b"\xf0"


# ---------------------------------------------------------------------------
# Round trip (ROADMAP Phase 3 property test)
# ---------------------------------------------------------------------------


def test_round_trip_of_the_empty_payload():
    assert bits_to_bytes(bytes_to_bits(b"")) == b""


@pytest.mark.parametrize("length", [0, 1, 2, 3, 7, 8, 9, 15, 16, 31, 32, 255, 1024])
def test_round_trip_at_many_lengths(length):
    payload = bytes(random.Random(length).getrandbits(8) for _ in range(length))

    assert bits_to_bytes(bytes_to_bits(payload)) == payload


def test_round_trip_over_random_payloads():
    """bits_to_bytes(bytes_to_bits(b)) == b, for arbitrary b."""
    rng = random.Random(20260812)
    for _ in range(500):
        payload = bytes(rng.getrandbits(8) for _ in range(rng.randrange(0, 64)))
        assert bits_to_bytes(bytes_to_bits(payload)) == payload


def test_round_trip_of_every_single_byte():
    for value in range(256):
        payload = bytes([value])
        assert bits_to_bytes(bytes_to_bits(payload)) == payload


def test_round_trip_of_multibyte_utf8():
    payload = "héllo — 世界 🎲".encode("utf-8")

    assert bits_to_bytes(bytes_to_bits(payload)) == payload


# ---------------------------------------------------------------------------
# int <-> bits
# ---------------------------------------------------------------------------


def test_int_to_bits_is_msb_first():
    assert int_to_bits(178, 8) == [1, 0, 1, 1, 0, 0, 1, 0]
    assert int_to_bits(1, 4) == [0, 0, 0, 1]
    assert int_to_bits(8, 4) == [1, 0, 0, 0]


def test_int_to_bits_pads_to_the_requested_width():
    assert int_to_bits(1, 8) == [0, 0, 0, 0, 0, 0, 0, 1]
    assert len(int_to_bits(0, 12)) == 12


def test_int_to_bits_of_zero_width():
    assert int_to_bits(0, 0) == []


@pytest.mark.parametrize("value,width", [(256, 8), (2, 1), (-1, 8), (1, 0)])
def test_int_to_bits_rejects_values_that_do_not_fit(value, width):
    with pytest.raises(ValueError):
        int_to_bits(value, width)


def test_bits_to_int_of_nothing_is_zero():
    assert bits_to_int([]) == 0


@pytest.mark.parametrize("width", [1, 3, 4, 5, 6, 7, 8])
def test_int_bits_round_trip_over_every_value(width):
    """Widths 3-8 are exactly the bit counts the PVD range table produces."""
    for value in range(1 << width):
        assert bits_to_int(int_to_bits(value, width)) == value


# ---------------------------------------------------------------------------
# The 32-bit header
# ---------------------------------------------------------------------------


def test_header_is_32_bits_wide():
    assert HEADER_BITS == 32
    assert len(pack_header(0)) == 32
    assert len(pack_header(MAX_PAYLOAD_BITS)) == 32


def test_header_is_big_endian():
    """A 1 lands in the last slot, not the first. This is format-defining."""
    assert pack_header(0) == [0] * 32
    assert pack_header(1) == [0] * 31 + [1]
    assert pack_header(1 << 31) == [1] + [0] * 31
    assert pack_header(MAX_PAYLOAD_BITS) == [1] * 32


def test_header_round_trip():
    for value in (0, 1, 8, 255, 256, 65535, 1 << 20, MAX_PAYLOAD_BITS):
        assert unpack_header(pack_header(value)) == value


def test_unpack_header_ignores_bits_beyond_the_first_32():
    bits = pack_header(64) + [1] * 100

    assert unpack_header(bits) == 64


@pytest.mark.parametrize("value", [-1, MAX_PAYLOAD_BITS + 1, 1 << 40])
def test_pack_header_rejects_out_of_range_lengths(value):
    with pytest.raises(ValueError):
        pack_header(value)


@pytest.mark.parametrize("length", [0, 1, 31])
def test_unpack_header_needs_a_full_header(length):
    with pytest.raises(StreamError, match="length header"):
        unpack_header([0] * length)


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------


def test_build_stream_prepends_the_message_bit_count():
    stream = build_stream(b"A")

    assert len(stream) == HEADER_BITS + 8
    assert unpack_header(stream) == 8
    assert stream[HEADER_BITS:] == [0, 1, 0, 0, 0, 0, 0, 1]


def test_build_stream_of_an_empty_payload_is_header_only():
    """SPEC 11: an empty message file is a supported case."""
    stream = build_stream(b"")

    assert stream == [0] * 32
    assert parse_stream(stream) == b""


def test_header_counts_bits_not_bytes():
    assert unpack_header(build_stream(b"abcd")) == 32
    assert unpack_header(build_stream(b"x" * 100)) == 800


@pytest.mark.parametrize(
    "payload",
    [b"", b"\x00", b"A", b"attack at dawn", "héllo 世界".encode("utf-8"), bytes(range(256))],
)
def test_stream_round_trip(payload):
    assert parse_stream(build_stream(payload)) == payload


def test_stream_round_trip_over_random_payloads():
    rng = random.Random(4463)
    for _ in range(200):
        payload = bytes(rng.getrandbits(8) for _ in range(rng.randrange(0, 128)))
        assert parse_stream(build_stream(payload)) == payload


def test_parse_stream_discards_trailing_padding():
    """The mesh yields whole groups; everything past the declared length is noise."""
    stream = build_stream(b"hi") + [1] * 37

    assert parse_stream(stream) == b"hi"


def test_parse_stream_rejects_a_truncated_stream():
    with pytest.raises(StreamError, match="length header"):
        parse_stream([0] * 20)


def test_parse_stream_rejects_an_implausible_header():
    """SPEC 8: fail with a clear message rather than returning junk."""
    stream = pack_header(10_000) + [1] * 16

    with pytest.raises(StreamError, match="claims 10000 payload bits"):
        parse_stream(stream)


def test_parse_stream_accepts_exactly_enough_bits():
    stream = pack_header(8) + [1] * 8

    assert parse_stream(stream) == b"\xff"


def test_a_partial_declared_length_is_padded_not_rejected():
    """A header that is not a multiple of 8 must not crash the extractor."""
    stream = pack_header(3) + [1, 1, 1, 0, 0]

    assert parse_stream(stream) == b"\xe0"
