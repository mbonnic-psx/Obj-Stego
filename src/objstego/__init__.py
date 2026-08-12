"""objstego -- hide arbitrary byte payloads in Wavefront OBJ vertex coordinates.

The method is a 3D adaptation of Pixel-Value Differencing (Wu & Tsai, 2003):
payload bits are carried in the low-order decimal digits of vertex coordinates,
with the number of bits per coordinate pair varying by how far apart the pair
already is. See SPEC.md, which is authoritative.

This package is standard library only, by design.

The public API (`hide`, `extract`) is not implemented yet -- see ROADMAP.md.
Phase 1 establishes the package skeleton, the CLI, and argument validation.
"""

__version__ = "0.1.0"

# SPEC 1. These are the two knobs the format is parameterised by, so they live
# at package level rather than in any one module: the CLI validates them, and
# obj_io/ranges will consume them from Phase 2 onward.
#: Decimal places written per coordinate.
DEFAULT_PRECISION = 6
#: Low-order decimals used for hiding. Constraint: 1 <= L <= P.
DEFAULT_LOW = 3

__all__ = ["__version__", "DEFAULT_PRECISION", "DEFAULT_LOW"]
