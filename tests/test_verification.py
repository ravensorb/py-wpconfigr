"""
Read-back verification (ADR-0010).

The guard exists to catch what the parser gets wrong, so these plant damage the
parser can actually do rather than confirming correct input passes. Each case
constructs the damaged result directly, so the test still holds if the parser
later changes.
"""

from l3io.wp.config.core.verification import verify_write

BEFORE = """<?php
define('DB_NAME', 'original');
define('DB_USER', 'someone');
$table_prefix = 'wp_';
"""


def test_sound_write_reports_nothing():
    actual = BEFORE.replace("'original'", "'updated'")
    assert (
        verify_write(before=BEFORE, actual=actual, written={("define", "DB_NAME"): "updated"}) == []
    )


def test_detects_a_neighbour_swallowed_on_the_same_line():
    """A greedy match can consume an adjacent define() sharing a line."""
    actual = """<?php
define('DB_NAME', 'updated');
$table_prefix = 'wp_';
"""
    problems = verify_write(
        before=BEFORE + "define('A', '1'); define('B', '2');\n",
        actual=actual,
        written={("define", "DB_NAME"): "updated"},
    )
    assert any("DB_USER" in p and "disappeared" in p for p in problems)


def test_detects_a_neighbour_altered_rather_than_removed():
    actual = BEFORE.replace("'original'", "'updated'").replace("'someone'", "'clobbered'")
    problems = verify_write(
        before=BEFORE, actual=actual, written={("define", "DB_NAME"): "updated"}
    )
    assert any("DB_USER" in p and "altered" in p for p in problems)
    assert not any("DB_NAME" in p for p in problems)


def test_detects_a_duplicate_key():
    """A duplicate means we matched one occurrence and WordPress uses the other."""
    actual = BEFORE.replace("'original'", "'updated'") + "define('DB_NAME', 'other');\n"
    problems = verify_write(
        before=BEFORE, actual=actual, written={("define", "DB_NAME"): "updated"}
    )
    assert any("DB_NAME" in p and "2 times" in p for p in problems)


def test_detects_a_key_that_never_landed():
    problems = verify_write(
        before=BEFORE, actual=BEFORE, written={("define", "NEVER_WRITTEN"): "x"}
    )
    assert any("NEVER_WRITTEN" in p and "absent" in p for p in problems)


def test_detects_a_value_that_did_not_round_trip():
    actual = BEFORE.replace("'original'", "'something-else'")
    problems = verify_write(
        before=BEFORE, actual=actual, written={("define", "DB_NAME"): "updated"}
    )
    assert any("DB_NAME" in p and "round-trip" in p for p in problems)


def test_a_define_and_a_variable_of_the_same_name_stay_distinct():
    before = "<?php\ndefine('prefix', 'a');\n$prefix = 'b';\n"
    actual = "<?php\ndefine('prefix', 'a');\n$prefix = 'c';\n"
    assert verify_write(before=before, actual=actual, written={("variable", "prefix"): "c"}) == []


def test_problem_text_never_quotes_a_value():
    """AD-14: no message contains a credential."""
    before = "<?php\ndefine('DB_PASSWORD', 'hunter2');\n"
    actual = "<?php\ndefine('DB_PASSWORD', 'tampered');\n"
    problems = verify_write(before=before, actual=actual, written={})
    assert problems
    assert all("hunter2" not in p and "tampered" not in p for p in problems)


def test_wordpress_own_spacing_is_not_a_mismatch():
    """WordPress writes `define( 'X', 'y' );`. A write preserves that formatting."""
    before = "<?php\ndefine( 'DB_NAME', 'original' );\n"
    actual = "<?php\ndefine( 'DB_NAME', 'updated' );\n"
    assert (
        verify_write(before=before, actual=actual, written={("define", "DB_NAME"): "updated"}) == []
    )
