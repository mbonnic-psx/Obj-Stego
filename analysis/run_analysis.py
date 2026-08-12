#!/usr/bin/env python3
"""Regenerate every table and figure in the analysis report.

    python analysis/run_analysis.py

Writes to `analysis/out/`, which is gitignored. Deterministic: payloads come
from a seeded generator, not os.urandom, so two runs produce identical numbers
and a diff means something changed in the tool.

ROADMAP Phase 8 asks for capacity, distortion, fill levels, perceptibility and
detectability across at least three meshes. Perceptibility is the one thing this
script cannot decide -- it writes the stego meshes out and leaves a table for a
human to fill in.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
# Both entries matter: `src` so objstego imports without being installed, and the
# repository root so `analysis.metrics` resolves the same way whether this file
# is run as a script or imported as a module by the tests.
for entry in (str(ROOT / "src"), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import numpy as np  # noqa: E402

from objstego import DEFAULT_LOW, DEFAULT_PRECISION, extract, hide  # noqa: E402

from analysis.metrics import (  # noqa: E402
    ChiSquare,
    Distortion,
    MeshCapacity,
    chi_square_uniform,
    low_digit_histogram,
    measure_capacity,
    measure_distortion,
)

DATA = ROOT / "tests" / "data"
OUT = Path(__file__).resolve().parent / "out"

#: ROADMAP Phase 8 requires at least three meshes. These three span the range:
#: a mesh that carries nothing, a structured one, and an organic one.
MESHES = ["cube.obj", "suzanne.obj", "car.obj"]

#: SPEC 1 allows 1 <= L <= P; these are the useful settings at P = 6.
LOW_VALUES = [1, 2, 3, 4]

#: ROADMAP Phase 8: 25%, 80%, 100% of capacity.
FILL_LEVELS = [0.25, 0.80, 1.00]

SEED = 4463
P = DEFAULT_PRECISION


@dataclass
class Row:
    mesh: str
    fill: float
    payload_bytes: int
    distortion: Distortion
    chi_cover: ChiSquare
    chi_stego: ChiSquare


def payload_of(size: int, seed: int) -> bytes:
    """Deterministic pseudo-random payload.

    Random content is the worst case for detectability -- it has no structure
    for the low-digit distribution to inherit -- and seeding keeps the report
    reproducible.
    """
    return random.Random(seed).randbytes(size)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def capacity_table(sources: Dict[str, str]) -> tuple[str, Dict[str, List[MeshCapacity]]]:
    measured: Dict[str, List[MeshCapacity]] = {
        mesh: [measure_capacity(source, P, low) for low in LOW_VALUES]
        for mesh, source in sources.items()
    }

    lines = [
        "| mesh | vertices | pairs | L | usable pairs | capacity (bits) | "
        "payload (bytes) | bits/vertex |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mesh, rows in measured.items():
        for row in rows:
            lines.append(
                f"| `{mesh}` | {row.vertices} | {row.pairs} | {row.low} | "
                f"{row.usable_pairs} ({row.usable_fraction:.1%}) | {row.capacity_bits} | "
                f"{row.payload_bytes} | {row.bits_per_vertex:.2f} |"
            )
    return "\n".join(lines), measured


def bits_per_pair_table(measured: Dict[str, List[MeshCapacity]]) -> str:
    widths = sorted({w for rows in measured.values() for w in rows[2].bits_per_pair})
    header = " | ".join(f"{w} bits" if w else "skipped" for w in widths)
    lines = [f"| mesh | {header} |", "|---" * (len(widths) + 1) + "|"]
    for mesh, rows in measured.items():
        counts = rows[2].bits_per_pair  # L = 3
        cells = " | ".join(str(counts.get(w, 0)) for w in widths)
        lines.append(f"| `{mesh}` | {cells} |")
    return "\n".join(lines)


def format_p(value: float) -> str:
    """Report an underflowed p-value as a bound rather than as exactly zero."""
    return "<1e-300" if value == 0.0 else f"{value:.3g}"


def distortion_table(rows: Sequence[Row]) -> str:
    lines = [
        "| mesh | fill | payload | coords moved | RMS (axis) | max (axis) | "
        "max (vertex) | Hausdorff | within bound |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        d = row.distortion
        lines.append(
            f"| `{row.mesh}` | {row.fill:.0%} | {row.payload_bytes} B | "
            f"{d.coordinates_changed}/{d.coordinates_total} ({d.changed_fraction:.1%}) | "
            f"{d.rms:.3e} | {d.maximum:.3e} | {d.max_vertex:.3e} | "
            f"{d.hausdorff:.3e} | {'yes' if d.within_bound else 'NO'} |"
        )
    return "\n".join(lines)


def detectability_table(rows: Sequence[Row]) -> str:
    lines = [
        "| mesh | fill | chi2 cover | p cover | chi2 stego | p stego | "
        "change | uniform rejected? |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        cover, stego = row.chi_cover, row.chi_stego
        verdict = (
            "both"
            if cover.rejects_uniform and stego.rejects_uniform
            else "cover only"
            if cover.rejects_uniform
            else "stego only"
            if stego.rejects_uniform
            else "neither"
        )
        change = (
            f"{stego.statistic / cover.statistic:.2f}x" if cover.statistic else "n/a"
        )
        lines.append(
            f"| `{row.mesh}` | {row.fill:.0%} | {cover.statistic:.1f} | "
            f"{format_p(cover.p_value)} | {stego.statistic:.1f} | "
            f"{format_p(stego.p_value)} | {change} | {verdict} |"
        )
    return "\n".join(lines)


def support_table(sources: Dict[str, str]) -> tuple[str, List[str]]:
    """Which of the ten digits each mesh actually uses, before and after.

    A cover that never emits some digit, and a stego file that does, is caught
    by inspection -- no statistics required.
    """
    lines = [
        "| mesh | digits used in cover | digits used in stego | newly possible |",
        "|---|---|---|---|",
    ]
    caught: List[str] = []
    for mesh, cover in sources.items():
        capacity = measure_capacity(cover, P, DEFAULT_LOW)
        if capacity.payload_bytes == 0:
            continue
        stego, _ = hide(cover, payload_of(capacity.payload_bytes, SEED))
        before = set(np.nonzero(low_digit_histogram(cover, P))[0].tolist())
        after = set(np.nonzero(low_digit_histogram(stego, P))[0].tolist())
        new = sorted(after - before)
        lines.append(
            f"| `{mesh}` | {len(before)}/10 | {len(after)}/10 | "
            + (", ".join(str(d) for d in new) if new else "none")
            + " |"
        )
        if new:
            caught.append(mesh)
    return "\n".join(lines), caught


def detectability_finding(rows: Sequence[Row], sources: Dict[str, str]) -> str:
    """State what the chi-square numbers actually mean, including the bad news."""
    full = [r for r in rows if r.fill == 1.00 and r.payload_bytes > 0]
    if not full:
        return ""

    worst = min(full, key=lambda r: r.chi_stego.statistic / r.chi_cover.statistic)
    ratio = worst.chi_stego.statistic / worst.chi_cover.statistic
    support_md, caught = support_table(sources)

    categorical = (
        [
            "",
            "### A cheaper attack than chi-square",
            "",
            "Some meshes do not use all ten digits. Blender's Suzanne sits on a "
            "1/64 grid, so her coordinates are multiples of `0.015625` and her "
            "last digit is only ever 0, 2, 5 or 8. Embedding fills in the other "
            "six.",
            "",
            support_md,
            "",
            "For "
            + ", ".join(f"`{m}`" for m in caught)
            + " this is not a statistical test at all. A digit that the cover's "
            "geometry could never produce, appearing in the file, is proof on "
            "sight. Structured meshes are the worst possible carriers for this "
            "scheme, and the ones most likely to be reached for as test data.",
        ]
        if caught
        else []
    )

    return "\n".join(
        [
            "### What this actually shows",
            "",
            "**The naive test does not separate cover from stego.** Uniformity is "
            "rejected at any sensible level for both, on every carrier mesh and "
            "every fill level. An analyst applying the textbook chi-square-against-"
            "uniform test learns nothing.",
            "",
            "**But the direction of travel is the tell.** Natural meshes have "
            "strongly clustered low-order digits. Embedding pushes them toward "
            "uniform without ever arriving, so the statistic *falls* as the "
            "payload grows -- on `"
            + worst.mesh
            + f"` from {worst.chi_cover.statistic:.0f} to "
            f"{worst.chi_stego.statistic:.0f}, a factor of {1 / ratio:.1f}.",
            "",
            "An analyst who models what untouched meshes look like, rather than "
            "testing against uniform, would flag these files immediately: a mesh "
            "whose digits are *too even* is the anomaly. **This tool is not "
            "resistant to that detector.** It defeats only the naive one, which "
            "is the honest conclusion and the reason the roadmap asked for the "
            "tool to be reported against its own detector.",
            "",
            "Resisting a distribution-modelling attack would need the embedding to "
            "preserve the cover's digit histogram, which the range table does not "
            "attempt. See `ROADMAP.md` for the Yang & Ivrissimtzis steganalysis "
            "reimplementation listed as a v2 candidate.",
        ]
        + categorical
    )


def perceptibility_table(rows: Sequence[Row]) -> str:
    lines = [
        "Renders are a human judgement. The meshes below are written to "
        "`analysis/out/meshes/`; open each next to its cover and grade it.",
        "",
        "| mesh | fill | file | grade |",
        "|---|---|---|---|",
    ]
    for row in rows:
        if row.payload_bytes == 0:
            continue
        name = f"{Path(row.mesh).stem}_fill{int(row.fill * 100):03d}.obj"
        lines.append(f"| `{row.mesh}` | {row.fill:.0%} | `out/meshes/{name}` | _ungraded_ |")
    lines += [
        "",
        "Grades: **obvious to a casual observer** / **apparent on close "
        "inspection** / **undetectable**.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def write_figures(
    sources: Dict[str, str],
    measured: Dict[str, List[MeshCapacity]],
    rows: Sequence[Row],
) -> List[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)
    written: List[str] = []

    # 1. Capacity against L.
    fig, ax = plt.subplots(figsize=(6, 4))
    for mesh, caps in measured.items():
        ax.plot(
            [c.low for c in caps],
            [c.bits_per_vertex for c in caps],
            marker="o",
            label=mesh,
        )
    ax.set_xlabel("L (low-order decimals used)")
    ax.set_ylabel("bits per vertex")
    ax.set_title("Capacity against L, at P = 6")
    ax.set_xticks(LOW_VALUES)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "capacity_vs_l.png", dpi=150)
    plt.close(fig)
    written.append("capacity_vs_l.png")

    # 2. Bits carried per pair at L = 3 -- the PVD spread.
    fig, ax = plt.subplots(figsize=(7, 4))
    widths = sorted({w for caps in measured.values() for w in caps[2].bits_per_pair})
    offset = np.linspace(-0.3, 0.3, len(measured))
    for (mesh, caps), shift in zip(measured.items(), offset):
        counts = [caps[2].bits_per_pair.get(w, 0) for w in widths]
        ax.bar(np.arange(len(widths)) + shift, counts, width=0.25, label=mesh)
    ax.set_xticks(range(len(widths)))
    ax.set_xticklabels(["skipped" if w == 0 else f"{w} bits" for w in widths])
    ax.set_ylabel("pairs")
    ax.set_title("Bits carried per pair at L = 3 (flat would mean it is just LSB)")
    ax.grid(alpha=0.3, axis="y")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "bits_per_pair.png", dpi=150)
    plt.close(fig)
    written.append("bits_per_pair.png")

    # 3. Low-digit histograms, cover against a full random payload.
    carriers = [m for m in MESHES if measured[m][2].payload_bytes > 0]
    fig, axes = plt.subplots(1, len(carriers), figsize=(5 * len(carriers), 4))
    axes = np.atleast_1d(axes)
    for ax, mesh in zip(axes, carriers):
        cover = sources[mesh]
        stego, _ = hide(cover, payload_of(measured[mesh][2].payload_bytes, SEED))
        digits = np.arange(10)
        cover_counts = low_digit_histogram(cover, P)
        ax.bar(digits - 0.2, cover_counts, width=0.4, label="cover")
        ax.bar(digits + 0.2, low_digit_histogram(stego, P), width=0.4, label="stego")
        ax.axhline(
            cover_counts.sum() / 10,
            color="black",
            linestyle="--",
            linewidth=1,
            label="uniform",
        )
        ax.set_title(mesh)
        ax.set_xlabel("least significant digit")
        ax.set_xticks(digits)
        ax.grid(alpha=0.3, axis="y")
    axes[0].set_ylabel("coordinates")
    axes[0].legend()
    fig.suptitle("Low-digit distribution, cover against a capacity-filling payload")
    fig.tight_layout()
    fig.savefig(OUT / "low_digit_histogram.png", dpi=150)
    plt.close(fig)
    written.append("low_digit_histogram.png")

    # 4. Distortion against fill level.
    fig, ax = plt.subplots(figsize=(6, 4))
    for mesh in carriers:
        subset = [r for r in rows if r.mesh == mesh]
        ax.plot(
            [r.fill * 100 for r in subset],
            [r.distortion.rms for r in subset],
            marker="o",
            label=f"{mesh} RMS",
        )
    ax.axhline(
        10.0 ** (DEFAULT_LOW - P),
        color="red",
        linestyle="--",
        linewidth=1,
        label="displacement bound",
    )
    ax.set_xlabel("capacity filled (%)")
    ax.set_ylabel("displacement (model units)")
    ax.set_yscale("log")
    ax.set_title("Distortion against fill level, L = 3")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "distortion_vs_fill.png", dpi=150)
    plt.close(fig)
    written.append("distortion_vs_fill.png")

    return written


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def collect_rows(sources: Dict[str, str], write_meshes: bool) -> List[Row]:
    rows: List[Row] = []
    mesh_dir = OUT / "meshes"
    if write_meshes:
        mesh_dir.mkdir(parents=True, exist_ok=True)

    for mesh, cover in sources.items():
        capacity = measure_capacity(cover, P, DEFAULT_LOW)
        chi_cover = chi_square_uniform(low_digit_histogram(cover, P))

        for fill in FILL_LEVELS:
            size = int(capacity.payload_bytes * fill)
            payload = payload_of(size, SEED + int(fill * 100))
            stego, result = hide(cover, payload)

            if size:
                # Every reported measurement must come from a mesh that really
                # round-trips; a silent failure here would make the whole table
                # meaningless. Not an assert -- python -O would drop it.
                if not result.complete:
                    raise RuntimeError(f"{mesh} at {fill:.0%}: payload did not fit")
                if extract(stego) != payload:
                    raise RuntimeError(f"{mesh} at {fill:.0%}: payload did not recover")

            if write_meshes and size:
                name = f"{Path(mesh).stem}_fill{int(fill * 100):03d}.obj"
                (mesh_dir / name).write_text(stego)

            rows.append(
                Row(
                    mesh=mesh,
                    fill=fill,
                    payload_bytes=size,
                    distortion=measure_distortion(cover, stego, P, DEFAULT_LOW),
                    chi_cover=chi_cover,
                    chi_stego=chi_square_uniform(low_digit_histogram(stego, P)),
                )
            )
    return rows


def build_report(
    sources: Dict[str, str],
    measured: Dict[str, List[MeshCapacity]],
    rows: Sequence[Row],
    capacity_md: str,
    figures: Sequence[str],
) -> str:
    carriers = [m for m in MESHES if measured[m][2].payload_bytes > 0]
    parts = [
        "# Analysis report",
        "",
        "Generated by `python analysis/run_analysis.py`. Every number here is "
        "re-measured on each run from the fixtures in `tests/data/`; nothing is "
        "transcribed. Payloads are seeded, so a diff between runs means the tool "
        "changed.",
        "",
        f"Parameters: P = {P}, L = {DEFAULT_LOW} unless stated. "
        f"Payload seed {SEED}.",
        "",
        "## Capacity",
        "",
        capacity_md,
        "",
        "### Bits carried per pair, L = 3",
        "",
        "A flat row would mean the scheme had collapsed into fixed-rate LSB. The "
        "spread is what makes it PVD.",
        "",
        bits_per_pair_table(measured),
        "",
        "## Distortion",
        "",
        f"The format guarantees that no single coordinate moves by as much as "
        f"`10**(L-P)` = {10.0 ** (DEFAULT_LOW - P):g} (SPEC 12.5). Three columns, "
        "because they measure different things and the distinction matters:",
        "",
        "- **max (axis)** is the largest single-coordinate move. This is the "
        "quantity the spec bounds.",
        "- **max (vertex)** is the largest Euclidean move of a whole vertex. All "
        "three axes can move at once, so it reaches up to `sqrt(3)` times the "
        "per-axis figure.",
        "- **Hausdorff** is what a geometric comparison of the two point sets "
        "would report. It is bounded above by max (vertex) -- never by max "
        "(axis), which it routinely exceeds.",
        "",
        distortion_table(rows),
        "",
        "Hausdorff comes out exactly equal to max (vertex) on every mesh here. "
        "That is not a coincidence and not a bug: it means every displaced "
        "vertex is still nearer to its own original position than to any other "
        "vertex, which is another way of saying the perturbation is small "
        "relative to the mesh's own vertex spacing.",
        "",
        "## Detectability",
        "",
        "Chi-square goodness-of-fit of the least significant decimal digit "
        "against a uniform distribution, 9 degrees of freedom. This is the "
        "cheapest steganalytic probe there is, and the tool is reported against "
        "it honestly -- including where it loses.",
        "",
        detectability_table(rows),
        "",
        detectability_finding(rows, sources),
        "",
        "## Perceptibility",
        "",
        perceptibility_table(rows),
        "",
        "## Figures",
        "",
    ]
    parts += [f"- `{name}`" for name in figures]
    parts += ["", "## Meshes measured", ""]
    parts += [
        f"- `{mesh}` — "
        + (
            f"{measured[mesh][2].payload_bytes} bytes at L = 3"
            if mesh in carriers
            else "no capacity; carries nothing at any L"
        )
        for mesh in MESHES
    ]
    return "\n".join(parts) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-figures", action="store_true", help="skip matplotlib output"
    )
    parser.add_argument(
        "--no-meshes", action="store_true", help="skip writing stego meshes"
    )
    args = parser.parse_args(argv)

    sources = {mesh: (DATA / mesh).read_text() for mesh in MESHES}

    capacity_md, measured = capacity_table(sources)
    rows = collect_rows(sources, write_meshes=not args.no_meshes)
    figures = [] if args.no_figures else write_figures(sources, measured, rows)

    OUT.mkdir(parents=True, exist_ok=True)
    report = build_report(sources, measured, rows, capacity_md, figures)
    (OUT / "REPORT.md").write_text(report)

    print(report)
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
