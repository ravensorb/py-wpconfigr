#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""Tests for migrate-engine.py — run with: uv run test-engine.py"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = Path(HERE) / "fixtures"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(HERE), filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eng = _load("migrate_engine", "migrate-engine.py")


def _copy(name):
    """Copy a fixture into a temp dir. Returns (project_path, tempdir_to_remove)."""
    d = Path(tempfile.mkdtemp())
    shutil.copytree(FIXTURES / name, d / "proj")
    return d / "proj", d


class TestFixtureCorpus(unittest.TestCase):
    def test_every_fixture_directory_has_a_reader(self):
        """Deleting a fixture must fail the suite, not silently shrink the corpus."""
        on_disk = {p.name for p in FIXTURES.iterdir()
                   if p.is_dir() and not p.name.startswith(".")}
        self.assertEqual(on_disk, set(eng.READERS), "fixture set != reader set")

    def test_the_corpus_has_all_five_layouts(self):
        self.assertEqual(len(eng.READERS), 5)


class TestDetect(unittest.TestCase):
    def _detect(self, fixture):
        p, d = _copy(fixture)
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return eng.detect(p, p)

    def test_l3io_flat(self):
        self.assertEqual(self._detect("l3io-flat"), "l3io-flat")

    def test_bmad_flat(self):
        self.assertEqual(self._detect("bmad-flat"), "bmad-flat")

    def test_split(self):
        self.assertEqual(self._detect("split"), "split")

    def test_per_epic(self):
        self.assertEqual(self._detect("per-epic"), "per-epic")

    def test_artifacts(self):
        self.assertEqual(self._detect("artifacts"), "artifacts")

    def test_nothing_present(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.assertEqual(eng.detect(d, d), "none")

    def test_split_wins_over_flat_because_both_carry_sprint_status(self):
        p, d = _copy("split")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.assertTrue((p / "sprint-status.yaml").is_file())
        self.assertEqual(eng.detect(p, p), "split")


class TestGatherAndPlan(unittest.TestCase):
    def test_l3io_flat_plan_counts(self):
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        plan = eng.build_plan(eng.gather("l3io-flat", p, p))
        self.assertEqual(plan["counts"], {"epic": 2, "sprint": 2, "story": 3})
        self.assertEqual(plan["problems"], [])

    def test_bmad_flat_plan_counts(self):
        p, d = _copy("bmad-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        plan = eng.build_plan(eng.gather("bmad-flat", p, p))
        self.assertEqual(plan["counts"], {"epic": 2, "sprint": 0, "story": 3})

    def test_a_plan_orders_parents_before_children(self):
        """import-node exits 3 on a sprint whose epic is absent, so order matters."""
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        kinds = [r["kind"]
                 for r in eng.build_plan(eng.gather("l3io-flat", p, p))["records"]]
        self.assertEqual(kinds, sorted(kinds, key=["epic", "sprint", "story"].index))

    def test_invalid_records_are_reported_as_problems(self):
        plan = eng.build_plan([
            {"kind": "epic", "key": "", "status": "backlog", "title": "", "source": "x"}])
        self.assertTrue(plan["problems"])

    def test_an_unknown_layout_gathers_nothing(self):
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.assertEqual(eng.gather("no-such-layout", p, p), [])

    def test_source_is_empty_is_false_when_the_file_has_content(self):
        p, d = _copy("bmad-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.assertFalse(eng.source_is_empty("l3io-flat", p, p))

    def test_source_is_empty_is_true_for_an_empty_file(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "sprint-status.yaml").write_text("", encoding="utf-8")
        self.assertTrue(eng.source_is_empty("l3io-flat", d, d))

    def test_render_plan_names_the_layout_and_the_counts(self):
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        text = eng.render_plan("l3io-flat", eng.build_plan(eng.gather("l3io-flat", p, p)))
        self.assertIn("l3io-flat", text)
        self.assertIn("epics", text)


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
PM_STATUS = os.path.join(REPO, "skills", "_shared", "pm-status.py")


class TestGate(unittest.TestCase):
    def test_non_empty_source_with_empty_plan_BLOCKS(self):
        """THE live defect, as a test. A BMad-schema file read by the l3io reader
        yields zero records over a non-empty source: the run must refuse."""
        p, d = _copy("bmad-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        plan = eng.build_plan(eng.gather("l3io-flat", p, p))   # wrong reader on purpose
        self.assertEqual(plan["counts"], {"epic": 0, "sprint": 0, "story": 0})
        msg = eng.gate("l3io-flat", plan, p, p)
        self.assertIsNotNone(msg)
        self.assertIn("BLOCKED", msg)

    def test_empty_source_with_empty_plan_is_allowed(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "sprint-status.yaml").write_text("", encoding="utf-8")
        self.assertIsNone(eng.gate("l3io-flat", eng.build_plan([]), d, d))

    def test_a_good_plan_passes(self):
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        plan = eng.build_plan(eng.gather("l3io-flat", p, p))
        self.assertIsNone(eng.gate("l3io-flat", plan, p, p))

    def test_validation_problems_block(self):
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        plan = eng.build_plan([
            {"kind": "epic", "key": "", "status": "backlog", "title": "", "source": "x"}])
        self.assertIn("BLOCKED", eng.gate("l3io-flat", plan, p, p))


class TestWriteVerifyDispose(unittest.TestCase):
    def _run(self, fixture, layout):
        p, d = _copy(fixture)
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        state = Path(d) / "state"
        plan = eng.build_plan(eng.gather(layout, p, p))
        written, errors = eng.write(plan, state, PM_STATUS)
        return p, d, state, plan, written, errors

    def test_write_creates_every_node(self):
        _, _, state, plan, written, errors = self._run("l3io-flat", "l3io-flat")
        self.assertEqual(errors, [])
        self.assertEqual(written, len(plan["records"]))
        self.assertTrue((state / "active" / "epic-001" / "epic.yaml").exists())
        self.assertTrue((state / "planned" / "epic-002" / "epic.yaml").exists())
        self.assertTrue(
            (state / "active" / "epic-001" / "sprint-01" / "E001-S01-001.yaml").exists())

    def test_verify_against_plan_passes_after_a_good_write(self):
        _, _, state, plan, _, _ = self._run("l3io-flat", "l3io-flat")
        self.assertEqual(eng.verify_against_plan(plan, state), [])

    def test_verify_catches_a_node_corrupted_on_disk(self):
        """Proves verification compares against the PLAN, not against itself."""
        _, _, state, plan, _, _ = self._run("l3io-flat", "l3io-flat")
        (state / "active" / "epic-001" / "epic.yaml").write_text(
            "key: 'E001'\nstatus: backlog\n", encoding="utf-8")
        problems = eng.verify_against_plan(plan, state)
        self.assertTrue(any("E001" in p for p in problems), problems)

    def test_verify_catches_a_missing_node(self):
        _, _, state, plan, _, _ = self._run("l3io-flat", "l3io-flat")
        (state / "planned" / "epic-002" / "epic.yaml").unlink()
        self.assertTrue(any("E002" in p for p in eng.verify_against_plan(plan, state)))

    def test_inferred_nodes_keep_their_origin_through_the_write(self):
        p, d, state, plan, _, errors = self._run("artifacts", "artifacts")
        self.assertEqual(errors, [])
        from ruamel.yaml import YAML
        node = YAML(typ="safe").load(
            (state / "active" / "epic-001" / "sprint-01" / "sprint.yaml")
            .read_text(encoding="utf-8"))
        self.assertEqual(node["origin"], "inferred")

    def test_dispose_renames_and_never_deletes(self):
        p, d, state, plan, _, _ = self._run("l3io-flat", "l3io-flat")
        moved = eng.dispose("l3io-flat", p, p)
        self.assertEqual(moved, [str(p / "sprint-status.yaml")])
        self.assertFalse((p / "sprint-status.yaml").exists())
        self.assertTrue((p / "sprint-status.yaml.legacy").exists())

    def test_dispose_retires_nothing_for_the_artifacts_layout(self):
        p, d, state, plan, _, _ = self._run("artifacts", "artifacts")
        self.assertEqual(eng.dispose("artifacts", p, p), [])
        self.assertTrue(
            (p / "epic-001" / "sprint-01" / "stories" / "E001-S01-001.md").exists())

    def test_the_source_survives_a_blocked_run(self):
        p, d = _copy("bmad-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        before = (p / "sprint-status.yaml").read_text(encoding="utf-8")
        plan = eng.build_plan(eng.gather("l3io-flat", p, p))
        self.assertIsNotNone(eng.gate("l3io-flat", plan, p, p))
        self.assertEqual((p / "sprint-status.yaml").read_text(encoding="utf-8"), before)
        self.assertFalse((p / "sprint-status.yaml.legacy").exists())

    def test_partial_write_failure_leaves_valid_records_on_disk_and_source_untouched(self):
        """A mid-plan write failure must not roll back valid records already written, and
        it must never trigger disposal of the source.

        The vacuous-truth trap the peer surfaced: a one-record fixture proves
        "records before the failing one survive" trivially (there are zero of them).
        This fixture has THREE records -- two valid + one poisoned with an invalid status
        that import-node rejects -- so the survivor set is a real property, not an empty one.
        """
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        source_before = (p / "sprint-status.yaml").read_text(encoding="utf-8")
        state = Path(d) / "state"

        # Craft a plan with a valid epic, an invalid epic, and another valid epic.
        # import-node returns exit 2 for an invalid status; the loop must keep going.
        poisoned_plan = eng.build_plan([
            {"kind": "epic", "key": "E001", "status": "in-progress", "title": "first"},
            {"kind": "epic", "key": "E002", "status": "not-a-real-status", "title": "bad"},
            {"kind": "epic", "key": "E003", "status": "done", "title": "third"},
        ])
        written, errors = eng.write(poisoned_plan, state, PM_STATUS)

        # The valid records land; the poisoned one is reported.
        self.assertEqual(written, 2, f"expected 2 successful writes, got {written}")
        self.assertEqual(len(errors), 1, f"expected 1 error, got {errors}")
        self.assertIn("E002", errors[0])
        self.assertTrue((state / "active" / "epic-001" / "epic.yaml").exists(),
                        "valid record BEFORE the failure must survive")
        self.assertTrue((state / "archived" / "epic-003" / "epic.yaml").exists(),
                        "valid record AFTER the failure must survive -- write does not "
                        "abort the loop on the first error")
        self.assertFalse((state / "planned" / "epic-002" / "epic.yaml").exists(),
                         "the poisoned record must NOT have landed on disk")

        # The source is untouched -- caller sees errors and never invokes dispose.
        self.assertEqual((p / "sprint-status.yaml").read_text(encoding="utf-8"),
                         source_before,
                         "source file must be byte-identical after a failed write")
        self.assertFalse((p / "sprint-status.yaml.legacy").exists(),
                         "dispose must never have run")

        # verify_against_plan sees the missing node -- proves the caller's gate works.
        problems = eng.verify_against_plan(poisoned_plan, state)
        self.assertTrue(any("E002" in prob for prob in problems),
                        f"verify must catch the missing E002, got: {problems}")

    def test_apply_is_idempotent(self):
        p, d, state, plan, written1, _ = self._run("l3io-flat", "l3io-flat")
        written2, errors2 = eng.write(plan, state, PM_STATUS)
        self.assertEqual(errors2, [])
        self.assertEqual(written2, 0, "a second apply must write nothing")

    def test_scalar_extras_land_on_disk_via_set_field(self):
        """The l3io-flat fixture carries `goal` on E001 and `superseded_by` on
        E001-S01-002. Both are scalar strings and pm-status.py has typed
        support via set-field. Both must land through the migration."""
        from ruamel.yaml import YAML

        _, _, state, _, _, errors = self._run("l3io-flat", "l3io-flat")
        # Filter out any WARN-only lines that might come through errors -- WARN
        # is stderr, not the errors list. set-field failures WOULD be here; none
        # expected.
        self.assertEqual(errors, [], f"set-field calls must not error: {errors}")

        _, epic = None, YAML(typ="safe").load(
            (state / "active" / "epic-001" / "epic.yaml").read_text(encoding="utf-8"))
        self.assertEqual(epic.get("goal"),
                         "All users can sign in with password + one federated provider.",
                         "epic.goal must round-trip through the migration")

        story = YAML(typ="safe").load(
            (state / "active" / "epic-001" / "sprint-01" / "E001-S01-002.yaml")
            .read_text(encoding="utf-8"))
        self.assertEqual(story.get("superseded_by"), "E001-S01-999",
                         "story.superseded_by must round-trip through the migration")

    def test_classification_is_passed_to_import_node(self):
        """import-node's typed --classification flag was accepted but the engine
        never sent it, so every story landed with classification=unknown even
        when the source had feature/etc. Pin the fix."""
        from ruamel.yaml import YAML

        _, _, state, _, _, _ = self._run("l3io-flat", "l3io-flat")
        story = YAML(typ="safe").load(
            (state / "active" / "epic-001" / "sprint-01" / "E001-S01-001.yaml")
            .read_text(encoding="utf-8"))
        self.assertEqual(story.get("classification"), "feature")

    def test_no_structured_extra_is_WARNed_any_more(self):
        """Was test_structured_extras_emit_visible_WARN_rather_than_silent_loss. All three
        structured fields now have typed writers, so a WARN for any of them would mean a
        regression to dropping it. The unrecognised-extra WARN path is separate and still
        tested below."""
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        state = Path(d) / "state"
        plan = eng.build_plan(eng.gather("l3io-flat", p, p))

        buf = io.StringIO()
        with redirect_stderr(buf):
            eng.write(plan, state, PM_STATUS)
        warns = [l for l in buf.getvalue().splitlines() if l.startswith("WARN")]

        for field in ("depends_on", "estimate", "actual"):
            self.assertFalse([w for w in warns if f" skipping {field}=" in w],
                             f"{field} has a typed writer; a WARN means it was dropped")
        self.assertEqual(eng.sr.STRUCTURED_EXTRAS_TO_WARN, (),
                         "nothing should be left in the WARN-only set")

    def test_an_unrecognised_extra_still_WARNs(self):
        """The WARN path itself must survive: a field the reader captured but the engine
        cannot route is still visible loss, not silent loss."""
        rec = {"kind": "epic", "key": "E001", "extras": {"no_such_field": "v"}}
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        state = Path(d) / "state"
        eng.write(eng.build_plan(eng.gather("l3io-flat", p, p)), state, PM_STATUS)
        buf = io.StringIO()
        with redirect_stderr(buf):
            eng._apply_extras(rec, state, PM_STATUS)
        self.assertIn("unrecognised extra", buf.getvalue())
        self.assertIn("no_such_field", buf.getvalue())

    def test_actual_lands_via_set_actual_with_the_N_A_sentinel(self):
        """The fixture carries `actual: {man_hours: 6}` on E001-S02-001. It must land, with
        tokens as the N/A sentinel rather than a fabricated four-class split, and without
        appending a calibration sample."""
        from ruamel.yaml import YAML

        _, _, state, _, _, errors = self._run("l3io-flat", "l3io-flat")
        self.assertEqual(errors, [], f"set-actual must not error: {errors}")
        p = state / "active" / "epic-001" / "sprint-02" / "E001-S02-001.yaml"
        node = YAML(typ="safe").load(p.read_text(encoding="utf-8"))
        self.assertIn("actual", node, "the actual must be carried into state")
        self.assertEqual(str(node["actual"].get("man_hours")), "6")
        self.assertEqual(str(node["actual"].get("tokens_k")), "N/A",
                         "legacy tokens must be the sentinel, never 0 -- calibration would "
                         "consume 0 as a real measurement")
        cal = state / "pm-calibration.yaml"
        self.assertFalse(cal.exists(),
                         "a bulk import must not append calibration samples")

    def test_depends_on_lands_via_the_typed_writer(self):
        """Converted from a WARN assertion. The l3io-flat fixture carries
        `depends_on: ['E001-S01-002']` on story E001-S01-001; it must now be ON DISK as a
        LIST, not WARNed and not flattened to the string "['E001-S01-002']"."""
        from ruamel.yaml import YAML

        _, _, state, _, _, errors = self._run("l3io-flat", "l3io-flat")
        self.assertEqual(errors, [], f"set-depends-on must not error: {errors}")
        p = state / "active" / "epic-001" / "sprint-01" / "E001-S01-001.yaml"
        node = YAML(typ="safe").load(p.read_text(encoding="utf-8"))
        self.assertIn("depends_on", node, "depends_on must be carried into state")
        self.assertIsInstance(node["depends_on"], list,
                              "it must land as a LIST -- a stringified list is worse than "
                              "nothing, because a later reader takes it for a scalar")
        self.assertEqual(node["depends_on"], ["E001-S01-002"])

    def test_estimate_lands_via_set_estimate(self):
        """Converted from a WARN assertion. The fixture carries a POINT estimate
        (`man_hours: 5`, `tokens_k: 40`) on E001-S02-001. set-estimate has point flags as well
        as range flags, so the mapping keys translate mechanically -- man_hours -> --man-hours
        -- with no per-metric table to drift."""
        from ruamel.yaml import YAML

        _, _, state, _, _, errors = self._run("l3io-flat", "l3io-flat")
        self.assertEqual(errors, [], f"set-estimate must not error: {errors}")
        p = state / "active" / "epic-001" / "sprint-02" / "E001-S02-001.yaml"
        node = YAML(typ="safe").load(p.read_text(encoding="utf-8"))
        self.assertIn("estimate", node, "the estimate must be carried into state")
        est = node["estimate"]
        self.assertTrue(
            any("man_hours" in str(k) for k in est),
            f"man_hours must survive the translation; got {sorted(est)}")

    def test_a_legacy_cost_in_an_estimate_is_dropped_with_a_note(self):
        """cost is derived from tokens at capture and frozen; set-estimate rejects --cost*
        outright. A legacy cost must be dropped visibly, not passed and not silently lost."""
        rec = {"kind": "epic", "key": "E001",
               "extras": {"estimate": {"man_hours": 5, "cost_low": "1.00"}}}
        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        state = Path(d) / "state"
        eng.write(eng.build_plan(eng.gather("l3io-flat", p, p)), state, PM_STATUS)
        buf = io.StringIO()
        with redirect_stderr(buf):
            errs = eng._apply_extras(rec, state, PM_STATUS)
        self.assertEqual(errs, [], f"a dropped cost must not be an error: {errs}")
        self.assertIn("cost_low", buf.getvalue())
        self.assertIn("derived", buf.getvalue())

    def test_cli_apply_end_to_end(self):


        p, d = _copy("l3io-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        state = Path(d) / "state"
        code = eng.main([
            "--artifacts", str(p), "--project-root", str(p), "--apply",
            "--state-root", str(state), "--pm-status", PM_STATUS, "--dispose"])
        self.assertEqual(code, 0)
        self.assertTrue((state / "active" / "epic-001" / "epic.yaml").exists())
        self.assertTrue((p / "sprint-status.yaml.legacy").exists())

    def test_additive_bootstrap_on_partial_sharded_state(self):
        """A project with sharded state for SOME stories, plus artifact .md files
        for others, must bootstrap only the missing ones and leave existing state
        untouched. Passing --state-root to gather() scopes the plan to the orphan
        set; verify passes because nothing planned collides with the pre-existing
        nodes. This is the additive-bootstrap use case, end-to-end."""
        from ruamel.yaml import YAML

        p, d = _copy("artifacts")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        state = Path(d) / "state"

        # Pre-populate state for E001-S01-001 with a status that DIFFERS from what
        # the artifact frontmatter says. Without additive scoping, verify would
        # trip on this drift; with it, the reader skips this story entirely and
        # the pre-existing node is left exactly as-is.
        existing_sprint = state / "active" / "epic-001" / "sprint-01"
        existing_sprint.mkdir(parents=True)
        (state / "active" / "epic-001" / "epic.yaml").write_text(
            "key: 'E001'\nstatus: in-progress\ntitle: 'Existing epic'\n",
            encoding="utf-8")
        (existing_sprint / "sprint.yaml").write_text(
            "key: 'S01'\nepic: 'E001'\nstatus: in-progress\ntitle: 'Existing sprint'\n",
            encoding="utf-8")
        (existing_sprint / "E001-S01-001.yaml").write_text(
            "key: 'E001-S01-001'\nepic: 'E001'\nsprint: 'S01'\n"
            "status: backlog\ntitle: 'Pre-existing, do not touch'\n",
            encoding="utf-8")

        # Plan with state_root -- scoped to orphans only.
        plan = eng.build_plan(eng.gather("artifacts", p, p, state))
        planned_keys = {r["key"] for r in plan["records"]}
        self.assertNotIn("E001-S01-001", planned_keys,
                         "the tracked story must be skipped by the plan")
        self.assertNotIn("E001", planned_keys,
                         "the tracked epic must not be re-inferred")
        self.assertNotIn("E001-S01", planned_keys,
                         "the tracked sprint must not be re-inferred")
        self.assertIn("E001-S01-002", planned_keys,
                      "the orphan story must be in the plan")

        # Apply: writes the orphans, existing state is untouched.
        written, errors = eng.write(plan, state, PM_STATUS)
        self.assertEqual(errors, [])
        self.assertGreater(written, 0, "at least one orphan was expected")

        # The pre-existing node is byte-preserved -- the migration did not touch it.
        existing = YAML(typ="safe").load(
            (existing_sprint / "E001-S01-001.yaml").read_text(encoding="utf-8"))
        self.assertEqual(existing["title"], "Pre-existing, do not touch")
        self.assertEqual(existing["status"], "backlog",
                         "existing state must NOT be overwritten with the frontmatter's status")

        # Verify passes because it compares the plan (orphans only) not the full tree.
        self.assertEqual(eng.verify_against_plan(plan, state), [])

    def test_cli_apply_on_a_bmad_project_migrates_it_rather_than_blocking(self):
        """detect() picks the right reader, so the BMad project is CONVERTED."""
        p, d = _copy("bmad-flat")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        state = Path(d) / "state"
        code = eng.main([
            "--artifacts", str(p), "--project-root", str(p), "--apply",
            "--state-root", str(state), "--pm-status", PM_STATUS])
        self.assertEqual(code, 0)
        self.assertTrue((state / "active" / "epic-001" / "epic.yaml").exists())


if __name__ == "__main__":
    unittest.main()
