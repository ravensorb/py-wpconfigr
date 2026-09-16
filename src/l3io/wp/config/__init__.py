"""
Read and write ``define()`` constants in a WordPress ``wp-config.php`` file.

A reader and writer for the ``define()`` subset of PHP that WordPress itself
writes -- not a PHP parser. ADR-0010 records the documented limits and the
read-back verification that guards them.
"""

from l3io.wp.config.adapters.config_file import WpConfigFile
from l3io.wp.config.core.config_string import WpConfigString
from l3io.wp.config.domain.errors import (
    ConfigReadError,
    ConfigValueError,
    ConfigWriteError,
    ReadBackError,
    WpConfigError,
)
from l3io.wp.config.domain.values import MISSING, ConfigValue, MissingType

__all__ = [
    "MISSING",
    "ConfigReadError",
    "ConfigValue",
    "ConfigValueError",
    "ConfigWriteError",
    "MissingType",
    "ReadBackError",
    "WpConfigError",
    "WpConfigFile",
    "WpConfigString",
]
