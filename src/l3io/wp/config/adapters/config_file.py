"""
The I/O shell around the pure core: a ``wp-config.php`` on disk.

Holds a :class:`WpConfigString` rather than subclassing it (AD-1). Inheritance
would put every core method on this class automatically, so the surface declared
by ``__all__`` could not bound it.
"""

from __future__ import annotations

import os
from logging import getLogger
from pathlib import Path

from l3io.wp.config.core.config_string import Kind, WpConfigString
from l3io.wp.config.core.verification import verify_write
from l3io.wp.config.domain.errors import ConfigReadError, ConfigWriteError, ReadBackError
from l3io.wp.config.domain.values import ConfigValue, MissingType

__all__ = ["WpConfigFile"]

_log = getLogger(__name__)


class WpConfigFile:
    """
    Read and write ``define()`` constants in a ``wp-config.php`` file.

    Every :meth:`set` is verified by reading the result back before it is
    committed (ADR-0010). Verification failure leaves the original file
    untouched and raises :class:`ReadBackError`.

    Args:
        filename: Path to the ``wp-config.php`` file.

    Raises:
        ConfigReadError: The file cannot be read.
    """

    def __init__(self, filename: str | os.PathLike[str]) -> None:
        self._path = Path(filename)
        self._config = WpConfigString(self._read())

    @property
    def filename(self) -> str:
        """The path this instance reads and writes."""
        return str(self._path)

    @property
    def content(self) -> str:
        """The current content, including changes made by :meth:`set`."""
        return self._config.content

    def get(self, key: str) -> ConfigValue | MissingType:
        """
        The value of ``key``, or :data:`MISSING` if it is not defined.

        A key defined as ``false``, ``0`` or ``''`` is present and falsy, so test
        ``result is MISSING`` rather than truthiness.
        """
        return self._config.get(key)

    def set(self, key: str, value: ConfigValue) -> bool:
        """
        Set the ``define()`` constant ``key`` in the file, adding it if absent.

        Returns ``True`` if the file was changed, ``False`` if it already held
        this value -- in which case the file is not rewritten.

        Raises:
            ConfigValueError: ``value`` cannot be rendered as a PHP literal.
            ConfigWriteError: The file cannot be written.
            ReadBackError: The result did not verify; the file is unchanged.
        """
        return self._set("define", key, value)

    def get_variable(self, key: str) -> ConfigValue | MissingType:
        """
        The value of the file-scope variable ``key`` (named without its ``$``).

        ``$table_prefix`` is the one WordPress requires; a non-default prefix
        means site metadata is not in ``wp_options``.
        """
        return self._config.get_variable(key)

    def set_variable(self, key: str, value: ConfigValue) -> bool:
        """Set the file-scope variable ``key``, verified the same way as a define."""
        return self._set("variable", key, value)

    def _set(self, kind: Kind, key: str, value: ConfigValue) -> bool:
        before = self._config.content
        working = WpConfigString(before)
        mutate = working.set if kind == "define" else working.set_variable
        if not mutate(key, value):
            _log.debug("%r already up to date in %s; not rewriting.", key, self._path)
            return False

        intended = working.content
        tmp = self._path.with_name(f"{self._path.name}.l3io-tmp")
        try:
            tmp.write_text(intended, encoding="utf-8")
            # Read back from the temp file, so a failure never touches the original.
            actual = tmp.read_text(encoding="utf-8")
            problems = verify_write(before=before, actual=actual, written={(kind, key): value})
            if problems:
                raise ReadBackError(filename=str(self._path), mismatches=problems)
            tmp.replace(self._path)
        except OSError as exc:
            raise ConfigWriteError(filename=str(self._path), reason=str(exc), key=key) from exc
        finally:
            # Best-effort cleanup; the write already succeeded or already failed.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - cleanup must not mask the outcome
                _log.warning("Could not remove temporary file %s", tmp)

        self._config = WpConfigString(actual)
        _log.debug("%r written to %s and verified.", key, self._path)
        return True

    def verify(self) -> None:
        """
        Re-read the file and check it is internally sound.

        Raises:
            ConfigReadError: The file cannot be read.
            ReadBackError: The file contains duplicate definitions, or has
                diverged from the content this instance last wrote.
        """
        actual = self._read()
        problems = verify_write(before=self._config.content, actual=actual, written={})
        if problems:
            raise ReadBackError(filename=str(self._path), mismatches=problems)

    def _read(self) -> str:
        try:
            return self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigReadError(filename=str(self._path), reason=str(exc)) from exc
