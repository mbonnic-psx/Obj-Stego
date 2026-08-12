# Hostile and awkward inputs

Every file here is fed to both `--hide` and `--extract` by
`tests/test_errors.py`. The bar is SPEC §11: **an uncaught traceback on any of
these is a defect.** A clean refusal and a clean success are both acceptable
outcomes; a stack trace is not.

Two of these are not malformed at all — they are legal OBJ that is merely rare,
and they are here to prove the parser handles them rather than rejecting them.

| File | What it is | Expected |
|---|---|---|
| `empty.obj` | zero bytes | refused: no `v` lines |
| `only_whitespace.obj` | spaces, tabs, newlines | refused: no `v` lines |
| `no_vertices.obj` | faces but no vertices | refused: nowhere to hide |
| `binary_garbage.obj` | bytes 0–255, repeated | refused, no decode error escapes |
| `vertex_missing_z.obj` | a `v` line with two coordinates | parse error naming the line |
| `vertex_no_coordinates.obj` | a bare `v` | parse error naming the line |
| `vertex_non_numeric.obj` | `v 1.000000 elephant 3.000000` | parse error naming the token |
| `vertex_double_decimal.obj` | `v 1.0.0 …` | parse error naming the token |
| `vertex_nan.obj` | `nan` and `inf` | parse error — these are floats, not decimals |
| `comma_decimal.obj` | `v 1,000000 …` | parse error, not a silent mis-parse |
| `single_vertex.obj` | one vertex, three coordinates | handled: one pair, one leftover |
| `truncated_stego.obj` | a real stego mesh missing most vertices | extract refuses: header outlives payload |
| `implausible_header.obj` | every pair decodes to all-ones | extract refuses: header claims 2³²−1 bits |

## Legal but rare — these must *succeed*

| File | What it is | Expected |
|---|---|---|
| `scientific_notation.obj` | `v 1.5e-3 -2.5E2 3.000000` | parsed exactly via `Decimal` (SPEC §3) |
| `vertex_extra_tokens.obj` | per-vertex colour, and a `w` component | extras preserved byte-identically (SPEC §5) |

## Notes on two of them

**`implausible_header.obj`** is constructed rather than found. Every pair is
`(496, 503)`: a difference of 7, which is the top of range `[0, 7]`, so each
pair yields the bits `111`. Twelve pairs give 36 one-bits, so the 32-bit header
reads `0xFFFFFFFF` and claims 4,294,967,295 payload bits from a mesh holding
four. It exists to prove the extractor checks the header against what it
actually recovered instead of trusting it.

**`vertex_nan.obj`** matters because `float("nan")` and `float("inf")` both
succeed. Any implementation that reached for `float` would accept these and
produce a coordinate that cannot be written back — which is one more reason
SPEC §3 forbids that path.
