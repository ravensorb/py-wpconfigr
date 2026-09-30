"""The dry-run legs must reach every trigger, or they validate nothing there.

``make ci-dryrun`` exists because `make ci` cannot run publish.yml or release.yml:
act has no OIDC, ignores ``job.permissions``, and release.yml creates tags. A dry
run is the substitute, and it is worth more than YAML validation because act
resolves every ``uses:`` ref against the remote before skipping a step -- so it
fails on an action version that does not exist.

**But only for jobs the event actually reaches.** A job skipped by its ``if:`` never
has its refs resolved. The first version of this gate ran publish.yml under
``workflow_dispatch`` only, which skips the release job entirely -- and the release
job is where ``changelog-parser@v3.0.14`` hid. Planting a bad ref there passed.
So these tests assert the legs cover every declared trigger and every choice
option, which is the property that failed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
LEGS_FILE = REPO_ROOT / ".github" / "act-dryrun-legs.json"

#: Run for real by `make ci`, and act segfaults dry-running it (service containers).
EXCLUDED = {"ci.yml"}


@pytest.fixture(scope="module")
def legs() -> list[dict[str, Any]]:
    if not LEGS_FILE.is_file():
        pytest.skip("no dry-run legs declared in this tree")
    parsed: dict[str, Any] = json.loads(LEGS_FILE.read_text(encoding="utf-8"))
    declared: list[dict[str, Any]] = parsed["legs"]
    assert declared, "no legs declared -- every test here would pass vacuously"
    return declared


def _triggers(document: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML parses the bare key `on:` as the boolean True, not the string "on",
    # which is why this helper exists and why its parameter is keyed on Any.
    triggers: dict[str, Any] = document[True] if True in document else document["on"]
    return triggers


def _legged_workflows() -> list[Path]:
    return [w for w in sorted(WORKFLOWS.glob("*.yml")) if w.name not in EXCLUDED]


def test_every_workflow_outside_make_ci_has_at_least_one_leg(legs: list[dict[str, Any]]) -> None:
    covered = {leg["workflow"] for leg in legs}
    expected = {w.name for w in _legged_workflows()}
    assert expected, "no workflows found outside the excluded set -- this guard is vacuous"
    assert expected <= covered, f"no dry-run leg for: {sorted(expected - covered)}"


def test_every_declared_trigger_has_a_leg(legs: list[dict[str, Any]]) -> None:
    """The gap that let a bad ref through: one trigger tested, three declared."""
    missing: list[str] = []
    for workflow in _legged_workflows():
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        declared = set(_triggers(document))
        tested = {leg["event"] for leg in legs if leg["workflow"] == workflow.name}
        for event in sorted(declared - tested):
            missing.append(f"{workflow.name}:{event}")
    assert not missing, (
        "these triggers have no dry-run leg, so jobs reachable only by them never "
        f"have their action refs resolved: {missing}"
    )


def test_every_choice_option_has_a_leg(legs: list[dict[str, Any]]) -> None:
    """A target/bump value gates whole jobs, so an untested option is untested jobs."""
    missing: list[str] = []
    for workflow in _legged_workflows():
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        dispatch = _triggers(document).get("workflow_dispatch") or {}
        for name, spec in (dispatch.get("inputs") or {}).items():
            if spec.get("type") != "choice":
                continue
            tested = {
                (leg.get("inputs") or {}).get(name)
                for leg in legs
                if leg["workflow"] == workflow.name
            }
            for option in spec["options"]:
                if option not in tested:
                    missing.append(f"{workflow.name}:{name}={option}")
    assert not missing, f"choice options with no dry-run leg: {missing}"


def test_every_named_event_payload_exists(legs: list[dict[str, Any]]) -> None:
    """A missing payload file makes act fall back to a default event, silently."""
    for leg in legs:
        path = leg.get("eventpath")
        if path is None:
            continue
        where = f"{leg['workflow']}:{leg['event']}"
        assert (REPO_ROOT / path).is_file(), f"{where} names a missing payload: {path}"
