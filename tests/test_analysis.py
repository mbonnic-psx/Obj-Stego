"""Phase 8: the analysis harness.

The harness measures the tool, so its own measurements need checking -- a
chi-square implementation that is quietly wrong would produce a confident and
entirely fictional report.

Skipped when numpy is absent, since the analysis extra is optional and the core
package must stay installable without it.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="requires the [analysis] extra")

from analysis.metrics import (  # noqa: E402
    _chi2_sf,
    chi_square_uniform,
    hausdorff_distance,
    low_digit_histogram,
    measure_capacity,
    measure_distortion,
    vertices_array,
)
from analysis.run_analysis import format_p, payload_of  # noqa: E402
from objstego import DEFAULT_PRECISION, hide  # noqa: E402

DATA = Path(__file__).parent / "data"
P = DEFAULT_PRECISION


# ---------------------------------------------------------------------------
# The chi-square implementation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statistic,dof,expected",
    [
        # Critical values from a standard chi-square table: each statistic is the
        # published cut-off for its significance level at that many degrees of
        # freedom, so the survival function must return the level back.
        (2.706, 1, 0.10),
        (3.841, 1, 0.05),
        (6.635, 1, 0.01),
        (9.488, 4, 0.05),
        (13.277, 4, 0.01),
        (16.919, 9, 0.05),
        (21.666, 9, 0.01),
        (22.362, 13, 0.05),
        (27.688, 13, 0.01),
        (43.773, 30, 0.05),
    ],
)
def test_chi_square_p_values_match_published_tables(statistic, dof, expected):
    assert _chi2_sf(statistic, dof) == pytest.approx(expected, abs=5e-4)


def test_the_survival_function_is_monotonic():
    """Both branches of the incomplete gamma must agree across the crossover."""
    previous = 1.0
    for statistic in np.arange(0.5, 60.0, 0.25):
        current = _chi2_sf(float(statistic), 9)
        assert 0.0 <= current <= previous
        previous = current


def test_a_perfectly_uniform_histogram_is_not_rejected():
    counts = np.full(10, 100)

    result = chi_square_uniform(counts)

    assert result.statistic == 0.0
    assert result.p_value == 1.0
    assert not result.rejects_uniform


def test_a_wildly_skewed_histogram_is_rejected():
    counts = np.array([1000] + [0] * 9)

    result = chi_square_uniform(counts)

    assert result.degrees_of_freedom == 9
    assert result.rejects_uniform
    assert result.p_value < 1e-10


def test_chi_square_handles_an_empty_histogram():
    result = chi_square_uniform(np.zeros(10))

    assert result.p_value == 1.0
    assert result.samples == 0


def test_underflowed_p_values_are_reported_as_a_bound():
    """A p-value of exactly 0 is a float limit, not a measurement."""
    assert format_p(0.0) == "<1e-300"
    assert format_p(0.05) == "0.05"


# ---------------------------------------------------------------------------
# Hausdorff
# ---------------------------------------------------------------------------


def test_hausdorff_of_identical_point_sets_is_zero():
    points = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])

    assert hausdorff_distance(points, points) == 0.0


def test_hausdorff_is_a_known_distance():
    a = np.array([[0.0, 0.0, 0.0]])
    b = np.array([[3.0, 4.0, 0.0]])

    assert hausdorff_distance(a, b) == pytest.approx(5.0)


def test_hausdorff_is_symmetric():
    rng = np.random.default_rng(4463)
    a = rng.normal(size=(40, 3))
    b = rng.normal(size=(37, 3))

    assert hausdorff_distance(a, b) == pytest.approx(hausdorff_distance(b, a))


def test_hausdorff_chunking_does_not_change_the_answer():
    rng = np.random.default_rng(12)
    a = rng.normal(size=(300, 3))
    b = a + rng.normal(scale=0.01, size=a.shape)

    assert hausdorff_distance(a, b, chunk=7) == pytest.approx(
        hausdorff_distance(a, b, chunk=4096)
    )


# ---------------------------------------------------------------------------
# Capacity and distortion
# ---------------------------------------------------------------------------


def test_measured_capacity_matches_the_library():
    from objstego import payload_capacity

    source = (DATA / "car.obj").read_text()

    measured = measure_capacity(source, P, 3)

    assert measured.payload_bytes == payload_capacity(source)
    assert measured.capacity_bits == 5075
    assert measured.usable_pairs == 747
    assert measured.bits_per_vertex == pytest.approx(5075 / 711)


def test_capacity_rises_with_l():
    source = (DATA / "suzanne.obj").read_text()

    capacities = [measure_capacity(source, P, low).capacity_bits for low in (1, 2, 3, 4)]

    assert capacities == sorted(capacities)


def test_distortion_respects_the_spec_bound():
    """SPEC 12.5, measured rather than assumed."""
    cover = (DATA / "car.obj").read_text()
    stego, _ = hide(cover, payload_of(600, 1))

    distortion = measure_distortion(cover, stego, P, 3)

    assert distortion.within_bound
    assert distortion.maximum < 0.001
    assert distortion.coordinates_changed > 0


def test_vertex_displacement_can_exceed_the_per_axis_maximum():
    """Three axes move at once, so a vertex travels further than any coordinate.

    Getting this backwards is what made the first draft of the report claim
    Hausdorff was bounded by the per-axis figure.
    """
    cover = (DATA / "car.obj").read_text()
    stego, _ = hide(cover, payload_of(600, 2))

    distortion = measure_distortion(cover, stego, P, 3)

    assert distortion.max_vertex > distortion.maximum
    assert distortion.max_vertex <= distortion.maximum * math.sqrt(3) + 1e-12


def test_hausdorff_never_exceeds_the_vertex_displacement():
    cover = (DATA / "car.obj").read_text()
    stego, _ = hide(cover, payload_of(600, 3))

    distortion = measure_distortion(cover, stego, P, 3)

    assert distortion.hausdorff <= distortion.max_vertex + 1e-12


def test_an_unmodified_mesh_has_zero_distortion():
    source = (DATA / "cube.obj").read_text()

    distortion = measure_distortion(source, source, P, 3)

    assert distortion.coordinates_changed == 0
    assert distortion.rms == 0.0
    assert distortion.hausdorff == 0.0


def test_vertices_array_shape_and_scale():
    points = vertices_array((DATA / "car.obj").read_text(), P)

    assert points.shape == (711, 3)
    assert abs(points).max() < 10.0  # model units, not scaled integers


# ---------------------------------------------------------------------------
# Detectability direction
# ---------------------------------------------------------------------------


def test_embedding_moves_the_digit_histogram_toward_uniform():
    """The report's central claim, asserted rather than narrated."""
    cover = (DATA / "car.obj").read_text()
    stego, _ = hide(cover, payload_of(630, 4))

    before = chi_square_uniform(low_digit_histogram(cover, P))
    after = chi_square_uniform(low_digit_histogram(stego, P))

    assert after.statistic < before.statistic / 5
    # ...but never actually reaches uniform, which is why the naive test fails
    # to separate the two.
    assert before.rejects_uniform and after.rejects_uniform


def test_suzanne_is_caught_by_inspection_not_statistics():
    """The strongest finding in the report, asserted rather than described.

    Suzanne sits on a 1/64 grid, so her last digit is only ever 0, 2, 5 or 8.
    Embedding produces digits her geometry cannot; that is proof on sight, with
    no test statistic involved.
    """
    cover = (DATA / "suzanne.obj").read_text()
    stego, _ = hide(cover, payload_of(403, 5))

    before = set(np.nonzero(low_digit_histogram(cover, P))[0].tolist())
    after = set(np.nonzero(low_digit_histogram(stego, P))[0].tolist())

    assert before == {0, 2, 5, 8}
    assert after == set(range(10))
    assert sorted(after - before) == [1, 3, 4, 6, 7, 9]


def test_the_car_has_no_impossible_digits_to_betray_it():
    """The organic mesh uses all ten digits already, so the cheap attack fails."""
    cover = (DATA / "car.obj").read_text()
    stego, _ = hide(cover, payload_of(630, 6))

    before = set(np.nonzero(low_digit_histogram(cover, P))[0].tolist())
    after = set(np.nonzero(low_digit_histogram(stego, P))[0].tolist())

    assert before == set(range(10))
    assert after - before == set()


def test_low_digit_histogram_counts_every_coordinate():
    source = (DATA / "car.obj").read_text()

    counts = low_digit_histogram(source, P)

    assert len(counts) == 10
    assert counts.sum() == 2133


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_payloads_are_deterministic():
    """The report is only comparable between runs if the payloads are fixed."""
    assert payload_of(64, 7) == payload_of(64, 7)
    assert payload_of(64, 7) != payload_of(64, 8)
    assert len(payload_of(64, 7)) == 64


def test_the_harness_runs_end_to_end(tmp_path, monkeypatch):
    """The Phase 8 exit criterion: one command regenerates everything."""
    import analysis.run_analysis as harness

    monkeypatch.setattr(harness, "OUT", tmp_path / "out")

    assert harness.main(["--no-figures"]) == 0

    report = (tmp_path / "out" / "REPORT.md").read_text()
    assert "# Analysis report" in report
    assert "## Capacity" in report
    assert "## Distortion" in report
    assert "## Detectability" in report
    assert "## Perceptibility" in report
    assert (tmp_path / "out" / "meshes" / "car_fill100.obj").exists()


def test_the_harness_is_reproducible(tmp_path, monkeypatch):
    import analysis.run_analysis as harness

    reports = []
    for run in ("a", "b"):
        monkeypatch.setattr(harness, "OUT", tmp_path / run)
        harness.main(["--no-figures", "--no-meshes"])
        reports.append((tmp_path / run / "REPORT.md").read_text())

    assert reports[0] == reports[1]
