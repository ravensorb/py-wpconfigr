#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
Tests for detect-layout.py. Run with:
  uv run skills/l3io-doctor/scripts/tests/test-detect-layout.py

Every case drives the real CLI through subprocess -- never the detect() function directly --
so the test exercises the same exit code and stdout a health-check run would see.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import importlib.util
_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "detect_layout", os.path.join(os.path.dirname(_HERE), "detect-layout.py"))
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


# -- temp-dir leak guard ---------------------------------------------------------------- #
# setUpModule points tempfile.tempdir (this test process) AND the TMPDIR environment variable
# (inherited by every subprocess it spawns) at one private run directory; tearDownModule fails
# the run if anything is left in it, then removes it and restores both to their prior values.
# The one name it ignores is `uv-*.lock`, which `uv run` leaves in TMPDIR by design.
_RUN_TMP = None
_PREV_TMPDIR = None             # the TMPDIR environment variable, or None
_PREV_TEMPFILE_TEMPDIR = None   # tempfile.tempdir as it was before setUpModule


def setUpModule():
    global _RUN_TMP, _PREV_TMPDIR, _PREV_TEMPFILE_TEMPDIR
    _PREV_TEMPFILE_TEMPDIR = tempfile.tempdir
    _RUN_TMP = tempfile.mkdtemp(prefix="test-detect-layout-")
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
SCRIPT = os.path.join(os.path.dirname(HERE), "detect-layout.py")


class TestLayoutCollision(unittest.TestCase):
    def detect(self, **files):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        if files.get("flat"):
            Path(d, "sprint-status.yaml").touch()
        if files.get("legacy"):
            Path(d, "sprint-status.yaml.legacy").touch()
        if files.get("sharded"):
            Path(d, "state").mkdir()
        r = subprocess.run(["uv", "run", str(SCRIPT), "--artifacts", d],
                            capture_output=True, text=True)
        return r.returncode, r.stdout, d

    def test_both_layouts_is_a_collision(self):
        code, out, d = self.detect(flat=True, sharded=True)
        self.assertEqual(code, 1)
        # Assert the documented message shape verbatim -- both real paths present, not just
        # the "layout-collision" label -- so a mutation that drops the paths (leaving the
        # label intact) is caught rather than surviving on a substring match.
        expected = f"layout-collision: both {Path(d, 'sprint-status.yaml')} and {Path(d, 'state')}/ exist\n"
        self.assertEqual(out, expected)

    def test_post_migrate_legacy_rename_is_clean(self):
        # The load-bearing case: migrate-state renames the flat file to .legacy. If this
        # still reported a collision, the finding would never clear after the documented fix
        # and would become permanent noise.
        code, out, _ = self.detect(legacy=True, sharded=True)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_sharded_only_is_clean(self):
        code, out, _ = self.detect(sharded=True)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_flat_only_is_not_a_collision(self):
        code, out, _ = self.detect(flat=True)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_neither_present_is_clean(self):
        code, out, _ = self.detect()
        self.assertEqual(code, 0)
        self.assertEqual(out, "")


class TestClassifyFlat(unittest.TestCase):
    def _write(self, text):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "sprint-status.yaml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_bmad_mapping_is_bmad(self):
        p = self._write(
            "development_status:\n"
            "  epic-1: backlog\n"
            "  1-1-user-authentication: done\n"
        )
        self.assertEqual(mod.classify_flat(p), "bmad")

    def test_l3io_list_is_l3io(self):
        p = self._write("epics:\n  - key: 'E001'\n    status: backlog\n")
        self.assertEqual(mod.classify_flat(p), "l3io")

    def test_empty_file_is_empty(self):
        self.assertEqual(mod.classify_flat(self._write("")), "empty")

    def test_unparseable_is_unreadable(self):
        self.assertEqual(mod.classify_flat(self._write("a: [1,\n")), "unreadable")

    def test_neither_key_is_unreadable(self):
        self.assertEqual(mod.classify_flat(self._write("other: 1\n")), "unreadable")

    def test_classify_cli_exits_3_on_bmad(self):
        p = self._write("development_status:\n  epic-1: backlog\n")
        code = mod.main(["--artifacts", str(p.parent), "--classify"])
        self.assertEqual(code, 3)



class TestReachability(unittest.TestCase):
    """The two states that look identical to a caller checking only the configured path:
    a tree orphaned by a repointed implementation_artifacts, and a tree git ignores. Both
    turn "nothing to report" into a wrong answer rather than a refusal."""

    def _repo(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        return d

    def _state(self, root, rel):
        p = root / rel / "state" / "active" / "epic-001"
        p.mkdir(parents=True)
        (p / "epic.yaml").write_text("key: 'E001'\nstatus: in-progress\n", encoding="utf-8")
        return root / rel

    def test_configured_tree_alone_is_clean(self):
        root = self._repo()
        art = self._state(root, "arts")
        r = mod.reachability(art, root)
        self.assertEqual(r["orphaned"], [])
        self.assertFalse(r["untracked"])
        self.assertTrue(r["configured_exists"])

    def test_a_tree_outside_the_configured_path_is_orphaned(self):
        root = self._repo()
        self._state(root, "old-arts")
        (root / "new-arts").mkdir()
        r = mod.reachability(root / "new-arts", root)
        self.assertEqual(len(r["orphaned"]), 1, r)
        self.assertIn("old-arts", r["orphaned"][0])

    def test_a_gitignored_configured_tree_is_untracked(self):
        root = self._repo()
        art = self._state(root, "arts")
        (root / ".gitignore").write_text("arts/state/\n", encoding="utf-8")
        r = mod.reachability(art, root)
        self.assertTrue(r["untracked"], r)

    def test_no_state_anywhere_is_clean_not_a_finding(self):
        root = self._repo()
        (root / "arts").mkdir()
        r = mod.reachability(root / "arts", root)
        self.assertEqual(r["orphaned"], [])
        self.assertFalse(r["untracked"])
        self.assertFalse(r["configured_exists"])

    def test_outside_a_git_repo_it_reports_rather_than_failing(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "arts").mkdir()
        r = mod.reachability(d / "arts", d)
        self.assertFalse(r["git_available"])
        self.assertFalse(r["untracked"])

    def test_cli_exits_4_on_a_finding_and_0_when_clean(self):
        root = self._repo()
        self._state(root, "old-arts")
        (root / "new-arts").mkdir()
        self.assertEqual(mod.main(["--artifacts", str(root / "new-arts"),
                                   "--project-root", str(root), "--reachability"]), 4)
        art = self._state(root, "ok-arts")
        # a repo with ONLY the configured tree
        root2 = self._repo()
        art2 = self._state(root2, "arts")
        self.assertEqual(mod.main(["--artifacts", str(art2),
                                   "--project-root", str(root2), "--reachability"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
