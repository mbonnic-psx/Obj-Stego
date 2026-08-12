"""Bit-level plumbing: bytes <-> bits, and the 32-bit length header.

Two conventions run through this module and must not be varied anywhere else
(SPEC 4):

- **MSB-first within each byte.** ``b"\\x80"`` becomes ``[1, 0, 0, 0, 0, 0, 0, 0]``.
- **Big-endian for the header.** The 32-bit length is written most significant
  bit first, so it decodes the same way an ordinary integer reads.

The embedded stream is ``[32-bit length][message bits]``, where the length
counts *message* bits -- not bytes, and not including the header itself.

Bits are plain ``list[int]`` of 0 and 1. That is not the most compact
representation available, but it matches the spec's pseudocode line for line,
and this code is read by people learning the algorithm.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

__all__ = [
    "Bits",
    "StreamError",
    "HEADER_BITS",
    "MAX_PAYLOAD_BITS",
    "bytes_to_bits",
    "bits_to_bytes",
    "int_to_bits",
    "bits_to_int",
    "pack_header",
    "unpack_header",
    "build_stream",
    "parse_stream",
]

#: A sequence of 0/1 integers, most significant bit first.
Bits = List[int]

#: Width of the length header (SPEC 4).
HEADER_BITS = 32

#: The largest message length the header can express. Not a practical limit --
#: 2**32 - 1 bits is half a gigabyte of payload.
MAX_PAYLOAD_BITS = (1 << HEADER_BITS) - 1


def _check_bit(bit: object) -> None:
    """Reject anything that is not the integer 0 or 1.

    The type check is not redundant with the value check: ``1.0 == 1`` is True,
    so a float would pass a value-only guard and then fail with a TypeError
    inside the shift. Booleans are accepted -- they are ints, and genuinely 0/1.
    """
    if not isinstance(bit, int) or (bit != 0 and bit != 1):
        raise ValueError(f"bit values must be 0 or 1, got {bit!r}")


class StreamError(Exception):
    """A recovered bit stream cannot be interpreted as a framed payload.

    Raised when fewer than 32 bits were recovered, or when the header claims
    more payload than the file actually yielded. SPEC 8 requires this to fail
    loudly rather than return junk.
    """


# ---------------------------------------------------------------------------
# bytes <-> bits
# ---------------------------------------------------------------------------


def bytes_to_bits(data: bytes) -> Bits:
    """Expand bytes to bits, most significant bit of each byte first."""
    bits: Bits = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def bits_to_bytes(bits: Iterable[int]) -> bytes:
    """Pack bits back into bytes, most significant bit first.

    A trailing partial group is right-padded with zeros to complete the final
    byte. That mirrors SPEC 7's padding rule for the last embedded group; the
    length header is what tells the extractor where the real payload ends, so
    the padding is never mistaken for data.

    Raises ValueError if any element is not 0 or 1.
    """
    out = bytearray()
    accumulator = 0
    filled = 0

    for bit in bits:
        _check_bit(bit)
        accumulator = (accumulator << 1) | bit
        filled += 1
        if filled == 8:
            out.append(accumulator)
            accumulator = 0
            filled = 0

    if filled:
        accumulator <<= 8 - filled
        out.append(accumulator)

    return bytes(out)


# ---------------------------------------------------------------------------
# int <-> bits
# ---------------------------------------------------------------------------


def int_to_bits(value: int, width: int) -> Bits:
    """Render a non-negative integer as exactly `width` bits, MSB first.

    Used by extraction to turn a pair's in-range offset back into the bits it
    carried (SPEC 8), and by the header packer.
    """
    if width < 0:
        raise ValueError("width must not be negative")
    if value < 0:
        raise ValueError(f"value must not be negative, got {value}")
    if value >= (1 << width):
        raise ValueError(f"value {value} does not fit in {width} bits")

    bits: Bits = []
    for shift in range(width - 1, -1, -1):
        bits.append((value >> shift) & 1)
    return bits


def bits_to_int(bits: Sequence[int]) -> int:
    """Read a bit sequence as a non-negative integer, MSB first.

    An empty sequence reads as 0, which is what a zero-width range would carry.
    """
    value = 0
    for bit in bits:
        _check_bit(bit)
        value = (value << 1) | bit
    return value


# ---------------------------------------------------------------------------
# The 32-bit length header
# ---------------------------------------------------------------------------


def pack_header(payload_bits: int) -> Bits:
    """Encode a message length as 32 big-endian bits (SPEC 4)."""
    if payload_bits < 0:
        raise ValueError(f"payload length must not be negative, got {payload_bits}")
    if payload_bits > MAX_PAYLOAD_BITS:
        raise ValueError(
            f"payload of {payload_bits} bits exceeds the {HEADER_BITS}-bit "
            f"header limit of {MAX_PAYLOAD_BITS}"
        )
    return int_to_bits(payload_bits, HEADER_BITS)


def unpack_header(bits: Sequence[int]) -> int:
    """Read the message length from the first 32 bits of a recovered stream."""
    if len(bits) < HEADER_BITS:
        raise StreamError(
            f"need {HEADER_BITS} bits to read the length header, got {len(bits)}"
        )
    return bits_to_int(bits[:HEADER_BITS])


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------


def build_stream(payload: bytes) -> Bits:
    """Frame a payload as ``[32-bit length][message bits]`` (SPEC 4).

    An empty payload is legal and yields a header-only stream of 32 zero bits.
    """
    message = bytes_to_bits(payload)
    if len(message) > MAX_PAYLOAD_BITS:
        raise ValueError(
            f"payload of {len(message)} bits exceeds the header limit of "
            f"{MAX_PAYLOAD_BITS}"
        )
    return pack_header(len(message)) + message


def parse_stream(bits: Sequence[int]) -> bytes:
    """Recover the payload from a framed stream, discarding any padding.

    Bits beyond the length the header declares are ignored -- they are the
    zero-padding of the final embedded group, or simply the rest of the mesh.

    Raises :class:`StreamError` if the stream is too short to hold its header,
    or if the header claims more payload than was recovered.
    """
    declared = unpack_header(bits)
    available = len(bits) - HEADER_BITS

    if declared > available:
        raise StreamError(
            f"length header claims {declared} payload bits but only {available} "
            "were recovered -- the file is truncated, or was not produced by "
            "this tool"
        )

    return bits_to_bytes(bits[HEADER_BITS : HEADER_BITS + declared])
