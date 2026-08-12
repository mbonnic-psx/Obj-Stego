# Obj-Stego

Steganography for Wavefront OBJ files — variable-capacity payload hiding in low-order vertex
coordinate digits via 3D-adapted PVD.

> **Status: in development (Phase 0 of 8).** The package skeleton and CLI entry point exist;
> the hide/extract algorithm does not yet. See [`ROADMAP.md`](ROADMAP.md) for the build plan and
> [`SPEC.md`](SPEC.md) for the authoritative format definition.

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

Documented in full in `SPEC.md`. The notable one: the top range bucket spans differences 512–999
but only 256 of those are addressable with 8 bits, so differences 768–999 are never produced by
embedding. This is inherited from PVD's power-of-two width requirement and is intentional — the
range table defines the file format and cannot change without breaking every previously produced
stego file.

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
