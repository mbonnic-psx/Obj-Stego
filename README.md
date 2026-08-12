# Obj-Stego

[![tests](https://github.com/mbonnic-psx/Obj-Stego/actions/workflows/tests.yml/badge.svg)](https://github.com/mbonnic-psx/Obj-Stego/actions/workflows/tests.yml)

Hide arbitrary byte payloads in the vertex coordinates of Wavefront `.obj` meshes, using an
adaptation of Pixel-Value Differencing (PVD) to 3D coordinates.

> **Status: Phase 7 of 8.** Hiding and blind extraction work end to end and are covered by ~480
> tests. Remaining: the capacity and distortion analysis harness (Phase 8). See
> [`ROADMAP.md`](ROADMAP.md) for the plan and [`SPEC.md`](SPEC.md) for the authoritative format
> definition — if the code and the spec ever disagree, the spec wins.

---

## What it does

A `.obj` file is plain text, mostly a list of vertex positions:

```
v 1.234567 -0.891234 3.000010
```

The last few decimals of those numbers are visually irrelevant. Nudging a vertex by `0.000055`
changes nothing you can see, but it can carry data. Obj-Stego rewrites those low-order digits to
encode a payload and leaves everything else in the file untouched.

- **Variable capacity.** Coordinates are taken in pairs; a pair whose low digits are already far
  apart carries up to 8 bits, a pair that is close together carries 3. That is what makes this PVD
  rather than LSB substitution.
- **Blind extraction.** Recovering the payload needs only the stego file — no cover, no key.
- **Format-preserving.** Every non-`v` line passes through byte-identical.
- **No dependencies.** The core package is Python standard library only.

## Install

Not published to PyPI. From a clone:

```bash
git clone https://github.com/mbonnic-psx/Obj-Stego.git
cd Obj-Stego
pip install -e ".[dev]"
```

Requires Python 3.9 or newer.

## Usage

```
objstego --hide    -m <message file> -c <cover.obj> [-o <stego.obj>]
objstego --hide    -m random         -c <cover.obj> [-o <stego.obj>]
objstego --extract -s <stego.obj>                   [-o <message file>]
```

| Option | Meaning |
|---|---|
| `-m <path\|random>` | payload to hide; the literal word `random` fills the whole capacity with random bytes |
| `-c <path>` | cover mesh to embed into |
| `-s <path>` | stego mesh to extract from |
| `-o <path>` | output; defaults to `<cover>_stego.obj` when hiding, `<stego>_payload.bin` when extracting |
| `-P <int>` | decimal places written per coordinate (default 6) |
| `-L <int>` | low-order decimals used for hiding (default 3, must satisfy `1 <= L <= P`) |

`L` is the single knob trading capacity against distortion. Worst-case displacement per axis is
`10**(L-P)` units — `0.001` at the defaults.

### A real run

```console
$ printf 'attack at dawn' > secret.txt

$ objstego --hide -m secret.txt -c tests/data/car.obj
tests/data/car.obj -> tests/data/car_stego.obj: hid 14 of 14 bytes in 21 pairs (9 skipped)

$ objstego --extract -s tests/data/car_stego.obj -o recovered.txt
tests/data/car_stego.obj -> recovered.txt: recovered 14 bytes

$ diff secret.txt recovered.txt && echo identical
identical
```

The stego mesh is byte-identical to the cover on all 1,469 of its non-`v` lines, and no coordinate
moved by more than `0.001`. The 9 skipped pairs were reproduced by the extractor without ever
seeing the cover.

### As a library

```python
import objstego

cover = open("car.obj").read()
stego, result = objstego.hide(cover, b"attack at dawn")
print(result.complete, result.pairs_used)      # True 21

assert objstego.extract(stego) == b"attack at dawn"
print(objstego.payload_capacity(cover))        # 630
```

## How it works

**Carrier.** Each coordinate is parsed to an exact scaled integer at precision `P` — never through
`float`, whose rounding can be off by one unit in the last place and silently corrupt everything
downstream. Only `V mod 10**L` is modified.

**Pairing.** Coordinates are flattened `x, y, z, x, y, z, …` in file order and taken in
non-overlapping pairs. An odd trailing coordinate is left alone.

**Range table.** A pair's difference selects a range, and the range's width sets how many bits it
carries:

| Range | 0–7 | 8–15 | 16–31 | 32–63 | 64–127 | 128–255 | 256–511 | 512–999 |
|---|---|---|---|---|---|---|---|---|
| Bits | 3 | 3 | 4 | 5 | 6 | 7 | 8 | 8 |

**Anchoring.** Each pair is repositioned about an anchor `c = min(a,b) + ceil(m/2)`, which
embedding leaves unchanged. Because the boundary test depends only on `c` and the range, a receiver
holding just the stego file reaches exactly the skip decisions the sender did. That property is the
whole reason blind extraction works; see SPEC §6, including the amendment that established it.

**Framing.** The embedded stream is a 32-bit big-endian length header followed by the message bits,
MSB-first within each byte. The header is what tells the extractor where to stop.

## Capacity

Measured across the test fixtures at `L = 3`:

| mesh | vertices | usable pairs | distinct low digits | capacity |
|---|---|---|---|---|
| `cube.obj` | 8 | 0 / 12 (0%) | 1 | **0 bytes** |
| `suzanne.obj` | 507 | 490 / 760 (64.5%) | 16 | 403 bytes |
| `car.obj` | 711 | 747 / 1066 (70.1%) | 299 | 630 bytes |

## Limitations

**The mesh needs entropy in its low-order digits.** Organic, sculpted or scanned geometry carries a
lot; clean CAD-style or axis-aligned geometry carries nothing. Blender's default cube has capacity
**zero** — every coordinate is `±1.000000`, so every pair sits at a difference of 0 and the boundary
test rejects it. That is a property of the method, not of file size: a subdivided cube with 10,000
round coordinates would be equally empty. Hiding into such a mesh warns and writes a copy of the
cover.

**The top range bucket wastes capacity.** It spans differences 512–999, but 8 bits address only 256
of them, so differences 768–999 are never produced by embedding. Inherited from PVD's power-of-two
width requirement, and intentional — the range table defines the file format and cannot change
without breaking every previously produced stego file.

**No encryption.** The payload is unkeyed by design. Anyone who knows the method and `L` can read
it. Pair this with encryption if you need confidentiality rather than concealment.

**Precision is normalised.** Every `v` line is rewritten at exactly `P` decimals, including lines
carrying no payload. A cover written at 4 decimals produces a stego file that looks reformatted
throughout — prefer covers already at `P`.

Out of scope for v1: keyed or encrypted payloads, randomised traversal order, binary mesh formats
(STL, PLY, FBX), and per-mesh adaptive range tables.

## Development

```bash
pytest -q            # fast suite
pytest -m slow -q    # exhaustive sweep: all 10**6 pairs, ~2 minutes
```

Tests run straight from a clone — `pyproject.toml` puts `src/` on the path, so no install is
required. The slow sweep is deselected by default and runs in CI on every push.

```
src/objstego/
    __init__.py     public API: hide, extract, payload_capacity
    obj_io.py       parse and rebuild .obj, exact decimal handling
    bits.py         bytes <-> bits, 32-bit header pack/unpack
    ranges.py       range table construction, lookup, bit width
    pvd.py          anchoring, boundary test, embed/extract
    cli.py          argument parsing, messages, exit codes
tests/data/         fixture meshes (see tests/data/README.md)
tests/data/bad/     hostile inputs; none may produce a traceback
```

## Attribution

The 3D-PVD method implemented here was developed collaboratively as a CS 4463 course project
(Team 12), with **Carlos Moya** and **Michael Gonzalez**. See [`AUTHORS`](AUTHORS).

`suzanne.obj` is a Blender Foundation asset, included as a test fixture and not covered by this
repository's licence. See [`tests/data/README.md`](tests/data/README.md).

## References

- Wu, D.-C. and Tsai, W.-H. (2003). *A steganographic method for images by pixel-value
  differencing.* Pattern Recognition Letters, 24(9–10), 1613–1626.
- Girdhar, A. and Kumar, V. (2019). *A reversible and affine invariant 3D data hiding technique
  based on difference shifting and logistic map.* Journal of Ambient Intelligence and Humanized
  Computing.
- Li, N., Hu, J., Sun, R., Wang, S. and Luo, Z. (2017). *A high-capacity 3D steganography algorithm
  with adjustable distortion.* IEEE Access, 5, 24457–24466.
- Madoš, B., Ádám, N., Hurtuk, J. and Čopjak, M. (2018). *Steganographic algorithm for information
  hiding using scalable vector graphics images.* IEEE SACI.
- Yang, Y. and Ivrissimtzis, I. (2014). *Mesh discriminative features for 3D steganalysis.* ACM
  Transactions on Multimedia Computing, Communications, and Applications, 10(3).

## License

MIT — see [`LICENSE`](LICENSE).
