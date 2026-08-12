"""Phase 4: anchoring, the boundary test, and single-pair embed/extract.

ROADMAP Phase 4 exit criterion -- the SPEC 9 golden vector passes, and an
exhaustive sweep confirms that every usable pair round-trips every value it can
carry with both coordinates staying in range.

The sweep is the real test. It is what caught the defect that SPEC 6 was
amended to fix, so it is written to cover the same ground that found it: every
pair, every value, all four failure modes checked separately.
"""

from __future__ import annotations

import random

import pytest

from objstego.pvd import (
    anchor,
    embed_bits,
    embed_pair,
    extract_bits,
    extract_pair,
    pair_capacity,
    pair_usable,
)
from objstego.ranges import bit_width, range_table

TABLE = range_table(3)
MOD = TABLE.mod


# ---------------------------------------------------------------------------
# The golden vector (SPEC 9)
# ---------------------------------------------------------------------------


def test_golden_vector():
    """SPEC 9, the whole worked example. Must pass before any commit to pvd.py."""
    a, b = 567, 890
    payload_bits = [1, 0, 1, 1, 0, 0, 1, 0]  # 178

    assert abs(b - a) == 323
    assert TABLE.find(323) == (256, 511)
    assert TABLE.bits_for(323) == 8
    assert anchor(a, b) == 729

    new_a, new_b = embed_bits(a, b, payload_bits, TABLE)

    assert (new_a, new_b) == (512, 946)
    assert new_b - new_a == 434 == 256 + 178
    assert extract_pair(new_a, new_b, TABLE) == 178
    assert extract_bits(new_a, new_b, TABLE) == payload_bits


def test_golden_vector_anchor_is_unchanged():
    assert anchor(567, 890) == anchor(512, 946) == 729


def test_golden_vector_displacement_at_p6():
    """SPEC 9: 1.234567 -> 1.234512 and 2.345890 -> 2.345946."""
    from objstego.obj_io import format_coordinate

    new_a, new_b = embed_pair(567, 890, 178, TABLE)

    assert format_coordinate(1234000 + new_a, 6) == "1.234512"
    assert format_coordinate(2345000 + new_b, 6) == "2.345946"


# ---------------------------------------------------------------------------
# The anchor (SPEC 6)
# ---------------------------------------------------------------------------


def test_anchor_is_order_independent():
    for a, b in [(0, 0), (5, 9), (9, 5), (567, 890), (999, 0)]:
        assert anchor(a, b) == anchor(b, a)


def test_anchor_of_an_equal_pair_is_the_value_itself():
    for value in (0, 1, 500, 999):
        assert anchor(value, value) == value


def test_anchor_places_the_pair_exactly():
    """A pair is always (c - ceil(m/2), c + floor(m/2)) in some order."""
    for a in range(0, 1000, 37):
        for b in range(0, 1000, 41):
            centre = anchor(a, b)
            difference = abs(b - a)
            assert min(a, b) == centre - (difference + 1) // 2
            assert max(a, b) == centre + difference // 2


def test_anchor_survives_embedding():
    """The invariant the whole scheme rests on (SPEC 6)."""
    rng = random.Random(4463)
    for _ in range(2000):
        a, b = rng.randrange(MOD), rng.randrange(MOD)
        _, upper = TABLE.find(abs(b - a))
        if not pair_usable(a, b, upper, MOD):
            continue
        width = TABLE.bits_for(abs(b - a))
        value = rng.randrange(1 << width)

        new_a, new_b = embed_pair(a, b, value, TABLE)

        assert anchor(new_a, new_b) == anchor(a, b)


# ---------------------------------------------------------------------------
# The boundary test (SPEC 6)
# ---------------------------------------------------------------------------


def test_the_amendment_counterexample_is_fixed():
    """The pair that motivated the SPEC 6 amendment.

    Under the original rule (995, 996) was usable, embedding 000 produced
    (996, 996), and that pair was *not* usable -- so the extractor skipped a
    pair the embedder had written to, shifting every later bit.
    """
    a, b = 995, 996
    _, upper = TABLE.find(abs(b - a))
    assert pair_usable(a, b, upper, MOD)

    new_a, new_b = embed_pair(a, b, 0, TABLE)
    _, new_upper = TABLE.find(abs(new_b - new_a))

    assert pair_usable(new_a, new_b, new_upper, MOD), "the desync is back"
    assert extract_pair(new_a, new_b, TABLE) == 0


@pytest.mark.parametrize("a,b", [(0, 0), (999, 999), (0, 5), (996, 999), (1, 2)])
def test_pairs_anchored_too_near_a_boundary_are_rejected(a, b):
    """Expanding to the top of the range would push a coordinate out of [0, MOD)."""
    _, upper = TABLE.find(abs(b - a))

    assert not pair_usable(a, b, upper, MOD)


def test_a_pair_already_at_maximum_difference_is_usable():
    """(0, 999) needs no room: its difference is already the range maximum, so
    embedding can only pull the coordinates inward."""
    assert pair_usable(0, 999, 999, MOD)
    assert pair_usable(999, 0, 999, MOD)
    assert extract_pair(0, 999, TABLE) == 999 - 512


def test_a_central_pair_is_usable_in_every_range():
    for _, upper in TABLE.ranges:
        assert pair_usable(500, 500, upper, MOD)


def test_usability_is_order_independent():
    """(a, b) and (b, a) differ only in orientation, never in verdict."""
    rng = random.Random(12)
    for _ in range(5000):
        a, b = rng.randrange(MOD), rng.randrange(MOD)
        _, upper = TABLE.find(abs(b - a))
        assert pair_usable(a, b, upper, MOD) == pair_usable(b, a, upper, MOD)


def test_pair_capacity_is_zero_for_a_skipped_pair():
    assert pair_capacity(0, 0, TABLE) == 0
    assert pair_capacity(999, 999, TABLE) == 0
    assert pair_capacity(500, 500, TABLE) == 3
    assert pair_capacity(567, 890, TABLE) == 8
    assert pair_capacity(0, 999, TABLE) == 8


# ---------------------------------------------------------------------------
# Embed / extract
# ---------------------------------------------------------------------------


def test_embed_preserves_orientation():
    """Whichever coordinate was larger stays larger, so the sign never flips."""
    ascending = embed_pair(300, 400, 5, TABLE)
    descending = embed_pair(400, 300, 5, TABLE)

    assert ascending[0] < ascending[1]
    assert descending[0] > descending[1]
    assert ascending == descending[::-1]


def test_embed_rejects_a_value_that_does_not_fit():
    with pytest.raises(ValueError, match="does not fit"):
        embed_pair(567, 890, 256, TABLE)  # 8-bit pair, 256 needs 9


def test_embed_rejects_an_unusable_pair():
    with pytest.raises(ValueError, match="not usable"):
        embed_pair(0, 0, 0, TABLE)


def test_embed_bits_requires_the_exact_width():
    with pytest.raises(ValueError, match="carries 8 bits"):
        embed_bits(567, 890, [1, 0, 1], TABLE)


def test_extract_of_an_untouched_pair_reads_its_offset():
    """Extraction is pure measurement -- it has no idea whether a pair was used."""
    assert extract_pair(500, 500, TABLE) == 0
    assert extract_pair(500, 507, TABLE) == 7
    assert extract_pair(567, 890, TABLE) == 323 - 256


def test_round_trip_over_random_pairs():
    rng = random.Random(20260812)
    checked = 0
    for _ in range(20_000):
        a, b = rng.randrange(MOD), rng.randrange(MOD)
        lower, upper = TABLE.find(abs(b - a))
        if not pair_usable(a, b, upper, MOD):
            continue
        width = bit_width(lower, upper)
        value = rng.randrange(1 << width)

        new_a, new_b = embed_pair(a, b, value, TABLE)

        assert 0 <= new_a < MOD and 0 <= new_b < MOD
        assert TABLE.find(abs(new_b - new_a)) == (lower, upper)
        assert pair_usable(new_a, new_b, upper, MOD)
        assert extract_pair(new_a, new_b, TABLE) == value
        checked += 1

    assert checked > 10_000, "the sample should be mostly usable pairs"


# ---------------------------------------------------------------------------
# Exhaustive sweeps (SPEC 12.7)
# ---------------------------------------------------------------------------


def _sweep(low_digits: int) -> int:
    """Check every pair against every value it can carry. Returns the count.

    The four failure modes are checked separately because they fail for
    different reasons: leaving the domain is an arithmetic bug, a changed range
    breaks the width lookup, a changed usability verdict desynchronises the
    extractor, and a wrong value means the split is not invertible.
    """
    table = range_table(low_digits)
    mod = table.mod
    lookup = [table.find(difference) for difference in range(mod)]
    widths = [bit_width(lower, upper) for lower, upper in lookup]

    combinations = 0
    for a in range(mod):
        for b in range(mod):
            difference = abs(b - a)
            lower, upper = lookup[difference]
            if not pair_usable(a, b, upper, mod):
                continue
            for value in range(1 << widths[difference]):
                new_a, new_b = embed_pair(a, b, value, table)
                new_difference = abs(new_b - new_a)

                assert 0 <= new_a < mod and 0 <= new_b < mod, (a, b, value)
                assert lookup[new_difference] == (lower, upper), (a, b, value)
                assert pair_usable(new_a, new_b, upper, mod), (a, b, value)
                assert new_difference - lower == value, (a, b, value)
                combinations += 1
    return combinations


@pytest.mark.parametrize("low_digits", [1, 2])
def test_exhaustive_sweep_at_small_l(low_digits):
    """Complete coverage at L=1 and L=2, cheap enough to run every time."""
    assert _sweep(low_digits) > 0


@pytest.mark.slow
def test_exhaustive_sweep_at_l3():
    """ROADMAP Phase 4: all 10**6 pairs at L=3, every value each can carry.

    ~98.5 million checks. Deselected by default; run with `pytest -m slow`.
    """
    assert _sweep(3) == 98_568_184


@pytest.mark.slow
def test_usable_pair_count_at_l3_is_unchanged_by_the_amendment():
    """675,439 -- identical to the pre-amendment rule. The fix cost no capacity."""
    usable = sum(
        1
        for a in range(MOD)
        for b in range(MOD)
        if pair_usable(a, b, TABLE.find(abs(b - a))[1], MOD)
    )

    assert usable == 675_439
