"""objstego -- hide arbitrary byte payloads in Wavefront OBJ vertex coordinates.

The method is a 3D adaptation of Pixel-Value Differencing (Wu & Tsai, 2003):
payload bits are carried in the low-order decimal digits of vertex coordinates,
with the number of bits per coordinate pair varying by how far apart the pair
already is. See SPEC.md, which is authoritative.

This package is standard library only, by design.

Public API: :func:`hide` embeds a payload in OBJ source text, :func:`extract`
recovers one from the stego text alone, and :func:`payload_capacity` reports
how much a mesh can hold.
"""

from __future__ import annotations

from typing import Tuple

__version__ = "0.1.0"

# SPEC 1. These are the two knobs the format is parameterised by, so they live
# at package level rather than in any one module: the CLI validates them, and
# obj_io/ranges consume them.
#: Decimal places written per coordinate.
DEFAULT_PRECISION = 6
#: Low-order decimals used for hiding. Constraint: 1 <= L <= P.
DEFAULT_LOW = 3

from . import pvd  # noqa: E402  (after the constants it does not depend on)
from .bits import HEADER_BITS  # noqa: E402
from .obj_io import parse_obj, render_obj  # noqa: E402
from .pvd import HideResult  # noqa: E402
from .ranges import range_table  # noqa: E402

__all__ = [
    "__version__",
    "DEFAULT_PRECISION",
    "DEFAULT_LOW",
    "HideResult",
    "hide",
    "extract",
    "payload_capacity",
]


def _check_parameters(precision: int, low: int) -> None:
    """Enforce SPEC 1's ``1 <= L <= P`` for callers that bypass the CLI."""
    if precision < 1:
        raise ValueError(f"precision must be at least 1, got {precision}")
    if low < 1:
        raise ValueError(f"low must be at least 1, got {low}")
    if low > precision:
        raise ValueError(f"low must not exceed precision (got L={low}, P={precision})")


def hide(
    cover: str,
    payload: bytes,
    *,
    precision: int = DEFAULT_PRECISION,
    low: int = DEFAULT_LOW,
) -> Tuple[str, HideResult]:
    """Embed `payload` in the vertex coordinates of OBJ source `cover`.

    Returns the stego OBJ text and a :class:`HideResult` describing what
    happened. If the payload was too large, the result's ``complete`` is False
    and the text holds as much of it as fit -- SPEC 7 requires embedding what
    fits rather than refusing outright.

    Every non-`v` line of `cover` is reproduced byte-identically, and every
    coordinate is written with exactly `precision` decimals.
    """
    _check_parameters(precision, low)
    document = parse_obj(cover, precision)
    result = pvd.hide(document.coordinates(), payload, range_table(low))
    return render_obj(document, result.coordinates), result


def extract(
    stego: str,
    *,
    precision: int = DEFAULT_PRECISION,
    low: int = DEFAULT_LOW,
) -> bytes:
    """Recover the payload hidden in the OBJ source `stego`.

    Blind: the cover mesh is never needed. `precision` and `low` must match
    those used to hide, since they define the carrier and the range table.

    Raises :class:`objstego.bits.StreamError` if `stego` carries no recoverable
    payload -- because it was never written by this tool, was truncated, or is
    being read with the wrong parameters.
    """
    _check_parameters(precision, low)
    document = parse_obj(stego, precision)
    return pvd.extract(document.coordinates(), range_table(low))


def payload_capacity(
    cover: str,
    *,
    precision: int = DEFAULT_PRECISION,
    low: int = DEFAULT_LOW,
) -> int:
    """Largest payload, in whole bytes, that `cover` can carry.

    The 32-bit length header is deducted, and the remainder is rounded down --
    a payload is always a whole number of bytes.
    """
    _check_parameters(precision, low)
    document = parse_obj(cover, precision)
    total = pvd.capacity_bits(document.coordinates(), range_table(low))
    return max(0, (total - HEADER_BITS) // 8)
