"""The PVD range table: how many bits a coordinate pair can carry.

This is what makes the scheme PVD rather than LSB. A pair whose low digits are
already far apart sits in a wide range and carries more bits; a pair that is
close together sits in a narrow one and is disturbed less. Capacity varies with
the mesh instead of being uniform (SPEC 2).

**The table defines the file format.** Changing a boundary, a width, or the
clipping rule changes how many bits every pair carries, and every previously
produced stego file becomes unreadable. Amend the spec first.
"""

from __future__ import annotations

import dataclasses
from typing import Tuple

__all__ = ["Range", "RangeTable", "build_ranges", "bit_width", "range_table"]

#: An inclusive difference range, ``(lower, upper)``.
Range = Tuple[int, int]

#: The table for the default L=3 (MOD=1000), quoted from SPEC 2 so the
#: generated table can be checked against the document it comes from.
SPEC_RANGES: Tuple[Range, ...] = (
    (0, 7),
    (8, 15),
    (16, 31),
    (32, 63),
    (64, 127),
    (128, 255),
    (256, 511),
    (512, 999),
)


def bit_width(lower: int, upper: int) -> int:
    """Bits carried by a pair whose difference falls in ``[lower, upper]``.

    ``t = floor(log2(upper - lower + 1))``, computed with ``int.bit_length``
    rather than ``math.log2``: the float version can land on the wrong side of
    an exact power of two, and a single wrong width desynchronises extraction
    for the rest of the file.
    """
    span = upper - lower + 1
    if span < 1:
        raise ValueError(f"empty range ({lower}, {upper})")
    return span.bit_length() - 1


def build_ranges(mod: int) -> Tuple[Range, ...]:
    """Construct the range table for a low-part domain of size `mod` (SPEC 2).

    Widths are powers of two ascending from 8, and the final range is clipped to
    ``mod - 1``. For ``mod = 1000`` this reproduces SPEC 2's table exactly.

    The clipping is why the last bucket wastes capacity: at the default L it
    spans 512-999, which is 488 wide, but only 256 offsets are addressable with
    8 bits, so differences 768-999 are never produced by embedding. That is
    inherited from PVD's power-of-two width requirement and is intentional --
    documented, not fixed.
    """
    if mod < 2:
        raise ValueError(f"mod must be at least 2, got {mod}")

    ranges = []
    lower = 0
    while lower < mod:
        # Every range after the first starts at its own width: 8-15 is 8 wide,
        # 16-31 is 16 wide, and so on. Only the first range breaks the pattern.
        width = 8 if lower == 0 else lower
        upper = min(lower + width - 1, mod - 1)
        ranges.append((lower, upper))
        lower = upper + 1

    return tuple(ranges)


@dataclasses.dataclass(frozen=True)
class RangeTable:
    """A range table bound to its domain size, with fast difference lookup.

    Built once per run and shared by hide and extract. Both directions must use
    the same table or extraction returns garbage, so `mod` travels with it
    rather than being passed separately.
    """

    mod: int
    ranges: Tuple[Range, ...]

    def find(self, difference: int) -> Range:
        """Return the range containing `difference`.

        The ranges tile ``[0, mod)`` without gaps, so exactly one matches.
        """
        if not 0 <= difference < self.mod:
            raise ValueError(
                f"difference {difference} is outside [0, {self.mod})"
            )
        for lower, upper in self.ranges:
            if difference <= upper:
                return (lower, upper)
        raise AssertionError("range table does not tile its domain")  # unreachable

    def bits_for(self, difference: int) -> int:
        """Bits carried by a pair with this difference."""
        lower, upper = self.find(difference)
        return bit_width(lower, upper)

    @property
    def capacity_bits(self) -> int:
        """Bits carried by the widest range -- the per-pair maximum."""
        return max(bit_width(lower, upper) for lower, upper in self.ranges)


def range_table(low_digits: int) -> RangeTable:
    """Build the table for `low_digits` (the parameter L of SPEC 1)."""
    if low_digits < 1:
        raise ValueError(f"L must be at least 1, got {low_digits}")
    mod = 10**low_digits
    return RangeTable(mod=mod, ranges=build_ranges(mod))
