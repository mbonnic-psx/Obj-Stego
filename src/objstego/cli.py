"""Command-line entry point.

This module owns invocation, messaging, and exit codes only. It contains no
algorithm logic -- that lives in the `pvd`/`obj_io`/`bits`/`ranges` modules
(CLAUDE.md, "Layout").

Phase 0 scope: usage text and exit codes. Real argument parsing arrives in
Phase 1; until then every invocation other than `--help` reports that the
requested mode is not yet implemented and exits non-zero.
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from . import __version__

#: Success.
EXIT_OK = 0
#: Usage error -- bad invocation, missing arguments, incompatible flags.
#: Matches argparse's convention so Phase 1 can adopt argparse without a change
#: in observable behaviour. SPEC 11 requires a clean non-zero exit here.
EXIT_USAGE = 2

USAGE = """\
objstego -- hide arbitrary byte payloads in Wavefront OBJ vertex coordinates

usage:
  objstego --hide    -m <message file> -c <cover.obj> [-o <stego.obj>]
  objstego --hide    -m random         -c <cover.obj> [-o <stego.obj>]
  objstego --extract -s <stego.obj>                   [-o <message file>]

modes:
  --hide             embed a payload into a cover mesh
  --extract          recover a payload from a stego mesh (needs only the stego file)

options:
  -m <path|random>   payload to hide; the literal word "random" fills the
                     available capacity with random bytes
  -c <path>          cover mesh to embed into
  -s <path>          stego mesh to extract from
  -o <path>          output path; when hiding, defaults to <cover>_stego.obj
  -P <int>           decimal places written per coordinate (default: 6)
  -L <int>           low-order decimals used for hiding (default: 3, 1 <= L <= P)
  -h, --help         show this message and exit
  --version          print the version and exit
"""


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the command line tool and return a process exit code.

    Guarantees: never raises for a bad invocation, and never writes a traceback
    to stderr. Returns ``EXIT_OK`` on success, ``EXIT_USAGE`` on any misuse.

    ``argv`` defaults to ``sys.argv[1:]`` so tests can drive it directly.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    if not args:
        # SPEC 10: running with no arguments prints usage and exits non-zero.
        print(USAGE, file=sys.stderr, end="")
        return EXIT_USAGE

    if args[0] in ("-h", "--help"):
        print(USAGE, end="")
        return EXIT_OK

    if args[0] == "--version":
        print(f"objstego {__version__}")
        return EXIT_OK

    # Phase 0 stops here. Phase 1 replaces this branch with real parsing.
    print(USAGE, file=sys.stderr, end="")
    print(
        "\nobjstego: not implemented yet -- this build is a Phase 0 skeleton.",
        file=sys.stderr,
    )
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
