#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""
Tests for sync-state.py. Run with:
  uv run skills/l3io-sync/scripts/tests/test-sync-state.py

Every case drives the real CLI through subprocess and then reads the YAML back off disk,
so what is asserted is the file a later sync run will actually load -- not a return value
that happened to be right before serialisation. This table is the only record linking a
BMad key to a GitHub issue; a mapping lost or duplicated here re-files an existing issue
as a new one, so the round-trip is the thing worth testing.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(os.path.dirname(_HERE), "sync-state.py")


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def cli(self, *args, stdin=None):
        r = subprocess.run([sys.executable, _SCRIPT, self.d, *args],
                           capture_output=True, text=True, input=stdin)
        return r.returncode, r.stdout, r.stderr

    def state(self):
        p = Path(self.d) / "_bmad" / "sync-state.yaml"
        return yaml.safe_load(p.read_text()) if p.exists() else None

    def add(self, key, remote_id=1, **extra):
        e = {"bmad_key": key, "remote_id": remote_id, **extra}
        code, _, err = self.cli("upsert", json.dumps(e))
        self.assertEqual(code, 0, err)


class TestListAndGet(Base):
    def test_list_on_a_project_with_no_state_file_is_an_empty_array(self):
        """A cold-start project must read as 'no mappings', not as an error -- setup lists
        before it has written anything."""
        code, out, err = self.cli("list")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), [])
        self.assertIsNone(self.state(), "listing must not create the file")

    def test_get_returns_the_entry_and_misses_are_exit_1(self):
        self.add("E001-S01-001", 7)
        code, out, _ = self.cli("get", "E001-S01-001")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["remote_id"], 7)
        code, _, err = self.cli("get", "E999-S01-001")
        self.assertEqual(code, 1)
        self.assertIn("No mapping found", err)

    def test_get_remote_matches_a_numeric_id_given_as_a_string(self):
        """YAML loads `remote_id: 7` as an int; the CLI argument is always a string. If the
        comparison were not string-normalised, every numeric issue id would miss and the
        sync would re-create issues that already exist."""
        self.add("E001-S01-001", 7)
        self.assertIsInstance(self.state()["mappings"][0]["remote_id"], int)
        code, out, err = self.cli("get-remote", "7")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["bmad_key"], "E001-S01-001")

    def test_get_remote_miss_is_exit_1(self):
        code, _, err = self.cli("get-remote", "404")
        self.assertEqual(code, 1)
        self.assertIn("No mapping found", err)


class TestUpsert(Base):
    def test_insert_then_update_keeps_one_row_per_key(self):
        code, out, _ = self.cli("upsert", json.dumps({"bmad_key": "K", "remote_id": 1}))
        self.assertEqual(json.loads(out)["action"], "inserted")
        code, out, _ = self.cli("upsert", json.dumps({"bmad_key": "K", "remote_id": 2}))
        self.assertEqual(json.loads(out)["action"], "updated")
        rows = self.state()["mappings"]
        self.assertEqual(len(rows), 1, "a second upsert must replace, never append")
        self.assertEqual(rows[0]["remote_id"], 2)

    def test_upsert_reads_stdin_and_a_file_the_same_way(self):
        payload = json.dumps({"bmad_key": "K", "remote_id": 3})
        self.assertEqual(self.cli("upsert", "-", stdin=payload)[0], 0)
        from_stdin = self.state()["mappings"]
        shutil.rmtree(Path(self.d) / "_bmad")
        f = Path(self.d) / "entry.json"
        f.write_text(payload, encoding="utf-8")
        self.assertEqual(self.cli("upsert", f"@{f}")[0], 0)
        self.assertEqual(self.state()["mappings"], from_stdin)

    def test_a_missing_json_file_is_reported_rather_than_treated_as_a_literal(self):
        code, _, err = self.cli("upsert", "@/nonexistent/entry.json")
        self.assertEqual(code, 1)
        self.assertIn("JSON file not found", err)

    def test_invalid_json_and_a_missing_bmad_key_are_both_refused(self):
        code, _, err = self.cli("upsert", "{not json")
        self.assertEqual(code, 1)
        self.assertIn("Invalid JSON", err)
        code, _, err = self.cli("upsert", json.dumps({"remote_id": 1}))
        self.assertEqual(code, 1)
        self.assertIn("bmad_key", err)
        self.assertIsNone(self.state(), "a refused upsert must not create state")

    def test_upsert_with_no_source_argument_is_refused(self):
        code, _, err = self.cli("upsert")
        self.assertEqual(code, 1)
        self.assertIn("upsert requires", err)

    def test_unrelated_top_level_keys_survive_a_write(self):
        """last_sync is part of the GitHub sync contract, not scratch -- a save that
        dropped sibling keys would silently reset it."""
        self.add("K")
        p = Path(self.d) / "_bmad" / "sync-state.yaml"
        s = yaml.safe_load(p.read_text())
        s["last_sync"] = "2026-01-01T00:00:00Z"
        p.write_text(yaml.dump(s, sort_keys=False), encoding="utf-8")
        self.add("K2")
        self.assertEqual(self.state()["last_sync"], "2026-01-01T00:00:00Z")


class TestUpdateHashAndRemove(Base):
    def test_update_hash_writes_both_hash_and_timestamp(self):
        self.add("K")
        code, out, err = self.cli("update-hash", "K", "abc123", "2026-02-02T00:00:00Z")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["action"], "hash_updated")
        row = self.state()["mappings"][0]
        self.assertEqual(row["last_synced_hash"], "abc123")
        self.assertEqual(row["last_synced_at"], "2026-02-02T00:00:00Z")

    def test_update_hash_defaults_the_timestamp_when_omitted(self):
        self.add("K")
        self.assertEqual(self.cli("update-hash", "K", "deadbeef")[0], 0)
        row = self.state()["mappings"][0]
        self.assertEqual(row["last_synced_hash"], "deadbeef")
        self.assertRegex(str(row["last_synced_at"]), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_update_hash_needs_both_arguments_and_an_existing_key(self):
        self.add("K")
        self.assertEqual(self.cli("update-hash", "K")[0], 1)
        code, _, err = self.cli("update-hash", "MISSING", "h")
        self.assertEqual(code, 1)
        self.assertIn("No mapping found", err)

    def test_remove_deletes_only_the_named_key(self):
        self.add("A", 1)
        self.add("B", 2)
        code, out, _ = self.cli("remove", "A")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["action"], "removed")
        self.assertEqual([r["bmad_key"] for r in self.state()["mappings"]], ["B"])

    def test_removing_a_key_that_is_not_there_is_exit_1(self):
        self.add("A")
        code, _, err = self.cli("remove", "NOPE")
        self.assertEqual(code, 1)
        self.assertIn("No mapping found", err)
        self.assertEqual(len(self.state()["mappings"]), 1)


class TestCliSurface(Base):
    def test_a_missing_project_root_is_refused(self):
        r = subprocess.run([sys.executable, _SCRIPT, os.path.join(self.d, "nope"), "list"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("project-root not found", r.stderr)

    def test_an_unknown_command_is_rejected_by_argparse(self):
        code, _, err = self.cli("frobnicate")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)


if __name__ == "__main__":
    unittest.main(verbosity=1)
