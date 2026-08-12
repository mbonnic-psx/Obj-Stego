# ROADMAP

Phased build plan. **Rule: the tree runs at the end of every phase.** One commit per phase
minimum. Do not skip ahead.

Each phase lists an **exit criterion** — a thing you can actually observe. If you can't observe
it, the phase isn't done.

---

## Phase 0 — Skeleton

- `pyproject.toml`, `src/objstego/__init__.py`, `cli.py` entry point
- Running with no arguments prints usage and exits non-zero
- `.gitignore`, `LICENSE`, stub `README.md`
- `pytest` runs (zero tests is fine)

**Exit:** `objstego` with no args prints usage. `pytest -q` exits 0.

---

## Phase 1 — Argument parsing

- `--hide` / `--extract` modes with `-m`, `-c`, `-s`, `-o`
- Optional `-P` / `-L` overrides with validation (`1 <= L <= P`)
- Reject incompatible combos (`--extract` with `-m`, both modes, neither mode)
- Missing/unreadable paths caught here, not deep in the algorithm
- Default output naming (`cover.obj` -> `cover_stego.obj`)

**Exit:** every bad-invocation case in SPEC §11 produces a readable message and a clean exit code.
No tracebacks.

---

## Phase 2 — OBJ read/write round trip

- Parse `v` lines into exact scaled integers (decimal-string path, not float)
- Preserve every non-`v` line byte-identical
- Preserve extra tokens on `v` lines (4th component, per-vertex color)
- Rewrite at exactly `P` decimals
- **No hiding yet**

**Exit:** loading and re-writing `tiny.obj` with no embedding produces a file whose non-`v` lines
are byte-identical and whose `v` lines are numerically identical at precision `P`. Negative
coordinates survive.

---

## Phase 3 — Bit utilities and header

- `bytes_to_bits` / `bits_to_bytes`, MSB-first
- 32-bit big-endian header pack/unpack
- Property test: `bits_to_bytes(bytes_to_bits(b)) == b` for random `b`, including empty

**Exit:** unit tests pass, including empty payload and payloads that aren't a whole number of
bytes' worth of bits.

---

## Phase 4 — Single-pair embed and extract

- `ranges.py`: table construction from `MOD`, `find_range`, bit width
- `pair_usable` — implemented once, shared by both directions
- `embed_pair`, `extract_pair`
- **Golden vector test** from SPEC §9

**Exit:** golden vector passes. Exhaustive test over all `(a, b)` in `[0, MOD)^2` for `L=3`
(1,000,000 pairs — run it once, then mark it slow) confirming that for every usable pair, every
representable value round-trips and both new values stay in range.

---

## Phase 5 — Full hide

- Flatten coordinates, walk non-overlapping pairs
- Length header + payload, partial final group right-padded
- Skip unusable pairs, consume no bits
- "Message too large" warning to stderr, exit 0
- Reassemble and write the stego OBJ

**Exit:** a short text file embeds into `tiny.obj` and a real mesh without error, and the output
still loads in a mesh viewer.

---

## Phase 6 — Full extract

- Blind extraction, stego file only
- Read header, stop at `n` bits
- Fail clearly on truncated or implausible headers

**Exit:** `extract(hide(msg, cover)) == msg` byte-for-byte on every fixture mesh, for ASCII text,
UTF-8 with multibyte characters, a small binary blob, and an empty file.

---

## Phase 7 — Polish and hardening

- `-m random` via `os.urandom`
- Every error case in SPEC §11 covered by a test
- Malformed OBJ files, meshes with zero vertices, odd coordinate counts
- `README.md`: install, usage, worked example, limitations, references, attribution
- GitHub Actions: `pytest` on push and PR

**Exit:** CI green. No input in `tests/data/bad/` produces a traceback.

---

## Phase 8 — Analysis harness

Lives in `analysis/`, may use third-party packages.

- **Capacity** — total embeddable bits and bits-per-vertex at `L = 1, 2, 3, 4`; capacity-vs-`L`
  curve
- **Distortion** — RMS vertex displacement, max displacement, Hausdorff distance cover vs stego
- **Fill levels** — 25%, 80%, 100% of capacity
- **Perceptibility** — before/after renders graded as: obvious to a casual observer / apparent on
  close inspection / undetectable
- **Detectability** — histogram of low-order digits; chi-square test against uniform. A full
  random payload flattens the natural distribution — report the tool against its own detector
- Run across **at least 3 different meshes**

**Exit:** a reproducible script that regenerates every table and figure from the fixture meshes in
one command.

---

## Pre-flight checklist (before Phase 0)

- [ ] Confirm with Carlos and Michael before publishing publicly
- [ ] Check the professor's policy on posting coursework to GitHub
- [ ] Pick a license (MIT or Apache-2.0)
- [ ] Confirm the package name is free on PyPI
- [ ] Gather 3+ test meshes with clear licenses; record each source and license in
      `tests/data/README.md`
- [ ] Hand-write `tiny.obj` (SPEC §13)

---

## v2 candidates — explicitly out of scope for v1

- Payload encryption or a keyed variant
- Seeded pseudo-random traversal order (Wu & Tsai use one; this tool deliberately does not)
- Additional containers: PLY, STL, glTF
- Adaptive range tables derived per mesh
- A reference implementation of the Yang & Ivrissimtzis steganalysis attack, to test resistance
  honestly rather than only against a chi-square baseline
