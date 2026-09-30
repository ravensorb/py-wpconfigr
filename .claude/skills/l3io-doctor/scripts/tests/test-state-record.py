#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# ///
"""Tests for state-record.py — run with: uv run test-state-record.py"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "state-record.py")
spec = importlib.util.spec_from_file_location("state_record", SCRIPT)
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)


class TestMakeRecord(unittest.TestCase):
    def test_minimal_record_is_valid(self):
        r = sr.make_record("epic", "E001", "backlog", "First epic", "sprint-status.yaml:3")
        self.assertEqual(sr.validate(r), [])
        self.assertEqual(r["kind"], "epic")
        self.assertEqual(r["key"], "E001")

    def test_origin_absent_by_default(self):
        r = sr.make_record("epic", "E001", "backlog", "t", "s")
        self.assertNotIn("origin", r)

    def test_origin_recorded_when_given(self):
        r = sr.make_record("sprint", "E001-S01", "done", "t", "s",
                           origin="inferred", origin_note="from status transitions")
        self.assertEqual(r["origin"], "inferred")
        self.assertEqual(r["origin_note"], "from status transitions")


class TestValidate(unittest.TestCase):
    def test_bad_kind_reported(self):
        r = sr.make_record("saga", "X", "backlog", "t", "s")
        self.assertIn("unknown kind 'saga'", sr.validate(r))

    def test_bad_status_for_kind_reported(self):
        r = sr.make_record("epic", "E001", "ready-for-dev", "t", "s")
        problems = sr.validate(r)
        self.assertTrue(any("invalid epic status" in p for p in problems), problems)

    def test_story_status_ready_for_dev_is_valid(self):
        r = sr.make_record("story", "E001-S01-001", "ready-for-dev", "t", "s")
        self.assertEqual(sr.validate(r), [])

    def test_empty_key_reported(self):
        r = sr.make_record("epic", "", "backlog", "t", "s")
        self.assertIn("key is empty", sr.validate(r))

    def test_empty_source_reported(self):
        r = sr.make_record("epic", "E001", "backlog", "t", "")
        self.assertIn("source is empty", sr.validate(r))


class TestDedupe(unittest.TestCase):
    def test_shell_and_full_epic_merge_to_one(self):
        shell = sr.make_record("epic", "E001", "backlog", "", "a.yaml:1")
        full = sr.make_record("epic", "E001", "in-progress", "Real title", "b.yaml:9")
        out = sr.dedupe([shell, full])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Real title")
        self.assertEqual(out[0]["status"], "in-progress")

    def test_richer_record_wins_regardless_of_order(self):
        shell = sr.make_record("epic", "E001", "backlog", "", "a.yaml:1")
        full = sr.make_record("epic", "E001", "in-progress", "Real title", "b.yaml:9")
        self.assertEqual(sr.dedupe([full, shell])[0]["title"], "Real title")

    def test_distinct_keys_are_untouched(self):
        a = sr.make_record("epic", "E001", "backlog", "A", "x:1")
        b = sr.make_record("epic", "E002", "backlog", "B", "x:2")
        self.assertEqual(len(sr.dedupe([a, b])), 2)

    def test_same_key_different_kind_is_not_merged(self):
        a = sr.make_record("epic", "E001", "backlog", "A", "x:1")
        b = sr.make_record("sprint", "E001", "backlog", "B", "x:2")
        self.assertEqual(len(sr.dedupe([a, b])), 2)

    def test_first_seen_order_is_preserved(self):
        a = sr.make_record("epic", "E002", "backlog", "B", "x:2")
        b = sr.make_record("epic", "E001", "backlog", "A", "x:1")
        self.assertEqual([r["key"] for r in sr.dedupe([a, b])], ["E002", "E001"])


class TestClassification(unittest.TestCase):
    def test_classification_absent_by_default(self):
        r = sr.make_record("story", "E001-S01-001", "done", "T", "x:1")
        self.assertNotIn("classification", r)

    def test_classification_recorded_when_given(self):
        r = sr.make_record("story", "E001-S01-001", "done", "T", "x:1",
                           classification="feature")
        self.assertEqual(r["classification"], "feature")

    def test_empty_classification_is_not_recorded(self):
        r = sr.make_record("story", "E001-S01-001", "done", "T", "x:1", classification="")
        self.assertNotIn("classification", r)


class TestExtras(unittest.TestCase):
    def test_extras_absent_when_none_given(self):
        r = sr.make_record("story", "E001-S01-001", "done", "T", "x:1")
        self.assertNotIn("extras", r)

    def test_empty_extras_dict_is_not_recorded(self):
        r = sr.make_record("story", "E001-S01-001", "done", "T", "x:1", extras={})
        self.assertNotIn("extras", r)

    def test_extras_recorded_when_populated(self):
        extras = {"goal": "ship it", "depends_on": ["E001-S01-002"]}
        r = sr.make_record("epic", "E001", "backlog", "T", "x:1", extras=extras)
        self.assertEqual(r["extras"], extras)

    def test_collect_extras_picks_up_known_fields(self):
        node = {
            "key": "E001", "status": "done", "title": "T",  # typed surface
            "goal": "ship", "depends_on": ["a"], "superseded_by": "E001-S01-999",
            "estimate": {"man_hours": 5}, "actual": {"man_hours": 6},
        }
        extras = sr.collect_extras(node)
        self.assertEqual(set(extras), set(sr.KNOWN_EXTRAS))

    def test_collect_extras_ignores_typed_and_unknown_fields(self):
        node = {"key": "E001", "status": "done", "title": "T", "classification": "feature",
                "random_field": "value"}
        self.assertEqual(sr.collect_extras(node), {})

    def test_collect_extras_drops_empty_values(self):
        node = {"goal": "", "depends_on": [], "estimate": {}, "actual": None,
                "superseded_by": "keep"}
        self.assertEqual(sr.collect_extras(node), {"superseded_by": "keep"})

    def test_extras_count_boosts_richness_when_title_and_status_equal(self):
        """A record with populated extras must beat an otherwise-identical shell.

        This case matters if two sources ever supply the same key -- one with the
        typed record, one with the extras -- so the merge does not lose the extras.
        """
        shell = sr.make_record("epic", "E001", "backlog", "same", "x:1")
        rich = sr.make_record("epic", "E001", "backlog", "same", "x:2",
                              extras={"goal": "kept"})
        merged = sr.dedupe([shell, rich])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["extras"], {"goal": "kept"})


if __name__ == "__main__":
    unittest.main()
