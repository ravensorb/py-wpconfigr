"""Type fidelity and the documented parser limits (ADR-0010)."""

import pytest

from l3io.wp.config import MISSING, ConfigValueError, ConfigWriteError, WpConfigString

SOURCE = """<?php
define('QUOTED',    'hello');
define('NUMSTR',    '3306');
define('TRUE',      true);
define('FALSE',     false);
define('INTEGER',   1);
define('NEGATIVE',  -7);
define('FLOAT',     2.3);
define('DOUBLEQ',   "wp");
define('EXPR',      ABSPATH . 'x');
define('EMPTY',     '');
// define('COMMENTED', 'no');
$table_prefix = 'wp_';
"""


@pytest.mark.parametrize(
    ("key", "expected", "expected_type"),
    [
        ("QUOTED", "hello", str),
        ("NUMSTR", "3306", str),  # quoted stays str even though it looks numeric
        ("TRUE", True, bool),
        ("FALSE", False, bool),
        ("INTEGER", 1, int),  # was 1.0 before the ADR-0010 fix
        ("NEGATIVE", -7, int),
        ("FLOAT", 2.3, float),
        ("EMPTY", "", str),
    ],
)
def test_type_fidelity(key, expected, expected_type):
    value = WpConfigString(SOURCE).get(key)
    assert value == expected
    assert type(value) is expected_type


def test_double_quoted_is_returned_as_raw_text():
    """A documented limit: only single-quoted values are parsed as strings."""
    assert WpConfigString(SOURCE).get("DOUBLEQ") == '"wp"'


def test_php_expression_is_returned_as_raw_text():
    assert WpConfigString(SOURCE).get("EXPR") == "ABSPATH . 'x'"


def test_commented_definitions_are_invisible():
    assert WpConfigString(SOURCE).get("COMMENTED") is MISSING


def test_absent_and_falsy_are_distinguishable():
    config = WpConfigString(SOURCE)
    assert config.get("NOPE") is MISSING
    assert config.get("FALSE") is False
    assert config.get("EMPTY") == ""
    assert config.get("FALSE") is not MISSING


def test_variable_assignment_is_read():
    assert WpConfigString(SOURCE).get_variable("table_prefix") == "wp_"


def test_commented_variable_assignment_is_invisible():
    config = WpConfigString("<?php\n// $table_prefix = 'no_';\n")
    assert config.get_variable("table_prefix") is MISSING


def test_insertion_happens_once_even_with_two_php_markers():
    """`str.replace` with no count would insert at every marker."""
    content = "<?php\ndefine('A', 'a');\n?>\n<?php\ndefine('B', 'b');\n"
    config = WpConfigString(content)
    assert config.set("NEW", "x") is True
    assert config.content.count("define('NEW'") == 1


def test_unrenderable_value_fails_identically_whether_the_key_exists():
    """The old code raised TypeError only when the key already existed."""
    existing = WpConfigString("<?php\ndefine('X', 'a');\n")
    missing = WpConfigString("<?php\n")
    with pytest.raises(ConfigValueError):
        existing.set("X", [1, 2])  # type: ignore[arg-type]  # deliberate: the error path
    with pytest.raises(ConfigValueError):
        missing.set("X", [1, 2])  # type: ignore[arg-type]  # deliberate: the error path


def test_setting_an_int_works_on_both_paths():
    existing = WpConfigString("<?php\ndefine('PORT', 3306);\n")
    missing = WpConfigString("<?php\n")
    assert existing.set("PORT", 3307) is True
    assert missing.set("PORT", 3307) is True
    assert existing.get("PORT") == 3307
    assert missing.get("PORT") == 3307


def test_setting_the_same_value_reports_no_change():
    config = WpConfigString("<?php\ndefine('X', 'a');\n")
    assert config.set("X", "a") is False


def test_a_quoted_value_survives_a_round_trip():
    config = WpConfigString("<?php\ndefine('DB_PASSWORD', 'x');\n")
    config.set("DB_PASSWORD", "8675309")
    assert config.get("DB_PASSWORD") == "8675309"
    assert type(config.get("DB_PASSWORD")) is str


def test_a_file_with_no_php_newline_raises_rather_than_silently_skipping():
    """
    ADR-0010's third limit: insertion anchors on a literal ``<?php\\n``. A file
    opening ``<?php `` without a newline previously got no insertion *silently*
    and ``set()`` still reported success. It now fails loudly instead.
    """
    config = WpConfigString("<?php define('A', 'a');\n")
    with pytest.raises(ConfigWriteError) as caught:
        config.set("NEW", "x")
    assert caught.value.key == "NEW"
    assert "opening tag" in caught.value.reason
    assert config.content == "<?php define('A', 'a');\n", "content must be untouched"


def test_a_define_sharing_a_line_with_the_php_tag_is_invisible():
    """
    The line-start anchor is what makes a commented-out definition invisible,
    and it applies uniformly: a ``define()`` sharing a line with ``<?php`` is not
    at the start of a line either, so it is not seen. Real WordPress configs put
    ``<?php`` on its own line. Documented in the README's scope section.
    """
    config = WpConfigString("<?php define('A', 'a');\n")
    assert config.get("A") is MISSING
