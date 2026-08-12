# Test fixtures

Provenance and licensing for every mesh in this directory. The pre-flight
checklist in `ROADMAP.md` requires this file; keep it current when adding
fixtures.

---

## `tiny.obj`

**Source:** hand-written, transcribed from `SPEC.md` §13.
**License:** part of this repository, MIT.

Four vertices, small enough to verify by hand. Contains negative coordinates
and a trailing non-`v` line.

**Capacity: 14 bits — it cannot carry a payload at all.** Six pairs, of which
only two are usable, and 14 bits is less than the 32-bit length header. This is
a *parser* fixture, not a capacity fixture: use it for exact-decimal handling,
sign handling, and byte-identical passthrough. Hiding into it is expected to
warn and embed nothing, which is itself worth testing.

## `car.obj`

**Source:** authored by the repository owner in Blender 4.3.2. Original work, no
third-party rights.
**License:** part of this repository, MIT.

711 vertices, 2133 coordinates, exported at exactly 6 decimals — the same
precision the tool writes, so a cover/stego pair differs only where a payload
was actually embedded.

What makes it a good fixture:

| Property | Value | Why it matters |
|---|---|---|
| Non-`v` line types | `#`, `mtllib`, `o`, `vn`, `vt`, `s`, `usemtl`, `f` | 1,452 lines that must pass through byte-identical |
| Negative coordinates | 641 | exercises SPEC §3 floor-modulo sign handling |
| Coordinate count | 2133, **odd** | leaves one unpaired trailing coordinate (SPEC §5) |
| Usable pairs | 747 of 1066 (70.1%) | 319 real skip decisions for blind extraction to reproduce |
| Bits per pair | 3→25, 4→39, 5→52, 6→119, 7→226, 8→286 | genuine PVD spread, not uniform LSB |
| Capacity at L=3 | 5075 bits = 630 payload bytes | 7.14 bits per vertex |

It also contains the one cover pair `(0, 999)` whose difference falls in the top
bucket's dead zone (SPEC §2), where the offset 487 exceeds the 8 bits that range
carries. Embedding can never produce such a pair, so extraction must stop on the
length header before reaching it — which is exactly the behaviour it pins.

`Car.mtl` is referenced by the `mtllib` line but is not included. That is
harmless: the line passes through untouched like any other non-`v` line.
