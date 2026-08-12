"""objstego -- hide arbitrary byte payloads in Wavefront OBJ vertex coordinates.

The method is a 3D adaptation of Pixel-Value Differencing (Wu & Tsai, 2003):
payload bits are carried in the low-order decimal digits of vertex coordinates,
with the number of bits per coordinate pair varying by how far apart the pair
already is. See SPEC.md, which is authoritative.

This package is standard library only, by design.

The public API (`hide`, `extract`) is not implemented yet -- see ROADMAP.md.
Phase 0 establishes the package skeleton and the CLI entry point.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
