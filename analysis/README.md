# Analysis harness

Measures the tool: how much it can carry, how far it moves the geometry, and how
easily it is caught.

```bash
pip install -e ".[analysis]"
python analysis/run_analysis.py
```

One command regenerates every table and figure into `analysis/out/`, which is
gitignored. Payloads come from a seeded generator rather than `os.urandom`, so
two runs are byte-identical and a diff means the tool changed, not the dice.

Flags: `--no-figures` skips matplotlib, `--no-meshes` skips writing the stego
meshes. CI uses both.

## What it produces

| Output | What it shows |
|---|---|
| `REPORT.md` | every table, with the findings written out |
| `capacity_vs_l.png` | bits per vertex against `L`, per mesh |
| `bits_per_pair.png` | how many pairs carry 3–8 bits; a flat bar chart would mean the scheme had collapsed into LSB |
| `low_digit_histogram.png` | least-significant-digit distribution, cover against a capacity-filling payload |
| `distortion_vs_fill.png` | RMS displacement against fill level, with the format's bound marked |
| `meshes/*.obj` | stego meshes at 25%, 80% and 100% fill, for the perceptibility grading |

## The three distortion columns

They are not interchangeable, and conflating them is easy:

- **max (axis)** — largest single-coordinate move. This is what SPEC §12.5
  bounds at `10**(L-P)`.
- **max (vertex)** — largest Euclidean move of a whole vertex. Up to `sqrt(3)`
  times the per-axis figure, because all three coordinates can move at once.
- **Hausdorff** — what a geometric comparison of the two point sets reports.
  Bounded above by max (vertex), and it routinely *exceeds* max (axis).

On these fixtures Hausdorff comes out exactly equal to max (vertex), which means
every displaced vertex remains nearer to its own original position than to any
other vertex — the perturbation is small relative to the mesh's vertex spacing.

## Detectability, honestly

The roadmap asked for the tool to be reported against its own detector. It does
not come out well.

Chi-square against a uniform distribution — the textbook probe — **fails to
separate cover from stego**. Uniformity is rejected for both, on every mesh and
every fill level, because natural low-order digits are nowhere near uniform to
begin with.

But the statistic *falls* as the payload grows: on `car.obj` from 1361 to 130 at
full fill, a factor of ten. Embedding pushes the distribution toward uniform
without arriving. An analyst who models what untouched meshes look like, instead
of testing against uniform, would flag these files at once — **a mesh whose
digits are too even is the anomaly.**

So the tool defeats the naive detector and loses to the informed one. Resisting
the latter would require preserving the cover's digit histogram, which the range
table does not attempt. `ROADMAP.md` lists a Yang & Ivrissimtzis steganalysis
reimplementation as a v2 candidate, which would test this properly rather than
against a chi-square baseline.

## Perceptibility

The one thing this harness cannot decide. It writes stego meshes at each fill
level to `out/meshes/` and leaves an ungraded table in the report. Open each
beside its cover and grade it: **obvious to a casual observer** / **apparent on
close inspection** / **undetectable**.

## Dependencies

numpy and matplotlib, declared in the `analysis` extra. Deliberately not scipy:
the chi-square p-value uses a regularised incomplete gamma function implemented
in `metrics.py` and checked against published critical-value tables in
`tests/test_analysis.py`, which keeps the extra small.

The core package in `src/objstego/` remains standard library only.
