#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""Tests for read-bmad-flat.py — run with: uv run test-read-bmad-flat.py"""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = Path(HERE) / "fixtures" / "bmad-flat" / "sprint-status.yaml"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(HERE), filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rd = _load("read_bmad_flat", "read-bmad-flat.py")


class TestParseId(unittest.TestCase):
    def test_epic_id(self):
        self.assertEqual(rd.parse_id("epic-1"), ("epic", "E001"))

    def test_epic_id_zero_pads(self):
        self.assertEqual(rd.parse_id("epic-12"), ("epic", "E012"))

    def test_story_id(self):
        self.assertEqual(rd.parse_id("1-1-user-authentication"),
                         ("story", "E001-S01-001"))

    def test_story_id_second_number_is_the_story_number(self):
        self.assertEqual(rd.parse_id("2-7-report-export"), ("story", "E002-S01-007"))

    def test_unrecognised_id_is_none(self):
        self.assertIsNone(rd.parse_id("sprint-3"))
        self.assertIsNone(rd.parse_id("just-a-slug"))
        self.assertIsNone(rd.parse_id(""))


class TestReadBmadFlat(unittest.TestCase):
    def setUp(self):
        self.recs = rd.read(FIXTURE)

    def _by_kind(self, k):
        return [r for r in self.recs if r["kind"] == k]

    def _tmp(self, text):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "sprint-status.yaml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_counts(self):
        self.assertEqual(len(self._by_kind("epic")), 2)
        self.assertEqual(len(self._by_kind("story")), 3)

    def test_no_sprints_are_emitted_here(self):
        self.assertEqual(self._by_kind("sprint"), [])

    def test_keys(self):
        self.assertEqual({r["key"] for r in self._by_kind("epic")}, {"E001", "E002"})
        self.assertEqual({r["key"] for r in self._by_kind("story")},
                         {"E001-S01-001", "E001-S01-002", "E002-S01-001"})

    def test_statuses_carry_through(self):
        got = {r["key"]: r["status"] for r in self.recs}
        self.assertEqual(got["E001"], "in-progress")
        self.assertEqual(got["E001-S01-001"], "done")
        self.assertEqual(got["E002"], "backlog")

    def test_title_comes_from_the_slug(self):
        got = {r["key"]: r["title"] for r in self.recs}
        self.assertEqual(got["E001-S01-001"], "User authentication")

    def test_an_l3io_schema_file_yields_ZERO_records(self):
        p = self._tmp("epics:\n  - key: 'E001'\n    status: backlog\n")
        self.assertEqual(rd.read(p), [])

    def test_unknown_status_value_is_dropped_not_guessed(self):
        self.assertEqual(rd.read(self._tmp("development_status:\n  epic-1: wat\n")), [])

    def test_a_review_status_maps_to_in_progress_for_an_epic(self):
        recs = rd.read(self._tmp("development_status:\n  epic-1: review\n"))
        self.assertEqual(recs[0]["status"], "in-progress")

    def test_a_review_status_stays_review_for_a_story(self):
        recs = rd.read(self._tmp("development_status:\n  1-1-thing: review\n"))
        self.assertEqual(recs[0]["status"], "review")


if __name__ == "__main__":
    unittest.main()
