"""How the workflows reference the LiquidLogicLabs actions.

Two rules, both learned the expensive way.

**One major per action, floating.** These are first-party actions: the same org
owns them and the repositories that consume them, so the supply-chain argument
for exact pins is much weaker than for a third-party action, and three repos
maintaining exact pins by hand drift. Third-party refs are deliberately NOT
covered here -- ``setup-uv`` is pinned exactly on purpose, because it stopped
publishing floating majors after v7.

**A version belongs to one action.** ``git-action-changelog-parser`` was pinned at
``@v3.0.14``, which is a real version -- of ``git-action-release-changelog-builder``,
whose name differs by two words. The parser publishes v1 and v2 only, so every
release would have failed at that step. Verified by direct ref lookup:

    gh api repos/LiquidLogicLabs/git-action-changelog-parser/git/ref/tags/v2   -> 49b9b1ce
    gh api repos/LiquidLogicLabs/git-action-changelog-parser/git/ref/tags/v3   -> 404

A tag LISTING does not catch this, because both names return a plausible list.
Only asking for the specific ref does. Nothing offline can check ref existence,
so this module checks the SHAPE and says so rather than implying more coverage
than it has.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

ORG = "LiquidLogicLabs/"

#: A floating major: exactly `vN`, nothing after it.
_FLOATING_MAJOR = re.compile(r"^v\d+$")


def _org_action_refs() -> dict[str, set[str]]:
    """Every LiquidLogicLabs ref in every workflow, as {action: {refs}}.

    Derived by walking the workflow directory rather than from a list, so a new
    workflow or a new action is covered the moment it is added.
    """
    found: dict[str, set[str]] = defaultdict(set)
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job in (document.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                uses = str(step.get("uses", ""))
                if not uses.startswith(ORG):
                    continue
                action, _, ref = uses.partition("@")
                found[action].add(ref)
    return dict(found)


@pytest.fixture(scope="module")
def refs() -> dict[str, set[str]]:
    if not WORKFLOWS.is_dir():
        pytest.skip("no workflows in this tree")
    found = _org_action_refs()
    # The scope assertion. Without it, a rename of the org or a move of the
    # workflow directory makes every test below pass having examined nothing.
    assert found, "no LiquidLogicLabs action references found -- these tests are vacuous"
    return found


def test_every_org_action_is_pinned_to_a_floating_major(refs: dict[str, set[str]]) -> None:
    offenders = {
        f"{action}@{ref}"
        for action, action_refs in refs.items()
        for ref in action_refs
        if not _FLOATING_MAJOR.match(ref)
    }
    assert not offenders, (
        f"pin org actions to a floating major (vN), not an exact version: {sorted(offenders)}"
    )


def test_each_org_action_uses_one_major(refs: dict[str, set[str]]) -> None:
    """The same action at two refs in one repo is a defect either way.

    This repo carried git-action-tag-validate-version at both `@v2` and `@v2.1.8`
    -- two different resolutions of the same action in the same pipeline, so the
    tag a release validates and the tag it creates could be parsed by different
    code.
    """
    divergent = {
        action: sorted(action_refs) for action, action_refs in refs.items() if len(action_refs) > 1
    }
    assert not divergent, f"one major per action, but found: {divergent}"


def test_the_changelog_actions_are_not_confused(refs: dict[str, set[str]]) -> None:
    """The two similarly named changelog actions have different major lines.

    ``git-action-release-changelog-builder`` reaches v3; ``git-action-changelog-parser``
    stops at v2. A v3 on the parser resolves nowhere, and the name similarity is
    the whole reason it happened.
    """
    parser = refs.get(f"{ORG}git-action-changelog-parser", set())
    assert "v3" not in parser, (
        "git-action-changelog-parser has no v3 -- v3 belongs to "
        "git-action-release-changelog-builder, whose name differs by two words"
    )


def test_the_changelog_config_never_drops_an_entry() -> None:
    """``defaultCategory: ""`` is the one setting that silently discards entries.

    This action appends an entry matching no category under ``defaultCategory``,
    so nothing is lost by default -- the upstream ``mikepenz`` action DROPS such
    entries when the template omits ``#{{UNCATEGORIZED}}``, and that difference is
    easy to carry across as a false belief. Verified against this action's README:
    "by default, appended under defaultCategory (## Other Changes), so nothing is
    silently lost". The real hazard is emptying that key.
    """
    import json

    path = REPO_ROOT / ".github" / "changelog-config.json"
    if not path.is_file():
        pytest.skip("no changelog config in this tree")

    config = json.loads(path.read_text(encoding="utf-8"))
    assert config.get("defaultCategory"), (
        'defaultCategory must be non-empty; "" silently discards every entry that '
        "matches no category, which for a release note is unrecoverable"
    )
    # Commit bodies in this repo run to dozens of lines; a body in the template
    # turns each release note into a transcript.
    assert "#{{BODY}}" not in config.get("commit_template", ""), (
        "commit_template must be subject-only"
    )


def test_a_job_reading_the_changelog_config_checks_out() -> None:
    """``configuration:`` is a path read from the working tree.

    A release job that only downloads the built artifact has no working tree, so
    the config file is simply absent and the builder falls back to its defaults
    with no error and no warning -- a silent downgrade of every release note.
    Derived by finding the jobs that actually use the input, rather than naming
    the release job, so a second consumer is covered when it appears.
    """
    if not WORKFLOWS.is_dir():
        pytest.skip("no workflows in this tree")

    checked = 0
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job_name, job in (document.get("jobs") or {}).items():
            steps = job.get("steps") or []
            wants_config = any(
                "changelog-builder" in str(step.get("uses", ""))
                and (step.get("with") or {}).get("configuration")
                for step in steps
            )
            if not wants_config:
                continue
            checked += 1
            has_checkout = any(
                str(step.get("uses", "")).startswith("actions/checkout") for step in steps
            )
            assert has_checkout, (
                f"{workflow.name}:{job_name} passes `configuration:` but never checks "
                "out, so the config file is absent and the builder uses its defaults"
            )

    assert checked, "no job passes `configuration:` -- this guard is vacuous"
