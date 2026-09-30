#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""Tests for read-artifacts.py — run with: uv run test-read-artifacts.py"""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = Path(HERE) / "fixtures" / "artifacts"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(HERE), filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rd = _load("read_artifacts", "read-artifacts.py")


class TestParseFrontmatter(unittest.TestCase):
    def test_reads_a_yaml_block(self):
        got = rd.parse_frontmatter("---\nkey: 'A'\nstatus: done\n---\n\n# Body\n")
        self.assertEqual(got, {"key": "A", "status": "done"})

    def test_no_frontmatter_is_empty(self):
        self.assertEqual(rd.parse_frontmatter("# Just a heading\n"), {})

    def test_unterminated_block_is_empty(self):
        self.assertEqual(rd.parse_frontmatter("---\nkey: 'A'\n"), {})

    def test_malformed_yaml_is_empty(self):
        self.assertEqual(rd.parse_frontmatter("---\na: [1,\n---\n"), {})


class TestReadArtifacts(unittest.TestCase):
    def setUp(self):
        self.recs = rd.read(FIXTURE)

    def _by_kind(self, k):
        return [r for r in self.recs if r["kind"] == k]

    def _tmpdir(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_story_records_come_from_frontmatter(self):
        self.assertEqual({r["key"] for r in self._by_kind("story")},
                         {"E001-S01-001", "E001-S01-002", "E001-S02-001"})
        got = {r["key"]: r["status"] for r in self._by_kind("story")}
        self.assertEqual(got["E001-S01-001"], "done")
        self.assertEqual(got["E001-S01-002"], "review")

    def test_sprints_are_inferred_from_the_directory_structure(self):
        self.assertEqual({r["key"] for r in self._by_kind("sprint")},
                         {"E001-S01", "E001-S02"})

    def test_the_epic_is_inferred(self):
        self.assertEqual({r["key"] for r in self._by_kind("epic")}, {"E001"})

    def test_inferred_nodes_carry_origin_and_a_note(self):
        for r in self._by_kind("sprint") + self._by_kind("epic"):
            self.assertEqual(r["origin"], "inferred")
            self.assertTrue(r["origin_note"].strip(), r["key"])

    def test_story_records_are_NOT_marked_inferred(self):
        for r in self._by_kind("story"):
            self.assertNotIn("origin", r)

    def test_sprint_status_is_derived_from_its_stories(self):
        got = {r["key"]: r["status"] for r in self._by_kind("sprint")}
        # S01 has done + review -> started, not finished
        self.assertEqual(got["E001-S01"], "in-progress")
        # S02 has only ready-for-dev -> nothing started
        self.assertEqual(got["E001-S02"], "backlog")

    def test_epic_status_is_derived_from_its_sprints(self):
        got = {r["key"]: r["status"] for r in self._by_kind("epic")}
        self.assertEqual(got["E001"], "in-progress")

    def test_all_done_stories_make_the_sprint_and_epic_done(self):
        d = self._tmpdir()
        sd = d / "epic-003" / "sprint-01" / "stories"
        sd.mkdir(parents=True)
        (sd / "E003-S01-001.md").write_text(
            "---\nkey: 'E003-S01-001'\ntitle: T\nstatus: done\n---\n", encoding="utf-8")
        got = {r["key"]: r["status"] for r in rd.read(d)}
        self.assertEqual(got["E003-S01"], "done")
        self.assertEqual(got["E003"], "done")

    def test_a_story_without_frontmatter_is_skipped(self):
        d = self._tmpdir()
        sd = d / "epic-004" / "sprint-01" / "stories"
        sd.mkdir(parents=True)
        (sd / "E004-S01-001.md").write_text("# No frontmatter here\n", encoding="utf-8")
        self.assertEqual(rd.read(d), [])

    def test_a_story_with_an_invalid_status_is_skipped(self):
        d = self._tmpdir()
        sd = d / "epic-005" / "sprint-01" / "stories"
        sd.mkdir(parents=True)
        (sd / "E005-S01-001.md").write_text(
            "---\nkey: 'E005-S01-001'\nstatus: wat\n---\n", encoding="utf-8")
        self.assertEqual(rd.read(d), [])

    def test_empty_tree_yields_zero_records(self):
        self.assertEqual(rd.read(self._tmpdir()), [])

    def test_missing_directory_yields_zero_records(self):
        self.assertEqual(rd.read(Path("/nonexistent/artifacts")), [])

    def test_parents_precede_their_children(self):
        kinds = [r["kind"] for r in self.recs]
        self.assertEqual(kinds.index("epic"), 0)
        self.assertLess(kinds.index("sprint"), kinds.index("story"))


class TestReadArtifactsAdditive(unittest.TestCase):
    """The additive-bootstrap case: story .md files coexist with an existing sharded
    state tree. The reader must skip already-tracked stories, and only surface
    inferred sprints/epics for the keys the state tree does not already carry.

    Without this scoping, a plan on a partial-state project would list every story
    -- including the tracked ones -- and verify_against_plan would fail on any drift
    between the existing status and the inferred one, blocking a bootstrap that
    ought to be additive."""

    def _tmpdir(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def _seed_state(self, root: Path, *keys):
        """Write empty state files at the given (bucket, epic_key[, sprint_key[, story_key]])
        tuples so the reader sees them as already-tracked."""
        for entry in keys:
            bucket, epic_key = entry[0], entry[1]
            edir = root / bucket / f"epic-{int(epic_key[1:]):03d}"
            edir.mkdir(parents=True, exist_ok=True)
            (edir / "epic.yaml").write_text("key: 'E001'\n", encoding="utf-8")
            if len(entry) >= 3:
                sprint_key = entry[2]
                snum = int(sprint_key.split("-S")[1])
                sdir = edir / f"sprint-{snum:02d}"
                sdir.mkdir(parents=True, exist_ok=True)
                (sdir / "sprint.yaml").write_text(f"key: '{sprint_key}'\n",
                                                  encoding="utf-8")
                if len(entry) >= 4:
                    story_key = entry[3]
                    (sdir / f"{story_key}.yaml").write_text(
                        f"key: '{story_key}'\n", encoding="utf-8")

    def test_no_state_root_emits_every_story(self):
        """Baseline: without --state-root, the reader emits everything (unchanged)."""
        self.assertEqual(len(rd.read(FIXTURE)), 6)   # 1 epic + 2 sprints + 3 stories

    def test_state_root_pointing_at_empty_state_emits_every_story(self):
        empty_state = self._tmpdir()
        (empty_state / "active").mkdir()
        self.assertEqual(len(rd.read(FIXTURE, empty_state)), 6)

    def test_a_tracked_story_is_skipped(self):
        state = self._tmpdir()
        self._seed_state(state, ("active", "E001", "E001-S01", "E001-S01-001"))
        recs = rd.read(FIXTURE, state)
        story_keys = {r["key"] for r in recs if r["kind"] == "story"}
        self.assertNotIn("E001-S01-001", story_keys)
        self.assertIn("E001-S01-002", story_keys)      # not yet tracked, still present

    def test_a_tracked_sprint_suppresses_its_inferred_sprint_record(self):
        """When the state has a sprint node, the reader must not emit an
        inferred one alongside -- the existing state's status is the truth."""
        state = self._tmpdir()
        self._seed_state(state, ("active", "E001", "E001-S01"))
        recs = rd.read(FIXTURE, state)
        sprint_keys = {r["key"] for r in recs if r["kind"] == "sprint"}
        self.assertNotIn("E001-S01", sprint_keys)
        self.assertIn("E001-S02", sprint_keys)         # not tracked yet, still inferred

    def test_a_tracked_epic_suppresses_its_inferred_epic_record(self):
        state = self._tmpdir()
        self._seed_state(state, ("active", "E001"))
        recs = rd.read(FIXTURE, state)
        epic_keys = {r["key"] for r in recs if r["kind"] == "epic"}
        self.assertEqual(epic_keys, set())

    def test_fully_tracked_project_emits_zero_records(self):
        """If every story in the artifact tree has a state node, the reader
        emits nothing -- caller says 'nothing to bootstrap' and stops."""
        state = self._tmpdir()
        self._seed_state(state,
                         ("active", "E001", "E001-S01", "E001-S01-001"),
                         ("active", "E001", "E001-S01", "E001-S01-002"),
                         ("active", "E001", "E001-S02", "E001-S02-001"))
        self.assertEqual(rd.read(FIXTURE, state), [])

    def test_state_root_scans_every_status_bucket(self):
        """A story tracked under archived/ is just as skipped as one under active/."""
        state = self._tmpdir()
        self._seed_state(state, ("archived", "E001", "E001-S01", "E001-S01-001"))
        story_keys = {r["key"] for r in rd.read(FIXTURE, state) if r["kind"] == "story"}
        self.assertNotIn("E001-S01-001", story_keys)


if __name__ == "__main__":
    unittest.main()
