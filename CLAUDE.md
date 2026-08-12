# CLAUDE.md

Project rules for agentic sessions in this repository. Read `SPEC.md` before writing code.

---

## What this project is

A CLI tool and small Python library that hides arbitrary byte payloads in the vertex coordinates
of Wavefront `.obj` meshes using an adaptation of Pixel-Value Differencing (PVD) to 3D
coordinates. Originated as a CS 4463 course project (Team 12).

`SPEC.md` is authoritative. If the code and the spec disagree, the spec wins — fix the code, or
amend the spec in its own commit with a stated reason. Never let them drift silently.

---

## Hard rules

- **Core is standard library only.** `src/objstego/` imports nothing outside the Python stdlib.
  Analysis and dev tooling may use third-party packages, declared as optional extras.
- **Never modify non-`v` lines.** Faces, normals, texture coords, materials, comments, blank
  lines — all pass through byte-identical.
- **Always write exactly `P` decimals** per coordinate. Precision drift silently breaks
  extraction.
- **Never parse coordinates through `float`.** Use exact decimal-string handling. See SPEC §3.
- **The boundary test must be character-for-character identical** in hide and extract. Implement
  it once, in one function, called by both. Do not inline a second copy.
- **Do not change the range table, header format, pairing order, or sign rule** without a spec
  amendment. These define the file format; changing one breaks every previously produced stego
  file.
- **No crashes.** Every failure listed in SPEC §11 exits cleanly with a readable message.

---

## Workflow

- **Work in phases.** `ROADMAP.md` defines Phase 0 through Phase 8. Do one phase per session
  unless told otherwise. Do not skip ahead.
- **The tree must run at the end of every phase.** No half-finished refactors left on `main`.
- **One commit per phase minimum.** Commit messages state what changed and why, not "updates".
- **Ask before scope expansion.** If a task seems to need a new dependency, a new module, or a
  format change, stop and ask rather than deciding unilaterally.
- **Prefer small, explainable diffs** over large generated rewrites. If a change touches more
  than ~150 lines, explain the plan first.

---

## Testing

Before any commit that touches `pvd.py`, `obj_io.py`, or `bits.py`:

```bash
pytest -q
```

Non-negotiable tests:

1. **Golden vector** — SPEC §9. Pair `(567, 890)` with payload `10110010` produces `(512, 946)`
   and round-trips to `178`.
2. **Round trip** — `extract(hide(msg, cover)) == msg`, byte-for-byte, over every fixture mesh
   and payload type (ASCII text, UTF-8 with multibyte chars, a small binary blob, empty file).
3. **Negative coordinates** — `tiny.obj` contains them. They must round-trip.
4. **Passthrough** — every non-`v` line is byte-identical between cover and stego.
5. **Displacement bound** — no coordinate moves more than `10**(L-P)` on any axis.
6. **Overflow warning** — an oversized payload warns, embeds a prefix, and exits 0.

When a bug is found, write the failing test first, then fix.

---

## Layout

```
src/objstego/
    __init__.py     public API
    obj_io.py       parse and rebuild .obj, exact decimal handling
    bits.py         bytes <-> bits, 32-bit header pack/unpack
    ranges.py       range table construction, find_range, bit width
    pvd.py          pair_usable, embed_pair, extract_pair, hide, extract
    cli.py          argument parsing, error messages, exit codes
tests/
    data/           fixture meshes and payloads
analysis/           capacity + distortion harness (may use numpy)
```

Keep the layers separated. `pvd.py` should not know what a file is; `cli.py` should contain no
algorithm logic.

---

## Style

- Type hints on public functions.
- Docstrings that say what a function guarantees, not what each line does.
- No clever one-liners in the PVD core — this code is read by people learning the algorithm.
- Comments explain *why*, especially around the boundary test and sign handling.
- Cross-reference the spec in comments where useful: `# SPEC §6`.

---

## Things that have already burned this project

- Applying Wu & Tsai's odd/even split formula incorrectly. Verify against the golden vector.
- Two different sign-handling rules coexisting in the design docs. SPEC §3 settles it —
  floor-modulo, no special-casing.
- Assuming the last range bucket wastes nothing. It does (768–999 unreachable). Known, documented,
  intentional.

---

## Attribution

The underlying design was developed with Carlos Moya and Michael Gonzalez. Keep them credited in
`README.md` and `LICENSE`/`AUTHORS`. Do not remove attribution when refactoring.

Cited works belong in `README.md` under References: Wu & Tsai (2003), Girdhar & Kumar (2019),
Li et al. (2017), Madoš et al. (2018), Yang & Ivrissimtzis (2014).
