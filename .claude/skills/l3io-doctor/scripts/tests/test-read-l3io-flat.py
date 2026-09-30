#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""Tests for read-l3io-flat.py — run with: uv run test-read-l3io-flat.py"""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "read-l3io-flat.py")
FIXTURE = Path(HERE) / "fixtures" / "l3io-flat" / "sprint-status.yaml"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(HERE), filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rd = _load("read_l3io_flat", "read-l3io-flat.py")
sr = _load("state_record", "state-record.py")


class TestReadL3ioFlat(unittest.TestCase):
    def setUp(self):
        self.recs = rd.read(FIXTURE)

    def _by_kind(self, kind):
        return [r for r in self.recs if r["kind"] == kind]

    def _tmp(self, text):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "sprint-status.yaml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_counts_match_the_fixture(self):
        self.assertEqual(len(self._by_kind("epic")), 2)
        self.assertEqual(len(self._by_kind("sprint")), 2)
        self.assertEqual(len(self._by_kind("story")), 3)

    def test_keys_are_exact(self):
        self.assertEqual({r["key"] for r in self._by_kind("epic")}, {"E001", "E002"})
        self.assertEqual({r["key"] for r in self._by_kind("sprint")},
                         {"E001-S01", "E001-S02"})
        self.assertEqual({r["key"] for r in self._by_kind("story")},
                         {"E001-S01-001", "E001-S01-002", "E001-S02-001"})

    def test_statuses_are_carried_through(self):
        got = {r["key"]: r["status"] for r in self.recs}
        self.assertEqual(got["E001"], "in-progress")
        self.assertEqual(got["E002"], "backlog")
        self.assertEqual(got["E001-S01"], "done")
        self.assertEqual(got["E001-S01-002"], "review")

    def test_every_record_validates(self):
        for r in self.recs:
            self.assertEqual(sr.validate(r), [], f"{r['key']}: {sr.validate(r)}")

    def test_no_record_is_marked_inferred(self):
        for r in self.recs:
            self.assertNotIn("origin", r)

    def test_source_names_the_file(self):
        for r in self.recs:
            self.assertIn("sprint-status.yaml", r["source"])

    def test_epic_with_no_sprints_still_yields_its_epic(self):
        self.assertIn("E002", {r["key"] for r in self._by_kind("epic")})

    def test_a_bmad_schema_file_yields_ZERO_records(self):
        """The live defect, as a test. This reader must not invent nodes from
        BMad's development_status: mapping -- and must not refuse either. It
        reports emptiness; the engine's gate is what blocks."""
        p = self._tmp("development_status:\n  epic-1: backlog\n")
        self.assertEqual(rd.read(p), [])

    def test_empty_file_yields_zero_records(self):
        self.assertEqual(rd.read(self._tmp("")), [])

    def test_unparseable_file_yields_zero_records(self):
        self.assertEqual(rd.read(self._tmp("a: [1,\n")), [])

    def test_an_epic_without_a_key_is_skipped(self):
        p = self._tmp("epics:\n  - title: nameless\n    status: backlog\n")
        self.assertEqual(rd.read(p), [])

    def test_epic_goal_is_captured_as_an_extra(self):
        """Fields import-node does not accept typed must ride through in `extras` so
        the engine can dispatch them via set-field (or WARN)."""
        by_key = {r["key"]: r for r in self.recs}
        self.assertEqual(
            by_key["E001"].get("extras", {}).get("goal"),
            "All users can sign in with password + one federated provider.")

    def test_story_classification_is_a_top_level_field_not_an_extra(self):
        """import-node has a typed --classification flag, so the reader promotes
        classification to a top-level record field rather than burying it in extras."""
        by_key = {r["key"]: r for r in self.recs}
        s = by_key["E001-S01-001"]
        self.assertEqual(s.get("classification"), "feature")
        self.assertNotIn("classification", s.get("extras", {}))

    def test_story_extras_capture_depends_on_and_superseded_by(self):
        by_key = {r["key"]: r for r in self.recs}
        self.assertEqual(by_key["E001-S01-001"]["extras"]["depends_on"], ["E001-S01-002"])
        self.assertEqual(by_key["E001-S01-002"]["extras"]["superseded_by"], "E001-S01-999")

    def test_story_estimate_and_actual_blocks_are_captured(self):
        by_key = {r["key"]: r for r in self.recs}
        s = by_key["E001-S02-001"]
        self.assertEqual(s["extras"]["estimate"], {"man_hours": 5, "tokens_k": 40})
        self.assertEqual(s["extras"]["actual"], {"man_hours": 6})


if __name__ == "__main__":
    unittest.main()
