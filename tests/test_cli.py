"""Phase 0 smoke tests.

These pin the ROADMAP Phase 0 exit criterion: running with no arguments prints
usage and exits non-zero. They also assert the broader SPEC 11 promise that a
bad invocation never produces a traceback.
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


def test_version_flag(capsys):
    code = main(["--version"])
    captured = capsys.readouterr()

    assert code == EXIT_OK
    assert __version__ in captured.out


def test_usage_text_documents_both_modes(capsys):
    main(["--help"])
    out = capsys.readouterr().out

    assert "--hide" in out
    assert "--extract" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["--hide"],
        ["--extract"],
        ["--hide", "-m", "secret.txt", "-c", "cover.obj"],
        ["--extract", "-m", "secret.txt"],  # incompatible combo, SPEC 11
        ["--nonsense"],
        ["cover.obj"],
    ],
)
def test_unimplemented_invocations_exit_cleanly(argv, capsys):
    """Phase 0 has no parser yet; the contract is only "no crash, non-zero"."""
    code = main(argv)
    err = capsys.readouterr().err

    assert code == EXIT_USAGE
    assert "Traceback" not in err


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
