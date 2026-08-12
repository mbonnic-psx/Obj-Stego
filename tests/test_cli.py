"""CLI smoke tests: usage, help, version, and the no-traceback promise.

Detailed argument parsing and validation lives in `test_args.py`. This file
pins the ROADMAP Phase 0 exit criterion and the SPEC 11 guarantee that no
invocation, valid or not, ever produces a traceback.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from objstego import __version__
from objstego.cli import EXIT_OK, EXIT_USAGE, main

SRC = Path(__file__).resolve().parents[1] / "src"


def test_no_arguments_prints_usage_and_exits_nonzero(capsys):
    code = main([])
    captured = capsys.readouterr()

    assert code == EXIT_USAGE
    assert code != EXIT_OK
    assert "usage:" in captured.err
    # Usage errors belong on stderr so stdout stays clean for piped payloads.
    assert captured.out == ""


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_prints_usage_to_stdout_and_exits_zero(flag, capsys):
    code = main([flag])
    captured = capsys.readouterr()

    assert code == EXIT_OK
    assert "usage:" in captured.out
    assert captured.err == ""


def test_help_wins_over_an_otherwise_invalid_invocation(capsys):
    code = main(["--hide", "--extract", "--help"])
    captured = capsys.readouterr()

    assert code == EXIT_OK
    assert "usage:" in captured.out


def test_version_flag(capsys):
    code = main(["--version"])
    captured = capsys.readouterr()

    assert code == EXIT_OK
    assert __version__ in captured.out


def test_usage_text_documents_both_modes_and_the_precision_knobs(capsys):
    main(["--help"])
    out = capsys.readouterr().out

    assert "--hide" in out
    assert "--extract" in out
    assert "-P" in out
    assert "-L" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["--hide"],
        ["--extract"],
        ["--hide", "--extract"],
        ["--hide", "-m", "nope.txt", "-c", "nope.obj"],
        ["--extract", "-m", "nope.txt"],
        ["--extract", "-s", "nope.obj"],
        ["--nonsense"],
        ["cover.obj"],
        ["--hide", "-m", "random", "-c", "nope.obj", "-P", "x"],
        ["-P", "2", "-L", "9"],
    ],
)
def test_bad_invocations_exit_nonzero_without_a_traceback(argv, capsys):
    """SPEC 11: an uncaught traceback on any of these is a defect."""
    code = main(argv)
    err = capsys.readouterr().err

    assert code != EXIT_OK
    assert "Traceback" not in err
    assert err.strip(), "a failure must explain itself"


def test_module_entry_point_exits_nonzero_with_no_args():
    """The real process, not just main() -- this is the observable exit criterion."""
    env = dict(os.environ, PYTHONPATH=str(SRC))
    proc = subprocess.run(
        [sys.executable, "-m", "objstego"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode != 0
    assert "usage:" in proc.stderr
    assert "Traceback" not in proc.stderr
