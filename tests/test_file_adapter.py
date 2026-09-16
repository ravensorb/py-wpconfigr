"""The file adapter: verified writes, and package-owned errors at the boundary."""

import pytest

from l3io.wp.config import (
    MISSING,
    ConfigReadError,
    ReadBackError,
    WpConfigError,
    WpConfigFile,
    WpConfigString,
)

SOUND = "<?php\ndefine('DB_NAME', 'original');\n$table_prefix = 'wp_';\n"


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_text(SOUND)
    return path


def test_composition_not_inheritance():
    """AD-1: inheritance would put every core method on the adapter's surface."""
    assert not issubclass(WpConfigFile, WpConfigString)


def test_read_and_write_round_trip(config_file):
    config = WpConfigFile(config_file)
    assert config.get("DB_NAME") == "original"
    assert config.set("DB_NAME", "updated") is True
    assert WpConfigFile(config_file).get("DB_NAME") == "updated"


def test_writing_the_same_value_does_not_rewrite(config_file):
    before = config_file.stat().st_mtime_ns
    assert WpConfigFile(config_file).set("DB_NAME", "original") is False
    assert config_file.stat().st_mtime_ns == before


def test_table_prefix_round_trip(config_file):
    config = WpConfigFile(config_file)
    assert config.get_variable("table_prefix") == "wp_"
    assert config.set_variable("table_prefix", "wpfoo_") is True
    assert WpConfigFile(config_file).get_variable("table_prefix") == "wpfoo_"


def test_absent_key_is_missing_not_none(config_file):
    assert WpConfigFile(config_file).get("NOPE") is MISSING


def test_a_failed_read_back_leaves_the_original_untouched(tmp_path):
    """
    A file already carrying a duplicate definition cannot be written safely: the
    pattern matches one occurrence while WordPress uses the other.
    """
    path = tmp_path / "wp-config.php"
    damaged = "<?php\ndefine('DB_NAME', 'a');\ndefine('DB_NAME', 'b');\n"
    path.write_text(damaged)

    config = WpConfigFile(path)
    with pytest.raises(ReadBackError) as caught:
        config.set("DB_NAME", "c")

    assert path.read_text() == damaged, "the original file must survive intact"
    assert any("2 times" in problem for problem in caught.value.mismatches)


def test_no_temporary_file_is_left_behind(tmp_path):
    path = tmp_path / "wp-config.php"
    path.write_text("<?php\ndefine('DB_NAME', 'a');\ndefine('DB_NAME', 'b');\n")
    with pytest.raises(ReadBackError):
        WpConfigFile(path).set("DB_NAME", "c")
    assert list(tmp_path.iterdir()) == [path]


def test_a_missing_file_raises_a_package_owned_error(tmp_path):
    """AD-14: no stdlib exception type crosses the public boundary."""
    with pytest.raises(ConfigReadError) as caught:
        WpConfigFile(tmp_path / "absent.php")
    assert isinstance(caught.value, WpConfigError)
    assert not isinstance(caught.value, OSError)
    assert caught.value.__cause__ is not None, "the cause must be chained"


def test_errors_carry_structured_fields(tmp_path):
    with pytest.raises(ConfigReadError) as caught:
        WpConfigFile(tmp_path / "absent.php")
    assert caught.value.filename.endswith("absent.php")
    assert caught.value.reason


def test_every_public_error_descends_from_one_base():
    import l3io.wp.config as package

    errors = [
        getattr(package, name)
        for name in package.__all__
        if isinstance(getattr(package, name), type)
        and issubclass(getattr(package, name), BaseException)
    ]
    assert errors, "the package must export its error hierarchy"
    assert all(issubclass(error, WpConfigError) for error in errors)


def test_a_file_with_no_php_newline_raises_and_leaves_the_file_alone(tmp_path):
    """The same ADR-0010 limit, through the file adapter."""
    from l3io.wp.config import ConfigWriteError

    path = tmp_path / "wp-config.php"
    original = "<?php define('DB_NAME', 'a');\n"
    path.write_text(original)

    with pytest.raises(ConfigWriteError):
        WpConfigFile(path).set("BRAND_NEW", "x")

    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path], "no temporary file left behind"
