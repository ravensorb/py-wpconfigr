"""End-to-end update of a real WordPress wp-config.php sample."""

import shutil
from pathlib import Path

import pytest

from l3io.wp.config import WpConfigFile

FIXTURES = Path(__file__).resolve().parent
ORIGINAL = FIXTURES / "wp-config-sample.original.php"
EXPECTED = FIXTURES / "wp-config-sample.expected.php"


@pytest.fixture
def sample(tmp_path):
    """
    A copy in tmp_path rather than beside the fixtures.

    The previous version wrote `wp-config-sample.actual.php` into the tests
    directory and unlinked it at the end, so a mid-test failure stranded an
    untracked file in the working tree.
    """
    target = tmp_path / "wp-config.php"
    shutil.copy(ORIGINAL, target)
    return target


def test_read(sample):
    assert WpConfigFile(sample).get("DB_PASSWORD") == "password_here"


def test_write(sample):
    config = WpConfigFile(sample)
    config.set("DB_NAME", "updated-db-name")
    config.set("DB_USER", "updated-db-user")
    config.set("DB_COLLATE", "updated-db-collate")
    config.set("AUTH_KEY", "updated-auth-key")
    config.set("WP_DEBUG", True)
    config.set("WP_NEW_STRING", "bar")
    config.set("WP_NEW_TRUE", True)
    config.set("WP_NEW_FALSE", False)

    assert sample.read_text().splitlines() == EXPECTED.read_text().splitlines()


def test_the_sample_carries_a_table_prefix(sample):
    """WordPress ships `$table_prefix` as a variable, not a define()."""
    assert WpConfigFile(sample).get_variable("table_prefix") == "wp_"
