"""The package version, read back from installed distribution metadata.

This module holds no version literal, and neither does ``pyproject.toml``. The
git tag is the single source: ``hatch-vcs`` derives the distribution version from
it at build time (AD-30), and this reads that value back. So "keep the tag and
the package version in sync" is not a rule that can be broken -- there is only
one value, and the tag decides it.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

#: Distribution name, which is what carries the version metadata.
_DISTRIBUTION = "l3io-wordpress-config"

try:
    __version__ = version(_DISTRIBUTION)
except PackageNotFoundError:  # pragma: no cover - a source tree never installed
    # Deliberately sorts below every real release, so an uninstalled tree can
    # never be mistaken for a newer one.
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
