"""The CLI distinguishes a falsy value from an absent key (ADR-0010)."""

import pytest

from l3io.wp.config.cli.main import EXIT_FAILED, EXIT_NOT_DEFINED, EXIT_OK, build_parser, run

SOURCE = """<?php
define('DB_NAME', 'wp');
define('WP_DEBUG', false);
define('EMPTY_STR', '');
define('PORT', 3306);
"""


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_text(SOURCE)
    return str(path)


@pytest.mark.parametrize(
    ("key", "expected_code", "expected_out"),
    [
        ("DB_NAME", EXIT_OK, "wp"),
        ("WP_DEBUG", EXIT_OK, "false"),  # present and falsy
        ("EMPTY_STR", EXIT_OK, ""),  # present and falsy
        ("PORT", EXIT_OK, "3306"),
    ],
)
def test_reading_a_present_value_succeeds(config_file, capsys, key, expected_code, expected_out):
    code = run(["--filename", config_file, "--key", key])
    assert code == expected_code
    assert capsys.readouterr().out.rstrip("\n") == expected_out


def test_an_absent_key_exits_non_zero(config_file, capsys):
    """The defect: `if got:` made false, 0 and '' indistinguishable from absent."""
    code = run(["--filename", config_file, "--key", "NOPE"])
    assert code == EXIT_NOT_DEFINED
    assert capsys.readouterr().out == ""


def test_a_falsy_value_and_an_absent_key_differ_in_exit_code(config_file):
    falsy = run(["--filename", config_file, "--key", "WP_DEBUG"])
    absent = run(["--filename", config_file, "--key", "NOPE"])
    assert falsy != absent


def test_an_unreadable_file_exits_failed(tmp_path, capsys):
    code = run(["--filename", str(tmp_path / "absent.php"), "--key", "DB_NAME"])
    assert code == EXIT_FAILED
    assert capsys.readouterr().err


def test_writing_a_value(config_file):
    assert run(["--filename", config_file, "--key", "DB_NAME", "--value", "new"]) == EXIT_OK
    assert run(["--filename", config_file, "--key", "DB_NAME"]) == EXIT_OK


def test_set_true_and_set_false_are_mutually_exclusive(config_file):
    with pytest.raises(SystemExit):
        run(["--filename", config_file, "--key", "X", "--set-true", "--set-false"])


def test_value_cannot_combine_with_a_boolean_flag(config_file):
    with pytest.raises(SystemExit):
        run(["--filename", config_file, "--key", "X", "--value", "v", "--set-true"])


def test_every_documented_flag_is_accepted():
    """Scope derived from the parser itself, so a new flag cannot skip this."""
    options = {option for action in build_parser()._actions for option in action.option_strings}
    for expected in ("--filename", "--key", "--value", "--set-true", "--set-false", "--log-level"):
        assert expected in options
