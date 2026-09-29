"""AD-30 -- the git tag is the only source of the version.

``pyproject.toml`` declares ``dynamic = ["version"]`` and ``hatch-vcs`` derives the
distribution version from the git tag at build time; ``_version.py`` reads it back
out of the installed metadata. So there is exactly one value and no rule for
anyone to break.

What is worth guarding is the ARRANGEMENT, not the agreement. Asserting that
``__version__`` equals ``importlib.metadata.version(...)`` is now tautological --
it is the same call -- so these tests check the wiring that makes it true, and in
particular the tag match pattern, which is the least obvious part and the most
likely to be deleted as noise.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from l3io.wp import config

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

#: Matches a module-level assignment of a version-shaped string literal.
_VERSION_LITERAL = re.compile(
    r"""^\s*(?:__version__|VERSION|version)\s*(?::\s*[^=]+)?=\s*["']\d+\.\d+""",
    re.MULTILINE,
)


@pytest.fixture(scope="module")
def pyproject() -> dict[str, Any]:
    path = REPO_ROOT / "pyproject.toml"
    if not path.is_file():
        pytest.skip("installed without the source tree")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_version_is_resolvable() -> None:
    """The attribute exists and is not the uninstalled sentinel."""
    assert config.__version__
    assert config.__version__ != "0.0.0+unknown", (
        "the distribution is not installed, so the version could not be read"
    )


def test_pyproject_declares_the_version_dynamic(pyproject: dict[str, Any]) -> None:
    project = pyproject["project"]
    assert "version" in project.get("dynamic", []), (
        "project.dynamic must contain 'version'; without it pyproject needs its "
        "own literal and the tag stops being the source"
    )
    assert "version" not in project, "pyproject.toml declares a version literal"


def test_the_version_source_is_the_vcs(pyproject: dict[str, Any]) -> None:
    hatch_version = pyproject["tool"]["hatch"]["version"]
    assert hatch_version["source"] == "vcs"
    assert "hatch-vcs" in pyproject["build-system"]["requires"]


def test_dev_builds_carry_no_local_version_label(pyproject: dict[str, Any]) -> None:
    """PyPI rejects a local label, so a dev build must not carry +g<sha>."""
    raw = pyproject["tool"]["hatch"]["version"]["raw-options"]
    assert raw["local_scheme"] == "no-local-version"


def test_only_three_component_tags_are_candidates(pyproject: dict[str, Any]) -> None:
    """The guard against this repo's two-component tags.

    Without the match, ``v1.0`` is the nearest ancestor of every commit on main;
    setuptools-scm reads its two components, guesses the next MINOR, and builds
    come out as ``1.1.devN`` -- which sorts ABOVE ``1.0.0`` in PEP 440, so
    publishing one would permanently outrank the real release. Reproduced before
    this pattern was added.
    """
    raw = pyproject["tool"]["hatch"]["version"]["raw-options"]
    describe = raw["git_describe_command"]
    assert "--match" in describe
    assert "v[0-9]*.[0-9]*.[0-9]*" in describe, (
        "the describe match must require three components, or the two-component "
        "v1.0 tag becomes the version basis again"
    )


def test_no_module_carries_a_version_literal() -> None:
    """Scope-derived: every module under src/, not a hand-kept list.

    A literal reintroduced anywhere in the package is a second source that
    nothing compares against the tag. Derived by walking the tree so that a new
    module is covered the moment it is added.
    """
    if not SRC.is_dir():
        pytest.skip("installed without the source tree")

    modules = sorted(SRC.rglob("*.py"))
    assert modules, "no modules found under src/ -- this guard would pass vacuously"

    offenders = []
    for module in modules:
        text = module.read_text(encoding="utf-8")
        if not _VERSION_LITERAL.search(text):
            continue
        # A literal is only ever acceptable as the fallback beside the real read,
        # which is what _version.py does for a tree that was never installed.
        # Expressed structurally rather than by naming that file, so a literal
        # added to any other module is still caught.
        if "importlib.metadata" in text:
            continue
        offenders.append(str(module.relative_to(REPO_ROOT)))

    assert not offenders, f"version literals found, tag is no longer the source: {offenders}"


def test_every_workflow_checkout_fetches_tags() -> None:
    """AD-30 -- a shallow checkout silently misversions the build.

    hatch-vcs derives the version from the nearest tag. ``actions/checkout``
    defaults to depth 1 and fetches no tags, so setuptools-scm finds none and
    falls back to ``0.1.devN`` -- no error, green job, wrongly versioned artifact.
    Reproduced against a real ``--depth 1`` clone before this guard was added.

    Applied to every checkout rather than only the ones that build, because which
    jobs build is a fact that changes and this is a fact that does not. The set is
    read from the workflow directory so a new workflow is covered on arrival.
    """
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    if not workflows:
        pytest.skip("no workflows in this tree")

    checkouts: list[str] = []
    offenders: list[str] = []
    for workflow in workflows:
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job_name, job in (document.get("jobs") or {}).items():
            for index, step in enumerate(job.get("steps") or []):
                if not str(step.get("uses", "")).startswith("actions/checkout"):
                    continue
                where = f"{workflow.name}:{job_name}[step {index}]"
                checkouts.append(where)
                if (step.get("with") or {}).get("fetch-depth") != 0:
                    offenders.append(where)

    # The scope assertion. Without it this passes on a tree whose workflows were
    # renamed to .yaml, or moved, having examined nothing.
    assert checkouts, "no actions/checkout steps found -- this guard is vacuous"
    assert not offenders, f"checkouts without fetch-depth: 0 (version will be wrong): {offenders}"
