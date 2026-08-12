"""Measurement functions for the capacity and distortion harness.

Unlike `src/objstego/`, this module may use third-party packages -- numpy here,
matplotlib in the driver. It measures the tool; it is not part of it.

Everything is a pure function of the meshes handed to it. Nothing here writes
files, so the driver owns all output and the numbers can be checked in isolation.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

from objstego.obj_io import parse_obj
from objstego.pvd import pair_capacity
from objstego.ranges import range_table

__all__ = [
    "MeshCapacity",
    "Distortion",
    "ChiSquare",
    "measure_capacity",
    "measure_distortion",
    "low_digit_histogram",
    "chi_square_uniform",
    "hausdorff_distance",
    "vertices_array",
]


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MeshCapacity:
    low: int
    vertices: int
    pairs: int
    usable_pairs: int
    capacity_bits: int
    payload_bytes: int
    bits_per_pair: Dict[int, int]

    @property
    def bits_per_vertex(self) -> float:
        return self.capacity_bits / self.vertices if self.vertices else 0.0

    @property
    def usable_fraction(self) -> float:
        return self.usable_pairs / self.pairs if self.pairs else 0.0


def measure_capacity(source: str, precision: int, low: int) -> MeshCapacity:
    """Capacity of `source` at a given L, plus the spread of bits across pairs.

    The spread is the interesting part: a flat distribution would mean the
    scheme had degenerated into fixed-rate LSB.
    """
    document = parse_obj(source, precision)
    table = range_table(low)
    lows = [value % table.mod for value in document.coordinates()]

    histogram: Counter = Counter()
    for index in range(0, len(lows) - 1, 2):
        histogram[pair_capacity(lows[index], lows[index + 1], table)] += 1

    pairs = sum(histogram.values())
    capacity = sum(bits * count for bits, count in histogram.items())

    return MeshCapacity(
        low=low,
        vertices=document.vertex_count,
        pairs=pairs,
        usable_pairs=pairs - histogram[0],
        capacity_bits=capacity,
        payload_bytes=max(0, (capacity - 32) // 8),
        bits_per_pair=dict(sorted(histogram.items())),
    )


# ---------------------------------------------------------------------------
# Distortion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Distortion:
    coordinates_changed: int
    coordinates_total: int
    rms: float
    #: Largest single-axis move. This is the quantity SPEC 12.5 bounds.
    maximum: float
    #: Largest Euclidean move of a whole vertex. Up to sqrt(3) times `maximum`,
    #: since all three axes may move at once.
    max_vertex: float
    mean: float
    hausdorff: float
    bound: float

    @property
    def changed_fraction(self) -> float:
        return (
            self.coordinates_changed / self.coordinates_total
            if self.coordinates_total
            else 0.0
        )

    @property
    def within_bound(self) -> bool:
        """SPEC 12.5: no coordinate moves more than 10**(L-P)."""
        return self.maximum < self.bound


def vertices_array(source: str, precision: int) -> np.ndarray:
    """Vertices as an (n, 3) float array in model units."""
    flat = parse_obj(source, precision).coordinates()
    scale = 10.0**precision
    return np.asarray(flat, dtype=np.float64).reshape(-1, 3) / scale


def measure_distortion(
    cover: str, stego: str, precision: int, low: int
) -> Distortion:
    """Per-axis displacement statistics plus the Hausdorff distance.

    Displacements are computed on exact integers and only then scaled, so the
    numbers do not inherit any float error from the measurement itself.
    """
    before = np.asarray(parse_obj(cover, precision).coordinates(), dtype=np.int64)
    after = np.asarray(parse_obj(stego, precision).coordinates(), dtype=np.int64)
    if before.shape != after.shape:
        raise ValueError("cover and stego have different coordinate counts")

    scale = 10.0**precision
    deltas = np.abs(after - before) / scale
    per_vertex = np.linalg.norm(deltas.reshape(-1, 3), axis=1) if deltas.size else deltas

    return Distortion(
        coordinates_changed=int(np.count_nonzero(deltas)),
        coordinates_total=int(deltas.size),
        rms=float(np.sqrt(np.mean(deltas**2))),
        maximum=float(deltas.max()) if deltas.size else 0.0,
        max_vertex=float(per_vertex.max()) if per_vertex.size else 0.0,
        mean=float(deltas.mean()) if deltas.size else 0.0,
        hausdorff=hausdorff_distance(
            vertices_array(cover, precision), vertices_array(stego, precision)
        ),
        bound=10.0 ** (low - precision),
    )


def hausdorff_distance(a: np.ndarray, b: np.ndarray, chunk: int = 512) -> float:
    """Symmetric Hausdorff distance between two point sets.

    Brute force, chunked to bound memory. The fixtures are hundreds of vertices,
    so an exact O(n*m) answer costs nothing and avoids a spatial-index
    dependency.

    It is bounded above by the largest Euclidean *vertex* displacement -- a moved
    vertex may land nearer some other original vertex, never further than it
    moved. It is **not** bounded by the largest single-axis displacement, which
    is the quantity SPEC 12.5 constrains: three axes can move at once, so a
    vertex travels up to sqrt(3) times as far as any one of its coordinates.
    Reporting all three keeps that distinction visible.
    """
    if a.size == 0 or b.size == 0:
        return 0.0

    def directed(source: np.ndarray, target: np.ndarray) -> float:
        worst = 0.0
        for start in range(0, len(source), chunk):
            block = source[start : start + chunk]
            distances = np.linalg.norm(block[:, None, :] - target[None, :, :], axis=2)
            worst = max(worst, float(distances.min(axis=1).max()))
        return worst

    return max(directed(a, b), directed(b, a))


# ---------------------------------------------------------------------------
# Detectability
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChiSquare:
    statistic: float
    degrees_of_freedom: int
    p_value: float
    samples: int

    @property
    def rejects_uniform(self) -> bool:
        """At the conventional 5% level."""
        return self.p_value < 0.05


def low_digit_histogram(source: str, precision: int, bins: int = 10) -> np.ndarray:
    """Distribution of the least significant decimal digit of each coordinate.

    This is the simplest steganalytic probe there is, and the one SPEC's
    references reach for first. Embedding pushes it toward uniform.
    """
    coordinates = parse_obj(source, precision).coordinates()
    digits = np.abs(np.asarray(coordinates, dtype=np.int64)) % bins
    return np.bincount(digits, minlength=bins).astype(np.int64)


def chi_square_uniform(counts: np.ndarray) -> ChiSquare:
    """Chi-square goodness-of-fit against a uniform distribution.

    The p-value uses a regularised incomplete gamma function implemented below
    rather than scipy, to keep the analysis extra to numpy and matplotlib.
    """
    counts = np.asarray(counts, dtype=np.float64)
    total = float(counts.sum())
    bins = len(counts)

    if total == 0 or bins < 2:
        return ChiSquare(0.0, max(0, bins - 1), 1.0, int(total))

    expected = total / bins
    statistic = float(((counts - expected) ** 2 / expected).sum())
    dof = bins - 1

    return ChiSquare(statistic, dof, _chi2_sf(statistic, dof), int(total))


def _chi2_sf(statistic: float, dof: int) -> float:
    """P(X > statistic) for a chi-square variable with `dof` degrees of freedom."""
    if dof <= 0:
        return 1.0
    if statistic <= 0:
        return 1.0
    return _gamma_q(dof / 2.0, statistic / 2.0)


def _gamma_q(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x).

    Series expansion below the crossover, continued fraction above it -- the
    standard split, because each converges quickly only on its own side.
    """
    if x < 0 or a <= 0:
        raise ValueError("gamma_q requires a > 0 and x >= 0")
    if x == 0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _gamma_series(a, x)
    return _gamma_continued_fraction(a, x)


def _gamma_series(a: float, x: float, iterations: int = 1000) -> float:
    """Lower regularised gamma P(a, x) by its series expansion."""
    term = 1.0 / a
    total = term
    index = a
    for _ in range(iterations):
        index += 1.0
        term *= x / index
        total += term
        if abs(term) < abs(total) * 1e-15:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_continued_fraction(a: float, x: float, iterations: int = 1000) -> float:
    """Upper regularised gamma Q(a, x) by the modified Lentz continued fraction."""
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d

    for index in range(1, iterations + 1):
        an = -index * (index - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break

    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))
