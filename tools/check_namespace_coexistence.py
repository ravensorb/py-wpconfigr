"""
AD-27 enforcement: prove the PEP 420 namespace survives a sibling distribution.

A distribution tested alone cannot catch a namespace shadow -- an `__init__.py`
at `l3io/` or `l3io/wp/` makes this package a regular package and its siblings
unimportable, while this package's own tests still pass. The failure appears
only when two distributions are installed together.

This does not wait for the real siblings to exist. It builds a stub distribution
claiming the same namespace and checks both install shapes AD-27 names:

  1. two wheels in one interpreter
  2. one editable plus one wheel, where `l3io.wp.__path__` must MERGE the
     site-packages entry with the editable tree

Shape 2 is the one that usually breaks for src-layout namespace packages.

Run directly, or via `make namespace-check`. CI runs the same script, so the two
cannot drift.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

STUB_PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "l3io-wp-database"
version = "0.0.0"
description = "Stub sibling. Exists only to prove AD-27; never published."
requires-python = ">=3.11"

[tool.hatch.build.targets.wheel]
packages = ["src/l3io"]
"""

# The assertion body, run INSIDE each isolated environment.
PROBE = """\
import pathlib, sys
import l3io, l3io.wp
import l3io.wp.config as cfg
import l3io.wp.database as db

# Two checks that fail at different times, deliberately kept together.
#
# The property check is the true one: a genuine PEP 420 namespace package has no
# __init__.py to execute, so __file__ is either None or absent entirely
# depending on the Python version -- hence getattr with a default, because a bare
# attribute access raises AttributeError and turns a clear failure into a
# confusing one. It also catches what a file scan cannot see: a backend that
# synthesises an __init__.py, or a stray one arriving from another installed
# distribution claiming the same prefix.
#
# The marker scan is the earlier signal, catching it before a build.
#
# The positive assertion below matters as much as both: it proves the merged
# path actually reached the sibling's code. Asserting only the two negatives
# would pass in a world where the sibling is absent entirely.
for name, pkg in (("l3io", l3io), ("l3io.wp", l3io.wp)):
    if getattr(pkg, "__file__", None) is not None:
        sys.exit(f"AD-27 VIOLATION: {name} is a regular package ({pkg.__file__})")
    for entry in pkg.__path__:
        marker = pathlib.Path(entry) / "__init__.py"
        if marker.exists():
            sys.exit(f"AD-27 VIOLATION: {marker} shadows the PEP 420 namespace")

assert cfg.WpConfigString("<?php\\ndefine('X', 'y');\\n").get("X") == "y"
assert db.marker == "stub-sibling"
print("  ok:", len(l3io.wp.__path__), "path entry/entries:", *l3io.wp.__path__)
"""


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def build_stub(root: Path) -> Path:
    """Build the stub sibling and return its wheel."""
    area = root / "src" / "l3io" / "wp" / "database"
    area.mkdir(parents=True)
    # Deliberately NO __init__.py at src/l3io/ or src/l3io/wp/ -- same rule.
    (area / "__init__.py").write_text('__all__ = ["marker"]\nmarker = "stub-sibling"\n')
    (root / "pyproject.toml").write_text(STUB_PYPROJECT)
    run("uv", "build", "--no-sources", cwd=root)
    return next((root / "dist").glob("*.whl"))


def check(label: str, env_root: Path, *install: str) -> bool:
    """Install into a fresh environment and run the probe. True if it held."""
    print(f"{label}:")
    run("uv", "venv", "--python", "3.11", "-q", str(env_root / ".venv"))
    python = env_root / ".venv" / "bin" / "python"
    run("uv", "pip", "install", "--python", str(python), "-q", *install)
    result = subprocess.run([str(python), "-c", PROBE], capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        print(f"  FAILED: {label}")
        return False
    return True


def main() -> int:
    run("uv", "build", "--no-sources", cwd=REPO)
    mine = max((REPO / "dist").glob("*.whl"), key=lambda p: p.stat().st_mtime)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stub = build_stub(root / "stub")

        held = [
            check("two wheels in one interpreter", root / "wheels", str(mine), str(stub)),
            check("editable plus wheel", root / "editable", "-e", str(REPO), str(stub)),
        ]

    if not all(held):
        print("\nAD-27 NOT satisfied.")
        return 1
    print("\nAD-27 satisfied: the namespace survives a sibling in both install shapes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
