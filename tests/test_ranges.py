"""Phase 4: the PVD range table.

The table defines the file format (SPEC 2). These tests pin it against the
document literally, so a refactor that quietly shifts a boundary fails here
rather than silently orphaning every stego file ever produced.
"""

from __future__ import annotations

import pytest

from objstego.ranges import (
    SPEC_RANGES,
    RangeTable,
    bit_width,
    build_ranges,
    range_table,
)


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------


def test_generated_table_matches_the_spec_literally():
    """SPEC 2's table, generated from MOD rather than transcribed."""
    assert build_ranges(1000) == SPEC_RANGES


def test_spec_table_bit_widths():
    """SPEC 2's Bits column: 3, 3, 4, 5, 6, 7, 8, 8."""
    widths = [bit_width(lower, upper) for lower, upper in SPEC_RANGES]

    assert widths == [3, 3, 4, 5, 6, 7, 8, 8]


def test_ranges_tile_the_domain_without_gaps_or_overlaps():
    for mod in (10, 100, 1000, 10_000):
        ranges = build_ranges(mod)

        assert ranges[0][0] == 0
        assert ranges[-1][1] == mod - 1
        for (_, upper), (lower, _) in zip(ranges, ranges[1:]):
            assert lower == upper + 1


@pytest.mark.parametrize("mod", [10, 100, 1000, 10_000, 100_000])
def test_widths_are_powers_of_two_except_the_clipped_last(mod):
    ranges = build_ranges(mod)

    for lower, upper in ranges[:-1]:
        span = upper - lower + 1
        assert span & (span - 1) == 0, f"({lower}, {upper}) is not a power of two"


def test_the_last_bucket_wastes_capacity_by_design():
    """SPEC 2's known limitation: 512-999 is 488 wide, 8 bits reaches 256 of it.

    Differences 768-999 are never produced by embedding. Documented, intentional,
    and pinned here so nobody "fixes" it without amending the spec.
    """
    lower, upper = SPEC_RANGES[-1]

    assert (lower, upper) == (512, 999)
    assert upper - lower + 1 == 488
    assert bit_width(lower, upper) == 8
    assert lower + (1 << 8) - 1 == 767  # the highest difference embedding makes


@pytest.mark.parametrize("low_digits,mod", [(1, 10), (2, 100), (3, 1000), (4, 10_000)])
def test_table_is_regenerated_for_other_values_of_l(low_digits, mod):
    """SPEC 2: the table must be regenerated from MOD when L != 3."""
    table = range_table(low_digits)

    assert table.mod == mod
    assert table.ranges == build_ranges(mod)
    assert table.ranges[-1][1] == mod - 1


def test_small_domains_still_produce_a_valid_table():
    assert build_ranges(10) == ((0, 7), (8, 9))
    assert bit_width(8, 9) == 1


@pytest.mark.parametrize("mod", [0, 1, -5])
def test_build_ranges_rejects_a_degenerate_domain(mod):
    with pytest.raises(ValueError):
        build_ranges(mod)


@pytest.mark.parametrize("low_digits", [0, -1])
def test_range_table_rejects_a_non_positive_l(low_digits):
    with pytest.raises(ValueError, match="L must be at least 1"):
        range_table(low_digits)


# ---------------------------------------------------------------------------
# bit_width
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lower,upper,expected",
    [
        (0, 7, 3),
        (8, 15, 3),
        (16, 31, 4),
        (32, 63, 5),
        (64, 127, 6),
        (128, 255, 7),
        (256, 511, 8),
        (512, 999, 8),
        (0, 0, 0),
        (0, 1, 1),
        (0, 2, 1),  # floor(log2(3)) == 1
    ],
)
def test_bit_width_cases(lower, upper, expected):
    assert bit_width(lower, upper) == expected


def test_bit_width_is_exact_at_powers_of_two():
    """math.log2 can land on the wrong side of an exact power; bit_length cannot."""
    for exponent in range(1, 60):
        span = 1 << exponent
        assert bit_width(0, span - 1) == exponent
        assert bit_width(0, span) == exponent  # one wider is still floor(log2)


def test_bit_width_rejects_an_empty_range():
    with pytest.raises(ValueError, match="empty range"):
        bit_width(10, 9)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_find_covers_every_difference_in_the_domain():
    table = range_table(3)

    for difference in range(table.mod):
        lower, upper = table.find(difference)
        assert lower <= difference <= upper


def test_find_boundary_values():
    table = range_table(3)

    assert table.find(0) == (0, 7)
    assert table.find(7) == (0, 7)
    assert table.find(8) == (8, 15)
    assert table.find(255) == (128, 255)
    assert table.find(256) == (256, 511)
    assert table.find(323) == (256, 511)  # the golden vector's difference, SPEC 9
    assert table.find(511) == (256, 511)
    assert table.find(512) == (512, 999)
    assert table.find(999) == (512, 999)


def test_golden_vector_range_and_width():
    """SPEC 9: |890 - 567| = 323 lands in [256, 511], carrying 8 bits."""
    table = range_table(3)

    assert table.find(323) == (256, 511)
    assert table.bits_for(323) == 8


@pytest.mark.parametrize("difference", [-1, 1000, 5000])
def test_find_rejects_a_difference_outside_the_domain(difference):
    with pytest.raises(ValueError, match="outside"):
        range_table(3).find(difference)


def test_bits_for_matches_the_spec_column():
    table = range_table(3)

    assert [table.bits_for(d) for d in (0, 8, 16, 32, 64, 128, 256, 512)] == [
        3, 3, 4, 5, 6, 7, 8, 8
    ]


def test_capacity_bits_is_the_per_pair_maximum():
    assert range_table(3).capacity_bits == 8
    assert range_table(1).capacity_bits == 3


def test_table_is_frozen():
    table = range_table(3)

    with pytest.raises(Exception):
        table.mod = 100  # type: ignore[misc]


def test_table_can_be_constructed_directly():
    table = RangeTable(mod=1000, ranges=build_ranges(1000))

    assert table.find(323) == (256, 511)
