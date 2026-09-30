#!/usr/bin/env python3
# A suite declares the dependencies of the script it drives, so `uv run <this file>`
# works with no flags. They used to be passed as `--with` on the CI command line only,
# which made the suite unrunnable as written anywhere else: running it directly gave
# spurious failures that looked like real defects. It also made the CI step unshareable,
# so the workflow had to name every suite by hand.
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
Tests for audit-backlog.py. Run with:
  uv run -q --with 'ruamel.yaml>=0.18' python3 skills/l3io-doctor/scripts/tests/test-audit-backlog.py
Items are always created through the real pm-status.py CLI, never hand-written.
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout


# -- temp-dir leak guard ---------------------------------------------------------------- #
# setUpModule points tempfile.tempdir (this test process) AND the TMPDIR environment variable
# (inherited by every subprocess it spawns) at one private run directory; tearDownModule fails
# the run if anything is left in it, then removes it and restores both to their prior values.
# Covered: every tempfile.mkdtemp()/mkstemp()/NamedTemporaryFile() made by this process or by
# a child that honours TMPDIR. Not covered: a child that writes to a hard-coded directory. The
# one name it ignores is `uv-*.lock`, which `uv run` leaves in TMPDIR by design
# (test-write-module-config spawns `uv run`). Fixtures without cleanup once left 60,936
# directories in /tmp and exhausted its inodes. Set in setUpModule, not at import, so a child
# process that re-imports this module never creates a run directory it would not remove.
_RUN_TMP = None
_PREV_TMPDIR = None             # the TMPDIR environment variable, or None
_PREV_TEMPFILE_TEMPDIR = None   # tempfile.tempdir as it was before setUpModule


def setUpModule():
    global _RUN_TMP, _PREV_TMPDIR, _PREV_TEMPFILE_TEMPDIR
    _PREV_TEMPFILE_TEMPDIR = tempfile.tempdir
    _RUN_TMP = tempfile.mkdtemp(prefix="test-audit-backlog-")
    tempfile.tempdir = _RUN_TMP
    _PREV_TMPDIR = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = _RUN_TMP


def tearDownModule():
    tempfile.tempdir = _PREV_TEMPFILE_TEMPDIR
    if _PREV_TMPDIR is None:
        os.environ.pop("TMPDIR", None)
    else:
        os.environ["TMPDIR"] = _PREV_TMPDIR
    leaked = sorted(n for n in os.listdir(_RUN_TMP)
                    if not (n.startswith("uv-") and n.endswith(".lock")))
    shutil.rmtree(_RUN_TMP, ignore_errors=True)
    if leaked:
        raise AssertionError(f"temp-dir leak: {len(leaked)} entr"
                             f"{'y' if len(leaked) == 1 else 'ies'} left by tests without "
                             f"cleanup: {', '.join(leaked[:5])}")

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "audit-backlog.py")
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
PM = os.path.join(REPO, "skills", "_shared", "pm-status.py")

_spec = importlib.util.spec_from_file_location("audit_backlog", SCRIPT)
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.proj = os.path.join(self.d, "proj")
        self.arts = os.path.join(self.proj, "_impl")
        self.state = os.path.join(self.arts, "state")
        os.makedirs(self.state)

    def pm(self, *args):
        p = subprocess.run([sys.executable, PM, *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def append(self, title, source, epic="001", sprint="01", severity="Low", description=None):
        argv = ["append-issue", "--state-root", self.state, "--epic", epic, "--sprint", sprint,
                "--title", title, "--source", source, "--severity", severity]
        if description:
            argv += ["--description", description]
        return self.pm(*argv)

    def write(self, rel, text, base=None):
        p = os.path.join(base or self.proj, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def run_audit(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ab.main(["--pm-status", PM, "--state-root", self.state, "--artifacts-root",
                            self.arts, "--project-root", self.proj, "--format", "json"])
        self.assertEqual(code, 0)
        return json.loads(buf.getvalue())

    def verdicts(self):
        return {v["key"]: v for v in self.run_audit()["verdicts"]}


class TestMarkers(Base):
    MARKER = "# bmad-defer: linear scan over the cache. ceiling: <500. upgrade: index.\n"

    def test_marker_removed_is_fixed_candidate(self):
        self.write("src/a.py", "x = 1\n")
        self.append("linear scan over the cache.", "code-marker (src/a.py:3)")
        self.assertEqual(self.verdicts()["BL-E001-001"]["verdict"], "fixed-candidate")

    def test_marker_present_is_open_with_its_line(self):
        self.write("src/a.py", "x = 1\n" + self.MARKER)
        self.append("linear scan over the cache.", "code-marker (src/a.py:9)")
        v = self.verdicts()["BL-E001-001"]
        self.assertEqual(v["verdict"], "open")
        self.assertIn("src/a.py:2", v["evidence"])

    def test_title_text_outside_a_marker_line_does_not_count(self):
        self.write("src/a.py", "# linear scan over the cache, still here\n")
        self.append("linear scan over the cache.", "code-marker (src/a.py:1)")
        self.assertEqual(self.verdicts()["BL-E001-001"]["verdict"], "fixed-candidate")

    def test_marker_embedded_in_a_longer_source_is_recognized(self):
        self.write("src/b.py", "y = 2\n")
        self.append("debug print", "clean-release (code-marker src/b.py:9)")
        self.assertEqual(self.verdicts()["BL-E001-001"]["verdict"], "fixed-candidate")

    def test_deleted_file_is_obsolete_candidate_when_most_files_exist(self):
        self.write("src/b.py", self.MARKER)
        self.write("src/c.py", self.MARKER)
        self.append("linear scan over the cache.", "code-marker (src/gone.py:1)", sprint="01")
        self.append("linear scan over the cache.", "code-marker (src/b.py:1)", sprint="02")
        self.append("linear scan over the cache.", "code-marker (src/c.py:1)", sprint="03")
        self.assertEqual(self.verdicts()["BL-E001-001"]["verdict"], "obsolete-candidate")

    def test_mass_missing_files_suspect_the_project_root(self):
        for i, s in enumerate(("01", "02", "03"), 1):
            self.append(f"thing {i}", f"code-marker (src/missing{i}.py:1)", sprint=s)
        result = self.run_audit()
        self.assertNotIn("obsolete-candidate", {v["verdict"] for v in result["verdicts"]})
        self.assertTrue(any("project-root suspect" in w for w in result["warnings"]))

    def test_a_single_missing_marker_is_obsolete_candidate_not_suspect(self):
        # Below MIN_MARKERS_FOR_MASS_MISSING_GUARD: one deleted file must not be read as
        # a project-root mismatch and suppressed into "needs-review".
        self.append("linear scan over the cache.", "code-marker (src/gone.py:1)")
        result = self.run_audit()
        self.assertEqual(self.verdicts()["BL-E001-001"]["verdict"], "obsolete-candidate")
        self.assertFalse(any("project-root suspect" in w for w in result["warnings"]))

    def test_marker_path_with_a_space_is_recognized(self):
        self.write("src/my file.py", "x = 1\n")
        self.append("linear scan over the cache.", "code-marker (src/my file.py:3)")
        self.assertEqual(self.verdicts()["BL-E001-001"]["verdict"], "fixed-candidate")

    def test_embedded_marker_path_with_a_space_is_recognized(self):
        self.write("src/my file.py", "x = 1\n")
        self.append("debug print", "clean-release (code-marker src/my file.py:9)")
        self.assertEqual(self.verdicts()["BL-E001-001"]["verdict"], "fixed-candidate")


class TestDuplicates(Base):
    def test_same_epic_lower_severity_is_proposed(self):
        self.append("Missing input validation", "qa (Q-1)", sprint="01", severity="High")
        self.append("Missing input validation", "qa (Q-2)", sprint="02", severity="Low")
        v = self.verdicts()["BL-E001-002"]
        self.assertEqual((v["verdict"], v["ref"]), ("duplicate-candidate", "BL-E001-001"))

    def test_cross_epic_is_not_proposed(self):
        self.append("Missing input validation", "qa (Q-1)", epic="001")
        self.append("Missing input validation", "qa (Q-1)", epic="002")
        self.assertNotEqual(self.verdicts()["BL-E002-001"]["verdict"], "duplicate-candidate")

    def test_higher_severity_is_not_proposed(self):
        self.append("Missing input validation", "qa (Q-1)", sprint="01", severity="Low")
        self.append("Missing input validation", "qa (Q-2)", sprint="02", severity="Critical")
        self.assertNotEqual(self.verdicts()["BL-E001-002"]["verdict"], "duplicate-candidate")

    def test_duplicate_of_a_resolved_wontfix(self):
        self.append("Verbose logging", "qa (Q-1)", sprint="01", severity="Medium")
        self.pm("resolve-issue", "--state-root", self.state, "--key", "BL-E001-001",
                "--resolution", "wontfix", "--note", "by design")
        self.append("Verbose logging", "qa (Q-2)", sprint="02", severity="Low")
        v = self.verdicts()["BL-E001-002"]
        self.assertEqual((v["verdict"], v["ref"]), ("duplicate-candidate", "BL-E001-001"))


class TestPointers(Base):
    def test_see_description(self):
        rel = "_impl/epic-001/sprint-01/closure/review-E001-S01-001.md"
        self.write(rel, "F-1: something\n")
        self.append("A finding", "code-review (E001-S01-001)", description=f"See {rel}")
        v = self.verdicts()["BL-E001-001"]
        self.assertEqual(v["verdict"], "needs-review")
        self.assertTrue(v["pointer"].endswith("review-E001-S01-001.md"))

    def test_code_review_source_derives_the_review_file(self):
        self.write("epic-001/sprint-01/closure/review-E001-S01-002.md", "x\n", base=self.arts)
        self.append("A finding", "code-review (E001-S01-002) — unresolved after 3 fix iterations")
        self.assertTrue(self.verdicts()["BL-E001-001"]["pointer"].endswith("review-E001-S01-002.md"))

    def test_phase_id_searches_only_that_phase_report(self):
        self.write("epic-001/sprint-01/closure/adversarial-review.md", "F-3: real one\n", base=self.arts)
        self.write("epic-001/sprint-01/closure/redteam-report.md", "F-3: other phase\n", base=self.arts)
        self.append("A finding", "adversarial (F-3)")
        self.assertIn("adversarial-review.md:1", self.verdicts()["BL-E001-001"]["pointer"])

    def test_ambiguous_phase_id_is_untraceable(self):
        self.write("epic-001/sprint-01/closure/adversarial-review.md", "F-3\nsee F-3\n", base=self.arts)
        self.append("A finding", "adversarial (F-3)")
        v = self.verdicts()["BL-E001-001"]
        self.assertIsNone(v["pointer"])
        self.assertEqual(v["evidence"], "untraceable")

    def test_epic_level_item_points_into_epic_closure(self):
        self.write("epic-001/epic-closure/redteam-report.md", "R-1: auth bypass\n", base=self.arts)
        self.append("Auth bypass", "epic-redteam (R-1)", sprint="")
        self.assertIn("epic-closure/redteam-report.md:1", self.verdicts()["BL-E001-001"]["pointer"])

    def test_unrecognized_source_is_untraceable_not_an_error(self):
        self.append("Odd", "something nobody writes")
        self.assertEqual(self.verdicts()["BL-E001-001"]["evidence"], "untraceable")


class TestLegacySourceShapes(Base):
    """Source shapes a real backlog actually contains, which no regex accepted.

    Measured on a real project (houserules, 517 items): 335 were
    `closure review (E{nnn}-S{nn})` and 29 were a bare story key -- 70% of the backlog --
    and every one resolved to `basis: none` / `evidence: untraceable`. The health check
    reported that as "0 candidates", which reads like a clean bill rather than blindness.
    """

    def test_closure_review_source_derives_the_sprint_review_file(self):
        self.write("epic-001/sprint-02/closure/review-sprint-E001-S02.md",
                   "F-1: something\n", base=self.arts)
        self.append("A finding", "closure review (E001-S02)", sprint="02")
        v = self.verdicts()["BL-E001-001"]
        self.assertTrue(v["pointer"] and v["pointer"].endswith("review-sprint-E001-S02.md"),
                        f"expected the sprint review file, got {v['pointer']!r}")

    def test_closure_review_with_no_such_file_stays_untraceable(self):
        self.append("A finding", "closure review (E001-S02)", sprint="02")
        self.assertIsNone(self.verdicts()["BL-E001-001"]["pointer"])

    def test_bare_story_key_source_resolves_into_that_story_closure_dir(self):
        self.write("epic-001/sprint-01/closure/review-E001-S01-004.md",
                   "the finding\n", base=self.arts)
        self.append("A finding", "E001-S01-004")
        v = self.verdicts()["BL-E001-001"]
        self.assertTrue(v["pointer"] and "E001-S01-004" in v["pointer"],
                        f"expected the story's closure artifact, got {v['pointer']!r}")

    def test_bare_story_key_with_no_artifact_stays_untraceable(self):
        self.append("A finding", "E001-S01-004")
        self.assertIsNone(self.verdicts()["BL-E001-001"]["pointer"])

    def test_story_key_followed_by_free_text_resolves(self):
        """The dominant real shape: a story key with a trailing word. Measured on a real
        backlog, `E###-S##-### development` / `implementation` / `code review` and similar
        are 60+ items; the `$`-anchored form rejected every one on the trailing word."""
        self.write("epic-001/sprint-01/closure/review-E001-S01-004.md",
                   "the finding\n", base=self.arts)
        self.append("A finding", "E001-S01-004 development")
        v = self.verdicts()["BL-E001-001"]
        self.assertTrue(v["pointer"] and "E001-S01-004" in v["pointer"],
                        f"expected the story's closure artifact, got {v['pointer']!r}")

    def test_story_key_with_a_long_trailing_clause_resolves(self):
        self.write("epic-001/sprint-01/closure/review-E001-S01-004.md",
                   "the finding\n", base=self.arts)
        self.append("A finding",
                    "E001-S01-004 development - returned to the orchestrator, not self-filed")
        self.assertTrue(self.verdicts()["BL-E001-001"]["pointer"])

    def test_story_key_in_one_file_BODY_resolves_with_a_line_number(self):
        """Closure artifacts are named after the KIND, not the story: measured on a real
        tree, only 6 of 39 carried a key in the filename, so filename matching reached
        almost nothing. The sibling phase branch has always searched bodies."""
        self.write("epic-001/sprint-01/closure/retrospective.md",
                   "notes\nE001-S01-004 was deferred\nmore\n", base=self.arts)
        self.append("A finding", "E001-S01-004 development")
        v = self.verdicts()["BL-E001-001"]
        self.assertTrue(v["pointer"] and v["pointer"].endswith("retrospective.md:2"),
                        f"expected a body hit with a line number, got {v['pointer']!r}")

    def test_story_key_in_two_file_BODIES_stays_untraceable(self):
        self.write("epic-001/sprint-01/closure/retrospective.md",
                   "E001-S01-004 here\n", base=self.arts)
        self.write("epic-001/sprint-01/closure/redteam.md",
                   "E001-S01-004 also here\n", base=self.arts)
        self.append("A finding", "E001-S01-004 development")
        self.assertIsNone(self.verdicts()["BL-E001-001"]["pointer"])

    def test_a_key_twice_in_ONE_body_is_still_one_hit(self):
        """Ambiguity is across files, not across lines of one file."""
        self.write("epic-001/sprint-01/closure/retrospective.md",
                   "E001-S01-004 first\nE001-S01-004 again\n", base=self.arts)
        self.append("A finding", "E001-S01-004 development")
        self.assertTrue(self.verdicts()["BL-E001-001"]["pointer"])

    def test_a_body_key_inside_a_longer_token_does_not_match(self):
        self.write("epic-001/sprint-01/closure/retrospective.md",
                   "E001-S01-0041 is a different story\n", base=self.arts)
        self.append("A finding", "E001-S01-004 development")
        self.assertIsNone(self.verdicts()["BL-E001-001"]["pointer"])

    def test_a_key_shaped_prefix_inside_a_longer_token_does_not_match(self):

        """`\\b` must not let E001-S01-0041 resolve as E001-S01-004."""
        self.write("epic-001/sprint-01/closure/review-E001-S01-004.md",
                   "the finding\n", base=self.arts)
        self.append("A finding", "E001-S01-0041 development")
        self.assertIsNone(self.verdicts()["BL-E001-001"]["pointer"])

    def test_ambiguous_story_artifacts_stay_untraceable(self):
        """Two artifacts naming the key: the one-hit-or-nothing rule must still refuse."""
        self.write("epic-001/sprint-01/closure/review-E001-S01-004.md", "x\n", base=self.arts)
        self.write("epic-001/sprint-01/closure/redteam-E001-S01-004.md", "x\n", base=self.arts)
        self.append("A finding", "E001-S01-004 development")
        self.assertIsNone(self.verdicts()["BL-E001-001"]["pointer"])

    def test_a_source_matching_nothing_is_still_untraceable(self):

        self.append("A finding", "hand-written note with no shape")
        self.assertIsNone(self.verdicts()["BL-E001-001"]["pointer"])


class TestStructuredSource(Base):
    """An item carrying source_phase/source_ref needs no parsing at all."""

    def _append_structured(self, phase, ref, epic="001", sprint="01"):
        return self.pm("append-issue", "--state-root", self.state, "--epic", epic,
                       "--sprint", sprint, "--title", "T", "--severity", "Low",
                       "--source-phase", phase, "--source-ref", ref)

    def test_structured_item_resolves_without_the_regex_chain(self):
        self.write("epic-001/sprint-01/closure/redteam-report.md",
                   "notes\nF-3 the finding\n", base=self.arts)
        self._append_structured("epic-redteam", "F-3")
        v = self.verdicts()["BL-E001-001"]
        self.assertTrue(v["pointer"] and v["pointer"].endswith("redteam-report.md:2"),
                        f"expected a body hit, got {v['pointer']!r}")

    def test_a_structured_item_bypasses_the_parsed_branches(self):
        """Proves the structured branch is used, not that the answer happens to be right:
        the stored `source` string is deliberately unparseable by every regex."""
        self.write("epic-001/sprint-01/closure/redteam-report.md", "F-3 here\n", base=self.arts)
        self._append_structured("epic-redteam", "F-3")
        import ruamel.yaml
        p = os.path.join(self.state, "issues.yaml")
        y = ruamel.yaml.YAML()
        with open(p, encoding="utf-8") as fh:
            data = y.load(fh)
        data["backlog"][0]["source"] = "!!! nothing can parse this !!!"
        with open(p, "w", encoding="utf-8") as fh:
            y.dump(data, fh)
        self.assertTrue(self.verdicts()["BL-E001-001"]["pointer"],
                        "structured fields must resolve even when `source` is garbage")

    def test_a_structured_ref_in_two_files_stays_untraceable(self):
        self.write("epic-001/sprint-01/closure/a.md", "F-3\n", base=self.arts)
        self.write("epic-001/sprint-01/closure/b.md", "F-3\n", base=self.arts)
        self._append_structured("epic-redteam", "F-3")
        self.assertIsNone(self.verdicts()["BL-E001-001"]["pointer"])

    def test_a_structured_ref_matching_nothing_is_untraceable(self):
        self.write("epic-001/sprint-01/closure/a.md", "nothing here\n", base=self.arts)
        self._append_structured("epic-redteam", "F-9")
        self.assertIsNone(self.verdicts()["BL-E001-001"]["pointer"])

    def test_a_legacy_item_still_uses_the_regex_chain(self):
        self.write("epic-001/sprint-01/closure/review-E001-S01-004.md", "x\n", base=self.arts)
        self.append("A finding", "E001-S01-004 development")
        self.assertTrue(self.verdicts()["BL-E001-001"]["pointer"])


class TestCli(Base):


    def test_json_through_a_subprocess(self):
        self.append("A finding", "qa (Q-1)")
        p = subprocess.run([sys.executable, SCRIPT, "--pm-status", PM, "--state-root", self.state,
                            "--artifacts-root", self.arts, "--project-root", self.proj,
                            "--format", "json"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["verdicts"][0]["key"], "BL-E001-001")

    def test_unlistable_state_exits_2(self):
        with open(os.path.join(self.state, "issues.yaml"), "w", encoding="utf-8") as fh:
            fh.write("backlog: oops\n")
        err = io.StringIO()
        with redirect_stderr(err):
            code = ab.main(["--pm-status", PM, "--state-root", self.state,
                            "--artifacts-root", self.arts, "--project-root", self.proj])
        self.assertEqual(code, 2)
        self.assertIn("issues.yaml has a malformed 'backlog' field", err.getvalue())

    def test_unlistable_resolved_list_exits_2(self):
        # the same refusal for the resolved file: list-issues --all reads both lists
        self.append("A finding", "qa (Q-1)")
        with open(os.path.join(self.state, "issues-resolved.yaml"), "w", encoding="utf-8") as fh:
            fh.write("resolved: oops\n")
        err = io.StringIO()
        with redirect_stderr(err):
            code = ab.main(["--pm-status", PM, "--state-root", self.state,
                            "--artifacts-root", self.arts, "--project-root", self.proj])
        self.assertEqual(code, 2)
        self.assertIn("issues-resolved.yaml has a malformed 'resolved' field", err.getvalue())


class TestSpecItemsSkipped(Base):
    """spec-change/spec-proposal items are confirmed or rejected in triage's spec pass; the
    mechanical audit must not propose resolving them as obsolete or needs-review."""

    def test_spec_items_get_no_verdict(self):
        self.pm("append-issue", "--state-root", self.state, "--epic", "001", "--sprint", "",
                "--title", "Spec change: order API", "--source", "spec-sync (AD-1)",
                "--severity", "Medium", "--kind", "spec-change", "--ref", "3f9c2a1",
                "--description", "Confirm or reject: /l3io-doctor triage")
        self.append("A defect", "code-review (E001-S01-001)")
        v = self.verdicts()
        self.assertNotIn("BL-E001-001", v)
        self.assertIn("BL-E001-002", v)


if __name__ == "__main__":
    unittest.main(verbosity=2)
