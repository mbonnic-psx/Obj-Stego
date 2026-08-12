"""Command-line entry point.

This module owns invocation, validation, messaging, and exit codes only. It
contains no algorithm logic -- that lives in the `pvd`/`obj_io`/`bits`/`ranges`
modules (CLAUDE.md, "Layout").

Phase 1 scope: full argument parsing and validation. Every bad invocation in
SPEC 11 is rejected here, with a readable message and a clean exit code, so the
algorithm modules can assume their inputs exist and are readable. The algorithm
itself is still absent -- a valid invocation parses, then reports that.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from pathlib import Path
from typing import NoReturn, Optional, Sequence

from . import DEFAULT_LOW, DEFAULT_PRECISION, __version__

#: Success.
EXIT_OK = 0
#: Runtime failure -- missing file, unreadable path, malformed mesh.
EXIT_ERROR = 1
#: Usage error -- bad flags, incompatible combinations, out-of-range -P/-L.
#: Matches argparse's convention. SPEC 11 requires a clean non-zero exit here.
EXIT_USAGE = 2

USAGE = f"""\
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
  -o <path>          output path; defaults to <cover>_stego.obj when hiding
                     and <stego>_payload.bin when extracting
  -P <int>           decimal places written per coordinate (default: {DEFAULT_PRECISION})
  -L <int>           low-order decimals used for hiding
                     (default: {DEFAULT_LOW}, must satisfy 1 <= L <= P)
  -h, --help         show this message and exit
  --version          print the version and exit
"""


class UsageError(Exception):
    """The invocation itself is wrong: bad flags, bad combination, bad -P/-L.

    Reported with the usage text, exit code ``EXIT_USAGE``.
    """


class InputError(Exception):
    """The invocation is well-formed but the filesystem disagrees with it.

    Reported on its own, without the usage text -- repeating usage for a
    missing file buries the actual problem. Exit code ``EXIT_ERROR``.
    """


@dataclasses.dataclass(frozen=True)
class Options:
    """A validated invocation.

    Guarantees, so that later phases never re-check them: ``mode`` is exactly
    ``"hide"`` or ``"extract"``; ``input_path`` names an existing readable file;
    ``output_path``'s parent directory exists and is writable; ``message_path``
    is set if and only if hiding a file (it is ``None`` for ``-m random`` and
    for extraction); and ``1 <= low <= precision``.
    """

    mode: str
    #: Cover mesh when hiding, stego mesh when extracting.
    input_path: Path
    #: Stego mesh when hiding, recovered payload when extracting.
    output_path: Path
    message_path: Optional[Path]
    use_random: bool
    precision: int
    low: int


class _Parser(argparse.ArgumentParser):
    """argparse that raises instead of terminating the process.

    argparse's default ``error()`` prints and calls ``sys.exit``. That would
    stop ``main()`` from returning its own exit code and would leak SystemExit
    into callers and tests, so redirect it into the normal error path.
    """

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def _build_parser() -> _Parser:
    # add_help=False: -h is handled in main() so the help text stays exactly the
    # hand-written USAGE above rather than argparse's generated version.
    parser = _Parser(prog="objstego", add_help=False, usage=argparse.SUPPRESS)
    parser.add_argument("--hide", action="store_true")
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("-m", dest="message", metavar="<path|random>")
    parser.add_argument("-c", dest="cover", metavar="<cover.obj>")
    parser.add_argument("-s", dest="stego", metavar="<stego.obj>")
    parser.add_argument("-o", dest="output", metavar="<path>")
    parser.add_argument("-P", dest="precision", type=int, default=DEFAULT_PRECISION)
    parser.add_argument("-L", dest="low", type=int, default=DEFAULT_LOW)
    return parser


def parse_args(argv: Sequence[str]) -> Options:
    """Parse and validate an argument vector into an :class:`Options`.

    Raises :class:`UsageError` for a malformed invocation and
    :class:`InputError` for a filesystem problem. Never calls ``sys.exit``.
    """
    namespace = _build_parser().parse_args(list(argv))

    if namespace.hide and namespace.extract:
        raise UsageError("choose one of --hide or --extract, not both")
    if not namespace.hide and not namespace.extract:
        raise UsageError("no mode given -- use --hide or --extract")

    _validate_precision(namespace.precision, namespace.low)

    if namespace.hide:
        return _hide_options(namespace)
    return _extract_options(namespace)


def _validate_precision(precision: int, low: int) -> None:
    """Enforce SPEC 1's ``1 <= L <= P``."""
    if precision < 1:
        raise UsageError(f"-P must be at least 1 (got {precision})")
    if low < 1:
        raise UsageError(f"-L must be at least 1 (got {low})")
    if low > precision:
        raise UsageError(
            f"-L must not exceed -P (got L={low}, P={precision}); "
            "SPEC 1 requires 1 <= L <= P"
        )


def _hide_options(namespace: argparse.Namespace) -> Options:
    if namespace.stego is not None:
        raise UsageError("-s is only valid with --extract; name the cover mesh with -c")
    if namespace.message is None:
        raise UsageError("--hide needs -m <message file>, or -m random")
    if namespace.cover is None:
        raise UsageError("--hide needs -c <cover.obj>")

    cover = _readable_file(namespace.cover, "cover mesh")

    # SPEC 10: "random" is a literal keyword here, not a path. A file genuinely
    # named "random" has to be given as "./random" to disambiguate.
    use_random = namespace.message == "random"
    message = None if use_random else _readable_file(namespace.message, "message file")

    output = (
        Path(namespace.output) if namespace.output is not None else _stego_name(cover)
    )
    _validate_output(output)

    return Options(
        mode="hide",
        input_path=cover,
        output_path=output,
        message_path=message,
        use_random=use_random,
        precision=namespace.precision,
        low=namespace.low,
    )


def _extract_options(namespace: argparse.Namespace) -> Options:
    if namespace.message is not None:
        raise UsageError(
            "-m is only valid with --hide; extraction is blind and recovers the "
            "payload from the stego mesh alone"
        )
    if namespace.cover is not None:
        raise UsageError("-c is only valid with --hide; name the stego mesh with -s")
    if namespace.stego is None:
        raise UsageError("--extract needs -s <stego.obj>")

    stego = _readable_file(namespace.stego, "stego mesh")

    output = (
        Path(namespace.output) if namespace.output is not None else _payload_name(stego)
    )
    _validate_output(output)

    return Options(
        mode="extract",
        input_path=stego,
        output_path=output,
        message_path=None,
        use_random=False,
        precision=namespace.precision,
        low=namespace.low,
    )


def _stego_name(cover: Path) -> Path:
    """SPEC 10 default: ``cover.obj`` -> ``cover_stego.obj``."""
    return cover.with_name(f"{cover.stem}_stego{cover.suffix}")


def _payload_name(stego: Path) -> Path:
    """Default extraction target: ``bunny_stego.obj`` -> ``bunny_stego_payload.bin``.

    The payload is arbitrary bytes, so the extension is deliberately generic.
    """
    return stego.with_name(f"{stego.stem}_payload.bin")


def _readable_file(raw: str, label: str) -> Path:
    """Return ``raw`` as a Path, or raise :class:`InputError` explaining why not.

    Catching this at the CLI boundary is what keeps SPEC 11's "no tracebacks"
    promise cheap: the algorithm never opens a file it has not been told exists.
    """
    path = Path(raw)
    if path.is_dir():
        raise InputError(f"{label} is a directory, not a file: {path}")
    if not path.exists():
        raise InputError(f"{label} not found: {path}")
    if not path.is_file():
        raise InputError(f"{label} is not a regular file: {path}")
    if not os.access(path, os.R_OK):
        raise InputError(f"{label} is not readable: {path}")
    return path


def _validate_output(path: Path) -> None:
    """Check the output is writable now, rather than after the work is done."""
    if path.is_dir():
        raise InputError(f"output path is a directory: {path}")

    parent = path.parent
    if not parent.exists():
        raise InputError(f"output directory does not exist: {parent}")
    if not parent.is_dir():
        raise InputError(f"output path's parent is not a directory: {parent}")

    if path.exists():
        if not os.access(path, os.W_OK):
            raise InputError(f"output file is not writable: {path}")
    elif not os.access(parent, os.W_OK):
        raise InputError(f"output directory is not writable: {parent}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the command line tool and return a process exit code.

    Guarantees: never raises for any invocation, and never writes a traceback.
    Returns ``EXIT_OK``, ``EXIT_USAGE`` for misuse, or ``EXIT_ERROR`` for a
    filesystem or runtime failure.

    ``argv`` defaults to ``sys.argv[1:]`` so tests can drive it directly.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    if not args:
        # SPEC 10: running with no arguments prints usage and exits non-zero.
        print(USAGE, file=sys.stderr, end="")
        return EXIT_USAGE

    # Scanned across the whole vector, not just the first slot, so that
    # `objstego --hide --help` behaves the way people expect.
    if "-h" in args or "--help" in args:
        print(USAGE, end="")
        return EXIT_OK

    if "--version" in args:
        print(f"objstego {__version__}")
        return EXIT_OK

    try:
        options = parse_args(args)
    except UsageError as exc:
        print(USAGE, file=sys.stderr, end="")
        print(f"\nobjstego: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except InputError as exc:
        # No usage dump here -- the invocation was fine, the filesystem was not.
        print(f"objstego: {exc}", file=sys.stderr)
        return EXIT_ERROR

    # Phase 1 stops here. Parsing and validation are complete; the algorithm is
    # not. Phase 5 and 6 replace this with the real hide/extract calls.
    print(
        f"objstego: --{options.mode} is not implemented yet "
        "-- this build is a Phase 1 skeleton.",
        file=sys.stderr,
    )
    return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
