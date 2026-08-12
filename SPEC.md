# SPEC — 3D-PVD Steganography in Wavefront OBJ Files

**Status:** authoritative. If code and this document disagree, this document wins until it is
explicitly amended. Amendments get their own commit.

---

## 0. What this tool does

Hides an arbitrary byte payload inside the **vertex coordinates** of a Wavefront `.obj` mesh by
adapting **Pixel-Value Differencing (PVD)** — originally defined over grayscale pixel pairs by
Wu & Tsai (2003) — to operate on the **low-order decimal digits** of 3D coordinates.

Properties:

- **Variable capacity** per coordinate pair (this is what makes it PVD and not LSB).
- **Blind extraction** — recovering the payload requires only the stego file, never the cover.
- **Format-preserving** — every non-`v` line passes through byte-identical.

### Provenance

The method is an original synthesis, not a reimplementation of any single paper:

| Source | Contributes |
|---|---|
| Wu & Tsai (2003) | PVD itself: range table, difference-encoding, fall-off-boundary rule |
| Girdhar & Kumar (2019) | Framing 3D coordinate differences as the carrier |
| Li et al. (2017, IEEE Access) | Distortion control via low-order decimal digits |
| Madoš et al. (IEEE SACI 2018) | OBJ as a steganographic container |

No prior work proposes this specific combination. Describe it as a **novel adaptation**.

---

## 1. Parameters

| Symbol | Meaning | Default |
|---|---|---|
| `P` | decimal places written per coordinate | `6` |
| `L` | low-order decimals used for hiding | `3` |
| `MOD` | low-part domain size = `10**L` | `1000` |

Constraints: `1 <= L <= P`. `L` is the single knob trading capacity against distortion.

Worst-case per-axis displacement ≈ `10**(L-P)` units (with defaults, `0.001`).

---

## 2. Range table

```python
RANGES = [(0, 7), (8, 15), (16, 31), (32, 63),
          (64, 127), (128, 255), (256, 511), (512, 999)]
```

Bits carried by a pair whose difference falls in `(l, u)`:

```
t = floor(log2(u - l + 1))
```

| k | Range | Width | Bits |
|---|---|---|---|
| 1 | 0–7 | 8 | 3 |
| 2 | 8–15 | 8 | 3 |
| 3 | 16–31 | 16 | 4 |
| 4 | 32–63 | 32 | 5 |
| 5 | 64–127 | 64 | 6 |
| 6 | 128–255 | 128 | 7 |
| 7 | 256–511 | 256 | 8 |
| 8 | 512–999 | 488 | 8 |

**Known limitation (not a bug):** the final bucket is 488 wide but only 256 offsets are
addressable with 8 bits, so differences 768–999 are never produced by embedding. This is
inherited from the power-of-two width requirement. Document it; do not "fix" it silently —
changing the table changes the format.

The table must be **regenerated from `MOD`** when `L != 3`. Rule: powers-of-two widths
ascending from 8, with the final range clipped to `MOD - 1`.

---

## 3. Coordinate → integer carrier

For each coordinate token on a `v` line:

```
V    = the coordinate as a scaled integer at precision P
low  = V mod MOD
high = V - low
```

Only `low` is modified. Reassembly is `V_new = high + low_new`, written back at **exactly `P`
decimal places**.

### DECISION — sign handling

**Use Python's floor-modulo on the signed integer `V`. Do not special-case negatives.**

Python's `%` returns a non-negative result for a positive modulus, so `high` absorbs the sign
and round-trips correctly:

```
c = -0.891234  ->  V = -891234
low  = V % 1000        =  766
high = V - low         = -892000
low_new = 512
V_new   = -892000 + 512 = -891488  ->  "-0.891488"
```

> The M3 slide deck describes an alternative "modify the magnitude, restore the sign" approach.
> These two rules produce **different stego output**. This spec picks floor-modulo because it is
> branch-free and symmetric. Do not mix them. Unit-test negative coordinates explicitly.

### DECISION — parse decimal strings, not floats

Do **not** compute `V = round(float(token) * 10**P)`. Float round-trips can be off by one ULP on
long or large coordinates, and a single off-by-one in `low` corrupts extraction from that pair
onward.

Instead, parse the token's digits directly (sign, integer part, fractional part), pad or truncate
the fractional part to exactly `P` digits, and assemble the integer. `decimal.Decimal` is an
acceptable implementation, as is manual string handling. Either way it must be **exact**.

Scientific notation (`1.5e-3`) in a `v` line is legal OBJ but rare. Handle it via `Decimal` or
reject the file with a clear error — do not silently mis-parse it.

---

## 4. Payload framing

1. Read the message file as **raw bytes** (works for text, images, zip — anything).
2. Convert to a bit list, **MSB-first** within each byte.
3. Prepend a **32-bit big-endian length header** = the number of *message* bits (not bytes,
   not including the header itself).
4. The embedded stream is `[32-bit length][message bits]`.

Extraction reads the first 32 recovered bits to learn `n`, then takes the next `n` bits.

Max payload: `2**32 - 1` bits. Not a practical limit.

---

## 5. Traversal and pairing

- Walk `v` lines in **file order**.
- Flatten coordinates as `x, y, z, x, y, z, ...` into one stream.
- Take **non-overlapping pairs** `(0,1), (2,3), (4,5), ...`.
- If the stream length is odd, the final unpaired coordinate is left untouched.

Hide and extract **must** use identical traversal. Any divergence returns garbage.

Only the first three numeric tokens on a `v` line participate. Extra tokens (`w`, per-vertex
color) are preserved verbatim and never modified.

---

## 6. Fall-off-boundary rule

Adapted from Wu & Tsai. A pair is tested by forcing its difference to the **maximum** of its
range and checking that both values stay inside `[0, MOD)`:

```python
def pair_usable(a, b, u):
    m    = abs(b - a)
    sign = 1 if b >= a else -1
    d    = u - m
    na   = a - sign * (d // 2)
    nb   = b + sign * ((d + 1) // 2)
    return 0 <= na < MOD and 0 <= nb < MOD
```

Unusable pairs are **skipped entirely** — left unchanged, consuming zero payload bits.

**Why this is blind-recoverable:** embedding never moves a difference out of its original range,
so the stego pair lands in the same range and yields the same `pair_usable` verdict. The receiver
reproduces the skip decisions without the cover file. This property is the whole reason the
scheme works; it is the #1 source of "extract returns garbage" when broken.

---

## 7. Hide algorithm

```
function HIDE(cover_lines, message_bits):
    stream = length_header_32(len(message_bits)) + message_bits
    coords = parse_scaled_coords(cover_lines)
    lows   = [V mod MOD for V in coords]
    highs  = [V - low for V, low in zip(coords, lows)]

    bit_i = 0
    for each non-overlapping pair (j, j+1) in lows:
        a, b = lows[j], lows[j+1]
        m    = abs(b - a)
        (l, u) = find_range(m)
        t    = floor(log2(u - l + 1))

        if not pair_usable(a, b, u):
            continue                        # skip, embed nothing

        if bit_i >= len(stream):
            break                           # payload fully embedded

        take = min(t, len(stream) - bit_i)  # last group may be partial
        bval = bits_to_int(stream[bit_i : bit_i + take] padded right to t bits)
        bit_i += take

        m_new = l + bval
        sign  = +1 if b >= a else -1
        diff  = m_new - m
        lows[j]     = a - sign * floor(diff / 2)
        lows[j + 1] = b + sign * ceil(diff / 2)

    if bit_i < len(stream):
        WARN("Message too large — only part of it was hidden.")

    coords_out = [high + low for high, low in zip(highs, lows)]
    return rebuild_obj(cover_lines, coords_out)
```

**Capacity rule:** do **not** pre-check whether the payload fits. Embed as much as possible, then
warn. Exit code 0 with a warning on stderr.

**Partial final group:** when fewer than `t` bits remain, right-pad with zeros to `t` bits. The
length header tells the extractor where the real payload ends, so the padding is harmless.

`floor` / `ceil` here are over a signed value. In Python, `math.floor(diff/2)` on a negative
`diff` is not the same as `diff // 2` for the ceiling half — use integer arithmetic and test both
signs:

```python
half_floor = diff // 2 if diff >= 0 else -((-diff) // 2)
half_ceil  = diff - half_floor
```

Whichever formulation you pick, **hide and extract must agree**, and the worked example in §9
must pass.

---

## 8. Extract algorithm

```
function EXTRACT(stego_lines):
    coords = parse_scaled_coords(stego_lines)
    lows   = [V mod MOD for V in coords]

    bits = []
    for each non-overlapping pair (j, j+1) in lows:
        a, b = lows[j], lows[j+1]
        m    = abs(b - a)
        (l, u) = find_range(m)
        t    = floor(log2(u - l + 1))
        if not pair_usable(a, b, u):
            continue
        bits += int_to_bits(m - l, width = t)
        if len(bits) >= 32 and len(bits) >= 32 + read_header(bits[0:32]):
            break

    n = read_header(bits[0:32])
    return bits_to_bytes(bits[32 : 32 + n])
```

Extraction reads **only** the stego file. No cover, no side channel, no key.

Error cases: if fewer than 32 bits are recoverable, or the header claims more bits than the file
can hold, fail with a clear message rather than returning junk.

---

## 9. Golden test vector

This must pass before any commit that touches `pvd.py`.

```
Payload bits : 10110010   (= 178)
Pair         : (a, b) = (567, 890)
m            = |890 - 567| = 323
Range        = [256, 511]  ->  t = 8 bits
m_new        = 256 + 178 = 434
diff         = 434 - 323 = 111
sign         = +1  (b >= a)
a'           = 567 - floor(111/2) = 567 - 55 = 512
b'           = 890 + ceil(111/2)  = 890 + 56 = 946
Check        : 946 - 512 = 434, still inside [256, 511] and [0, 999]

At P = 6:
  1.234567 -> 1.234512   (displacement 0.000055)
  2.345890 -> 2.345946   (displacement 0.000056)

Round trip   : extract((512, 946)) -> 434 - 256 = 178 -> 10110010
```

---

## 10. CLI

```
objstego --hide    -m <message file> -c <cover.obj> [-o <stego.obj>]
objstego --hide    -m random         -c <cover.obj> [-o <stego.obj>]
objstego --extract -s <stego.obj>    [-o <message file>]
```

- `-m random` fills available capacity with `os.urandom` bytes.
- If `-o` is omitted, derive a default name (`cover.obj` -> `cover_stego.obj`).
- Optional: `-P` / `-L` to override precision and hiding budget.
- **Running with no arguments prints usage text** and exits non-zero.

---

## 11. Error handling — required, no crashes

| Condition | Behaviour |
|---|---|
| Missing / unreadable path | clear message, clean non-zero exit |
| File is not valid OBJ, or has no `v` lines | handled, no traceback |
| `v` line with 4+ tokens or per-vertex color | extra tokens preserved untouched |
| Message larger than capacity | embed what fits, warn, exit 0 |
| Empty message file | handled (header-only stream) |
| Incompatible flag combos (`--extract` with `-m`) | usage error |
| Stego file with unreadable/implausible header | clear message, no junk output |

An uncaught traceback on any of these is a defect.

---

## 12. Invariants

1. `extract(hide(msg, cover)) == msg` byte-for-byte, for every test mesh and every payload type.
2. Every non-`v` line in the output is byte-identical to the input.
3. Every `v` line in the output has exactly `P` decimals per coordinate.
4. `hide` is deterministic given the same inputs (except `-m random`).
5. No coordinate moves more than `10**(L-P)` units on any axis.
6. `hide` with an empty payload still produces a valid, loadable mesh.

Assert these in tests, not in prose.

---

## 13. Fixture: `tests/data/tiny.obj`

Small enough to verify by hand. Includes a negative coordinate and a trailing non-`v` line.

```
# tiny.obj - hand-checkable fixture
v 1.234567 -0.891234 3.000010
v 2.345890 0.500000 -1.999999
v 0.000000 0.000001 0.000123
v -5.400000 12.345678 -0.000500
f 1 2 3
```

---

## 14. Out of scope for v1

- Encryption or keying of the payload (PVD here is unkeyed by design).
- Randomized / seeded traversal order.
- Binary mesh formats (STL, PLY, FBX).
- Adaptive range tables per mesh.

Record these in `ROADMAP.md` as possible v2 items, not as gaps.
