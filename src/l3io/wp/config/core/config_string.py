"""
Read and write ``define()`` constants in ``wp-config.php`` content.

Pure: string in, string out. No I/O, and nothing here imports ``ports``,
``adapters`` or ``cli`` (AD-1).

This is a reader and writer for the ``define()`` subset of PHP that WordPress
itself writes. It is **not** a PHP parser; ADR-0010 records its documented
limits and the read-back verification that guards them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from logging import getLogger
from typing import Literal

from l3io.wp.config.domain.errors import ConfigValueError, ConfigWriteError
from l3io.wp.config.domain.values import MISSING, ConfigValue, MissingType

__all__ = [
    "Constant",
    "Kind",
    "WpConfigString",
    "render_define",
    "render_statement",
    "render_value",
    "render_variable",
    "scan",
]

#: The two shapes `wp-config.php` carries. Connection settings are `define()`
#: constants; the table prefix is a variable assignment. Both are read and
#: written; nothing else in PHP is (ADR-0010).
Kind = Literal["define", "variable"]

_log = getLogger(__name__)

# Anchored at line start so a commented-out `// define(...)` never matches; that
# anchor is the v1.4 fix and is load-bearing. The value group is non-greedy and
# `.` excludes newlines, so a constant cannot swallow a neighbour on the same
# line or run past the end of its own.
_DEFINE_RE = re.compile(
    r"^[ \t]*define\s*\(\s*'(?P<key>(?:[^'\\]|\\.)*)'\s*,\s*(?P<value>.*?)\s*\)\s*;",
    re.MULTILINE,
)

# Same discipline as _DEFINE_RE: anchored at line start, so a commented-out
# assignment never matches, and `.` excludes newlines so a value stays on its
# own line. The anchor also approximates file scope -- an assignment indented
# inside a function body is not matched, which is the intent.
_VARIABLE_RE = re.compile(
    r"^[ \t]*\$(?P<key>[A-Za-z_]\w*)\s*=\s*(?P<value>.*?)\s*;",
    re.MULTILINE,
)

#: Each shape and the pattern that finds it. Annotated so the Literal survives.
_PATTERNS: tuple[tuple[Kind, re.Pattern[str]], ...] = (
    ("define", _DEFINE_RE),
    ("variable", _VARIABLE_RE),
)

_INT_RE = re.compile(r"^[+-]?\d+$")
_PHP_OPEN = "<?php\n"


@dataclass(frozen=True)
class Constant:
    """One ``define()`` occurrence found in the content."""

    kind: Kind
    """Which shape this is: a ``define()`` constant or a variable assignment."""
    key: str
    """The constant name, or the variable name without its ``$``."""
    raw_value: str
    """The value exactly as it appears in the source, unparsed."""
    start: int
    """Offset of the first character of ``raw_value``."""
    end: int
    """Offset one past the last character of ``raw_value``."""
    text: str
    """The whole matched ``define(...);`` as it appears in the source."""


def scan(content: str) -> list[Constant]:
    """Every ``define()`` and file-scope variable assignment, in source order."""
    found = [
        Constant(
            kind=kind,
            key=m.group("key"),
            raw_value=m.group("value"),
            start=m.start("value"),
            end=m.end("value"),
            text=m.group(0),
        )
        for kind, pattern in _PATTERNS
        for m in pattern.finditer(content)
    ]
    found.sort(key=lambda c: c.start)
    return found


def parse_value(raw: str) -> ConfigValue:
    """
    The Python value for a PHP literal, preserving the literal's own type.

    Quoted stays ``str``; unquoted ``true``/``false`` become ``bool``; unquoted
    integers become ``int``; unquoted decimals become ``float``; anything else is
    returned as raw source text (ADR-0010).
    """
    text = raw.strip()

    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("\\'", "'").replace("\\\\", "\\")

    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    if _INT_RE.match(text):
        return int(text)

    try:
        return float(text)
    except ValueError:
        return text


def render_value(key: str, value: ConfigValue) -> str:
    """The PHP literal for ``value``. Raises :class:`ConfigValueError` otherwise."""
    # bool before int: bool is a subclass of int.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    raise ConfigValueError(key=key, value_type=type(value).__name__)


def render_define(key: str, value: ConfigValue) -> str:
    """The whole ``define(...);`` statement for ``key``."""
    return f"define('{key}', {render_value(key, value)});"


def render_variable(key: str, value: ConfigValue) -> str:
    """The whole ``$key = ...;`` assignment."""
    return f"${key} = {render_value(key, value)};"


def render_statement(kind: Kind, key: str, value: ConfigValue) -> str:
    """The whole statement for ``key``, in whichever shape ``kind`` names."""
    if kind == "define":
        return render_define(key, value)
    return render_variable(key, value)


class WpConfigString:
    """
    Read and write ``define()`` constants in ``wp-config.php`` content.

    Args:
        content: The string content of a ``wp-config.php`` file.
    """

    def __init__(self, content: str) -> None:
        self._content = content

    @property
    def content(self) -> str:
        """The current content, including any changes made by :meth:`set`."""
        return self._content

    def get(self, key: str) -> ConfigValue | MissingType:
        """
        The value of the ``define()`` constant ``key``, or :data:`MISSING`.

        A key defined as ``false``, ``0`` or ``''`` is present and falsy, so test
        ``result is MISSING`` rather than truthiness.
        """
        return self._get("define", key)

    def set(self, key: str, value: ConfigValue) -> bool:
        """
        Set the ``define()`` constant ``key``, adding it if absent.

        Returns ``True`` if the content changed. Raises :class:`ConfigValueError`
        for an unrenderable value -- identically whether the key exists or not.
        """
        return self._set("define", key, value)

    def get_variable(self, key: str) -> ConfigValue | MissingType:
        """
        The value of the file-scope variable ``key`` (named without its ``$``).

        ``$table_prefix`` is the one WordPress requires; a non-default prefix
        means site metadata is not in ``wp_options`` (ADR-0010, handoff 5b).
        """
        return self._get("variable", key)

    def set_variable(self, key: str, value: ConfigValue) -> bool:
        """Set the file-scope variable ``key`` (named without its ``$``)."""
        return self._set("variable", key, value)

    def _get(self, kind: Kind, key: str) -> ConfigValue | MissingType:
        for constant in scan(self._content):
            if constant.kind == kind and constant.key == key:
                return parse_value(constant.raw_value)
        return MISSING

    def _set(self, kind: Kind, key: str, value: ConfigValue) -> bool:
        # Render first, so an unrenderable value fails the same way on both paths.
        rendered = render_value(key, value)

        for constant in scan(self._content):
            if constant.kind != kind or constant.key != key:
                continue
            if constant.raw_value == rendered:
                _log.debug("%r is already up to date.", key)
                return False
            self._content = (
                self._content[: constant.start] + rendered + self._content[constant.end :]
            )
            _log.debug("%r updated.", key)
            return True

        if _PHP_OPEN not in self._content:
            raise ConfigWriteError(
                filename="<string>",
                reason=f"no {_PHP_OPEN!r} opening tag to insert after",
                key=key,
            )

        statement = render_statement(kind, key, value)
        # count=1: insert after the FIRST opening tag only. Without it, a file
        # carrying two `<?php` markers receives two copies of the statement.
        self._content = self._content.replace(_PHP_OPEN, _PHP_OPEN + statement + "\n", 1)
        _log.debug("%r added.", key)
        return True
