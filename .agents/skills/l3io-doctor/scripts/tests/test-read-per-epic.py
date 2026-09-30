#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""Tests for read-per-epic.py — run with: uv run test-read-per-epic.py"""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = Path(HERE) / "fixtures" / "per-epic" / "_bmad" / "state"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(HERE), filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rd = _load("read_per_epic", "read-per-epic.py")


class TestReadPerEpic(unittest.TestCase):
    def setUp(self):
        self.recs = rd.read(FIXTURE)

    def _by_kind(self, k):
        return [r for r in self.recs if r["kind"] == k]

    def _tmpdir(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_both_epic_files_are_read(self):
        self.assertEqual({r["key"] for r in self._by_kind("epic")}, {"E001", "E002"})

    def test_nested_children_are_emitted(self):
        self.assertEqual({r["key"] for r in self._by_kind("sprint")}, {"E001-S01"})
        self.assertEqual({r["key"] for r in self._by_kind("story")}, {"E001-S01-001"})

    def test_statuses_carry_through(self):
        got = {r["key"]: r["status"] for r in self.recs}
        self.assertEqual(got["E001"], "in-progress")
        self.assertEqual(got["E001-S01"], "done")
        self.assertEqual(got["E002"], "backlog")

    def test_source_names_the_epic_file(self):
        got = {r["key"]: r["source"] for r in self.recs}
        self.assertIn("epic-001.yaml", got["E001"])
        self.assertIn("epic-002.yaml", got["E002"])

    def test_an_epic_shell_and_its_full_epic_merge_to_one(self):
        """The dedupe defect, as a test. Two files naming E001 -- a shell and the
        real one -- must produce ONE record, not two that land in two folders."""
        d = self._tmpdir()
        (d / "epic-001.yaml").write_text(
            "key: 'E001'\ntitle: ''\nstatus: backlog\n", encoding="utf-8")
        (d / "epic-001-full.yaml").write_text(
            "key: 'E001'\ntitle: Real\nstatus: in-progress\n", encoding="utf-8")
        recs = [r for r in rd.read(d) if r["kind"] == "epic"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["title"], "Real")

    def test_missing_directory_yields_zero_records(self):
        self.assertEqual(rd.read(Path("/nonexistent/state")), [])

    def test_unparseable_file_is_skipped_not_fatal(self):
        d = self._tmpdir()
        (d / "epic-001.yaml").write_text("key: 'E001'\nstatus: backlog\n", encoding="utf-8")
        (d / "epic-002.yaml").write_text("a: [1,\n", encoding="utf-8")
        self.assertEqual({r["key"] for r in rd.read(d)}, {"E001"})

    def test_a_file_without_a_key_is_skipped(self):
        d = self._tmpdir()
        (d / "epic-001.yaml").write_text("title: nameless\nstatus: backlog\n",
                                         encoding="utf-8")
        self.assertEqual(rd.read(d), [])

    def test_files_are_read_in_sorted_order(self):
        d = self._tmpdir()
        (d / "epic-002.yaml").write_text("key: 'E002'\nstatus: backlog\n", encoding="utf-8")
        (d / "epic-001.yaml").write_text("key: 'E001'\nstatus: backlog\n", encoding="utf-8")
        self.assertEqual([r["key"] for r in rd.read(d)], ["E001", "E002"])


if __name__ == "__main__":
    unittest.main()
