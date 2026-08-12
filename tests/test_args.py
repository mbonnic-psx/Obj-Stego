"""Phase 1: argument parsing and validation.

ROADMAP Phase 1 exit criterion -- every bad-invocation case in SPEC 11 produces
a readable message and a clean exit code. These tests drive `parse_args`
directly for the specifics and `main` for the exit codes those map to.
"""

from __future__ import annotations

import os

import pytest

from objstego import DEFAULT_LOW, DEFAULT_PRECISION
from objstego.cli import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    InputError,
    UsageError,
    main,
    parse_args,
)


@pytest.fixture
def cover(tmp_path):
    path = tmp_path / "cover.obj"
    path.write_text("v 1.000000 2.000000 3.000000\nf 1 1 1\n")
    return path


@pytest.fixture
def secret(tmp_path):
    path = tmp_path / "secret.txt"
    path.write_text("attack at dawn")
    return path


# --------------------------------------------------------------------------
# Mode selection
# --------------------------------------------------------------------------


def test_both_modes_is_a_usage_error():
    with pytest.raises(UsageError, match="not both"):
        parse_args(["--hide", "--extract"])


def test_no_mode_is_a_usage_error():
    with pytest.raises(UsageError, match="no mode given"):
        parse_args(["-c", "cover.obj"])


def test_unknown_flag_is_a_usage_error():
    with pytest.raises(UsageError):
        parse_args(["--encrypt"])


def test_stray_positional_is_a_usage_error():
    with pytest.raises(UsageError):
        parse_args(["cover.obj"])


# --------------------------------------------------------------------------
# -P / -L validation (SPEC 1: 1 <= L <= P)
# --------------------------------------------------------------------------


def test_precision_defaults_match_the_spec(cover, secret):
    options = parse_args(["--hide", "-m", str(secret), "-c", str(cover)])

    assert options.precision == DEFAULT_PRECISION == 6
    assert options.low == DEFAULT_LOW == 3


def test_low_may_equal_precision(cover, secret):
    options = parse_args(
        ["--hide", "-m", str(secret), "-c", str(cover), "-P", "4", "-L", "4"]
    )

    assert (options.precision, options.low) == (4, 4)


def test_low_greater_than_precision_is_rejected():
    with pytest.raises(UsageError, match="1 <= L <= P"):
        parse_args(["--extract", "-s", "stego.obj", "-P", "3", "-L", "4"])


@pytest.mark.parametrize("flag,value", [("-P", "0"), ("-L", "0"), ("-L", "-1")])
def test_non_positive_precision_values_are_rejected(flag, value):
    with pytest.raises(UsageError, match="at least 1"):
        parse_args(["--extract", "-s", "stego.obj", flag, value])


def test_non_integer_precision_is_rejected():
    with pytest.raises(UsageError):
        parse_args(["--extract", "-s", "stego.obj", "-P", "six"])


def test_precision_is_validated_before_paths_are_touched():
    """A bad -L should not be masked by a missing file, or vice versa."""
    with pytest.raises(UsageError):
        parse_args(["--hide", "-m", "nope.txt", "-c", "nope.obj", "-L", "99"])


# --------------------------------------------------------------------------
# --hide
# --------------------------------------------------------------------------


def test_hide_produces_validated_options(cover, secret):
    options = parse_args(["--hide", "-m", str(secret), "-c", str(cover)])

    assert options.mode == "hide"
    assert options.input_path == cover
    assert options.message_path == secret
    assert options.use_random is False


def test_hide_default_output_name(cover, secret):
    """SPEC 10: cover.obj -> cover_stego.obj."""
    options = parse_args(["--hide", "-m", str(secret), "-c", str(cover)])

    assert options.output_path == cover.parent / "cover_stego.obj"


def test_hide_default_output_name_without_a_suffix(tmp_path, secret):
    cover = tmp_path / "mesh"
    cover.write_text("v 0.000000 0.000000 0.000000\n")

    options = parse_args(["--hide", "-m", str(secret), "-c", str(cover)])

    assert options.output_path == tmp_path / "mesh_stego"


def test_hide_explicit_output_is_honoured(tmp_path, cover, secret):
    target = tmp_path / "elsewhere.obj"

    options = parse_args(
        ["--hide", "-m", str(secret), "-c", str(cover), "-o", str(target)]
    )

    assert options.output_path == target


def test_hide_random_keyword_needs_no_message_file(cover):
    options = parse_args(["--hide", "-m", "random", "-c", str(cover)])

    assert options.use_random is True
    assert options.message_path is None


def test_random_is_a_keyword_even_when_a_file_of_that_name_exists(
    tmp_path, cover, monkeypatch
):
    """SPEC 10 makes "random" a literal; ./random disambiguates a real file."""
    decoy = tmp_path / "random"
    decoy.write_text("not the keyword")
    monkeypatch.chdir(tmp_path)

    options = parse_args(["--hide", "-m", "random", "-c", str(cover)])

    assert options.use_random is True
    assert options.message_path is None


def test_hide_rejects_the_stego_flag(cover, secret):
    with pytest.raises(UsageError, match="only valid with --extract"):
        parse_args(["--hide", "-m", str(secret), "-c", str(cover), "-s", "x.obj"])


def test_hide_without_message_is_a_usage_error(cover):
    with pytest.raises(UsageError, match="-m"):
        parse_args(["--hide", "-c", str(cover)])


def test_hide_without_cover_is_a_usage_error(secret):
    with pytest.raises(UsageError, match="-c"):
        parse_args(["--hide", "-m", str(secret)])


def test_missing_cover_is_an_input_error(secret):
    with pytest.raises(InputError, match="cover mesh not found"):
        parse_args(["--hide", "-m", str(secret), "-c", "no_such_mesh.obj"])


def test_missing_message_is_an_input_error(cover):
    with pytest.raises(InputError, match="message file not found"):
        parse_args(["--hide", "-m", "no_such_message.txt", "-c", str(cover)])


def test_directory_as_cover_is_an_input_error(tmp_path, secret):
    with pytest.raises(InputError, match="is a directory"):
        parse_args(["--hide", "-m", str(secret), "-c", str(tmp_path)])


def test_empty_message_file_is_accepted(tmp_path, cover):
    """SPEC 11: an empty payload is a supported case, not an error."""
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")

    options = parse_args(["--hide", "-m", str(empty), "-c", str(cover)])

    assert options.message_path == empty


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_cover_is_an_input_error(tmp_path, cover, secret):
    cover.chmod(0o000)
    try:
        with pytest.raises(InputError, match="not readable"):
            parse_args(["--hide", "-m", str(secret), "-c", str(cover)])
    finally:
        cover.chmod(0o644)


def test_output_in_a_missing_directory_is_an_input_error(tmp_path, cover, secret):
    target = tmp_path / "does_not_exist" / "out.obj"

    with pytest.raises(InputError, match="output directory does not exist"):
        parse_args(
            ["--hide", "-m", str(secret), "-c", str(cover), "-o", str(target)]
        )


def test_output_onto_a_directory_is_an_input_error(tmp_path, cover, secret):
    with pytest.raises(InputError, match="output path is a directory"):
        parse_args(
            ["--hide", "-m", str(secret), "-c", str(cover), "-o", str(tmp_path)]
        )


# --------------------------------------------------------------------------
# --extract
# --------------------------------------------------------------------------


def test_extract_produces_validated_options(cover):
    options = parse_args(["--extract", "-s", str(cover)])

    assert options.mode == "extract"
    assert options.input_path == cover
    assert options.message_path is None
    assert options.use_random is False


def test_extract_default_output_name(tmp_path):
    stego = tmp_path / "bunny_stego.obj"
    stego.write_text("v 0.000000 0.000000 0.000000\n")

    options = parse_args(["--extract", "-s", str(stego)])

    assert options.output_path == tmp_path / "bunny_stego_payload.bin"


def test_extract_explicit_output_is_honoured(tmp_path, cover):
    target = tmp_path / "recovered.txt"

    options = parse_args(["--extract", "-s", str(cover), "-o", str(target)])

    assert options.output_path == target


def test_extract_rejects_the_message_flag(cover):
    """SPEC 11 lists --extract with -m as an incompatible combination."""
    with pytest.raises(UsageError, match="only valid with --hide"):
        parse_args(["--extract", "-s", str(cover), "-m", "secret.txt"])


def test_extract_rejects_the_cover_flag(cover):
    with pytest.raises(UsageError, match="only valid with --hide"):
        parse_args(["--extract", "-s", str(cover), "-c", str(cover)])


def test_extract_without_stego_is_a_usage_error():
    with pytest.raises(UsageError, match="-s"):
        parse_args(["--extract"])


def test_missing_stego_is_an_input_error():
    with pytest.raises(InputError, match="stego mesh not found"):
        parse_args(["--extract", "-s", "no_such_stego.obj"])


# --------------------------------------------------------------------------
# Exit codes and messages
# --------------------------------------------------------------------------


def test_usage_errors_exit_2_and_show_usage(capsys):
    code = main(["--hide", "--extract"])
    err = capsys.readouterr().err

    assert code == EXIT_USAGE
    assert "usage:" in err
    assert "not both" in err


def test_input_errors_exit_1_without_dumping_usage(capsys):
    code = main(["--extract", "-s", "no_such_stego.obj"])
    err = capsys.readouterr().err

    assert code == EXIT_ERROR
    assert "stego mesh not found" in err
    # Repeating the whole usage block would bury the actual problem.
    assert "usage:" not in err


def test_valid_hide_invocation_succeeds(cover, secret, capsys):
    code = main(["--hide", "-m", str(secret), "-c", str(cover)])
    capsys.readouterr()

    assert code == EXIT_OK
    assert (cover.parent / "cover_stego.obj").exists()


def test_extract_from_a_mesh_holding_no_payload_fails_cleanly(cover, capsys):
    """The one-vertex fixture yields no bits at all -- a clear message, no junk."""
    code = main(["--extract", "-s", str(cover)])
    err = capsys.readouterr().err

    assert code == EXIT_ERROR
    assert "no payload recovered" in err
    assert "Traceback" not in err
    assert not (cover.parent / "cover_payload.bin").exists()
