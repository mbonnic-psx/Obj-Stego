# Obj-Stego

Steganography for Wavefront OBJ files — variable-capacity payload hiding in low-order vertex
coordinate digits via 3D-adapted PVD.

> **Status: in development (Phase 6 of 8).** Hiding and blind extraction both work end to end.
> Remaining: error-case hardening and CI (Phase 7), and the capacity/distortion analysis harness
> (Phase 8). See [`ROADMAP.md`](ROADMAP.md) for the build plan and [`SPEC.md`](SPEC.md) for the
> authoritative format definition.

---

## What it does

A `.obj` mesh is plain text, mostly a list of vertex positions written to a fixed number of
decimal places. The last few of those decimals are visually irrelevant — moving a vertex by
`0.000055` units changes nothing you can see, but it can carry data.

Obj-Stego hides an arbitrary byte payload in those low-order digits using an adaptation of
**Pixel-Value Differencing** (Wu & Tsai, 2003) to 3D coordinates. Coordinates are taken in pairs;
the further apart a pair already is, the more bits it carries. That variable capacity is what
distinguishes PVD from plain LSB substitution.

- **Blind extraction** — recovering the payload needs only the stego file, no cover and no key.
- **Format-preserving** — every non-`v` line passes through byte-identical.
- **Standard library only** — the core package has no dependencies.

## Install

Not yet published. From a clone:

```bash
pip install -e ".[dev]"
```

## Usage

```
objstego --hide    -m <message file> -c <cover.obj> [-o <stego.obj>]
objstego --extract -s <stego.obj>                   [-o <message file>]
```

Run `objstego --help` for the full option list.

## Development

```bash
pytest -q
```

Tests run straight from a clone — `pyproject.toml` puts `src/` on the path, so no install is
required.

## Limitations

**The mesh needs entropy in its low-order digits.** Capacity comes from coordinates whose last
few decimals vary. Organic, sculpted or scanned geometry carries a lot; clean CAD-style or
axis-aligned geometry carries nothing at all. Blender's default cube has capacity **zero** — every
coordinate is `±1.000000`, so every pair sits at a difference of 0 and is rejected by the boundary
test. That is a property of the method, not of the file size: a subdivided cube with 10,000 round
coordinates would be just as empty. Hiding into such a mesh warns and writes a copy of the cover.

Measured across the test fixtures at `L = 3`:

| mesh | vertices | usable pairs | distinct low digits | capacity |
|---|---|---|---|---|
| `cube.obj` | 8 | 0 / 12 (0%) | 1 | **0 bytes** |
| `suzanne.obj` | 507 | 490 / 760 (64.5%) | 16 | 403 bytes |
| `car.obj` | 711 | 747 / 1066 (70.1%) | 299 | 630 bytes |

**The top range bucket wastes capacity.** It spans differences 512–999, but only 256 of those are
addressable with 8 bits, so differences 768–999 are never produced by embedding. Inherited from
PVD's power-of-two width requirement, and intentional — the range table defines the file format
and cannot change without breaking every previously produced stego file.

**No encryption.** The payload is unkeyed by design; anyone who knows the method and `L` can read
it. Pair PVD with encryption if you need confidentiality rather than concealment.

Documented in full in `SPEC.md`.

Encryption, keyed embedding, randomized traversal order, and non-OBJ containers are out of scope
for v1.

## Attribution

The 3D-PVD method implemented here was developed collaboratively as a CS 4463 course project
(Team 12), with **Carlos Moya** and **Michael Gonzalez**. See [`AUTHORS`](AUTHORS).

## References

- Wu, D.-C. and Tsai, W.-H. (2003). *A steganographic method for images by pixel-value
  differencing.* Pattern Recognition Letters, 24(9–10), 1613–1626.
- Girdhar, A. and Kumar, V. (2019). *A reversible and affine invariant 3D data hiding technique
  based on difference shifting and logistic map.* Journal of Ambient Intelligence and Humanized
  Computing.
- Li, N., Hu, J., Sun, R., Wang, S. and Luo, Z. (2017). *A high-capacity 3D steganography
  algorithm with adjustable distortion.* IEEE Access, 5, 24457–24466.
- Madoš, B., Ádám, N., Hurtuk, J. and Čopjak, M. (2018). *Steganographic algorithm for
  information hiding using scalable vector graphics images.* IEEE SACI.
- Yang, Y. and Ivrissimtzis, I. (2014). *Mesh discriminative features for 3D steganalysis.* ACM
  Transactions on Multimedia Computing, Communications, and Applications, 10(3).

## License

MIT — see [`LICENSE`](LICENSE).
