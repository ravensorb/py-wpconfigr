#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""Tests for read-split.py — run with: uv run test-read-split.py"""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = Path(HERE) / "fixtures" / "split"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(HERE), filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rd = _load("read_split", "read-split.py")


class TestReadSplit(unittest.TestCase):
    def setUp(self):
        self.recs = rd.read(FIXTURE)

    def _by_kind(self, k):
        return [r for r in self.recs if r["kind"] == k]

    def _tmpdir(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_all_three_files_contribute(self):
        self.assertEqual({r["key"] for r in self._by_kind("epic")},
                         {"E001", "E002", "E003"})

    def test_children_from_active_and_archived(self):
        self.assertEqual({r["key"] for r in self._by_kind("sprint")},
                         {"E001-S01", "E003-S01"})
        self.assertEqual({r["key"] for r in self._by_kind("story")},
                         {"E001-S01-001", "E003-S01-001"})

    def test_statuses_carry_through(self):
        got = {r["key"]: r["status"] for r in self.recs}
        self.assertEqual(got["E001"], "in-progress")
        self.assertEqual(got["E002"], "backlog")
        self.assertEqual(got["E003"], "done")

    def test_source_distinguishes_the_three_files(self):
        got = {r["key"]: r["source"] for r in self.recs}
        self.assertIn("sprint-status.yaml", got["E001"])
        self.assertIn("sprint-status-backlog.yaml", got["E002"])
        self.assertIn("sprint-status-archived.yaml", got["E003"])

    def test_absent_optional_files_are_fine(self):
        d = self._tmpdir()
        (d / "sprint-status.yaml").write_text(
            "epics:\n  - key: 'E001'\n    title: A\n    status: backlog\n",
            encoding="utf-8")
        self.assertEqual({r["key"] for r in rd.read(d)}, {"E001"})

    def test_a_key_in_two_files_yields_one_record(self):
        d = self._tmpdir()
        (d / "sprint-status.yaml").write_text(
            "epics:\n  - key: 'E001'\n    title: Real\n    status: in-progress\n",
            encoding="utf-8")
        (d / "sprint-status-backlog.yaml").write_text(
            "epics:\n  - key: 'E001'\n    title: ''\n    status: backlog\n",
            encoding="utf-8")
        recs = [r for r in rd.read(d) if r["kind"] == "epic"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["title"], "Real")

    def test_empty_directory_yields_zero_records(self):
        self.assertEqual(rd.read(self._tmpdir()), [])

    def test_missing_directory_yields_zero_records(self):
        self.assertEqual(rd.read(Path("/nonexistent/artifacts")), [])

    def test_split_files_constant_is_the_three_names(self):
        self.assertEqual(
            rd.SPLIT_FILES,
            ("sprint-status.yaml", "sprint-status-backlog.yaml",
             "sprint-status-archived.yaml"))


if __name__ == "__main__":
    unittest.main()
