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
Tests for bmad-deps.py. Run with:
  uv run -q --with 'ruamel.yaml>=0.18' python3 skills/l3io-doctor/scripts/tests/test-bmad-deps.py

Every case drives the real CLI through subprocess. Fixture trees are built by _tree(); nothing
here reads this repo's own _bmad/ install, and HOME is repointed at an empty directory for
every invocation, because resolve() probes ~/.claude as its second root -- a suite that let the
developer's real home leak in would pass or fail on machine state rather than on the fixture.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


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
    _RUN_TMP = tempfile.mkdtemp(prefix="test-bmad-deps-")
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
SCRIPT = os.path.join(os.path.dirname(HERE), "bmad-deps.py")
SKILL_ROOT = os.path.dirname(os.path.dirname(SCRIPT))
INVENTORY = os.path.join(SKILL_ROOT, "assets", "bmad-dependencies.json")


class Base(unittest.TestCase):
    def setUp(self):
        # An empty HOME, so the ~/.claude probe finds nothing the fixture did not put there.
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.err = ""

    def run_cli(self, args):
        """Run the real CLI; returns (exit code, stdout). stderr lands in self.err."""
        proc = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              env={**os.environ, "HOME": self.home})
        self.err = proc.stderr
        return proc.returncode, proc.stdout

    def _tree(self, names, layout="skills", version="6.12.0", shims=None, manifest_rows=None,
              bmb_version=None):
        """Build a project root whose .claude/<layout>/ contains `names`.

        `manifest_rows` is a list of data-row strings (no header) for
        `_bmad/_config/skill-manifest.csv`; the header `canonicalId,name,description,module,path`
        is always written when rows are given. `None` (the default) omits the file entirely, so
        a fixture that never mentions the manifest models a project without it.

        `bmb_version`, when given, adds a `bmb` module entry carrying that version -- the field
        baseline_drift compares against assets/bmad-baseline.json's `bmb_version`.
        """
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        for n in names:
            if layout == "skills":
                d = os.path.join(root, ".claude", "skills", n)
                os.makedirs(d, exist_ok=True)
                pathlib.Path(d, "SKILL.md").write_text("x", encoding="utf-8")
            else:
                d = os.path.join(root, ".claude", "commands")
                os.makedirs(d, exist_ok=True)
                pathlib.Path(d, f"{n}.md").write_text("x", encoding="utf-8")
        mf = os.path.join(root, "_bmad", "_config")
        os.makedirs(mf, exist_ok=True)
        text = f"installation:\n  version: {version}\n"
        if shims is not None:  # omitted entirely for a pre-6.12 manifest, which has no such key
            text += f"  installShims: {'true' if shims else 'false'}\n"
        text += "modules:\n  - name: core\n  - name: bmm\n"
        if bmb_version is not None:
            text += f"  - name: bmb\n    version: {bmb_version}\n"
        text += "ides:\n  - claude-code\n"
        pathlib.Path(mf, "manifest.yaml").write_text(text, encoding="utf-8")
        if manifest_rows is not None:
            csv_text = "canonicalId,name,description,module,path\n"
            csv_text += "".join(f"{row}\n" for row in manifest_rows)
            pathlib.Path(mf, "skill-manifest.csv").write_text(csv_text, encoding="utf-8")
        return root

    def _baseline(self, core_version=None, bmb_version=None):
        """A throwaway baseline file with only the given fields set."""
        data = {}
        if core_version is not None:
            data["core_version"] = core_version
        if bmb_version is not None:
            data["bmb_version"] = bmb_version
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "baseline.json")
        pathlib.Path(p).write_text(json.dumps(data), encoding="utf-8")
        return p

    def _inv(self, skills):
        """A throwaway inventory file holding exactly `skills`."""
        return self._raw_inv(json.dumps({"verified_against": "6.12.0", "skills": skills}))

    def _raw_inv(self, text):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "inv.json")
        pathlib.Path(p).write_text(text, encoding="utf-8")
        return p

    @staticmethod
    def real_inventory():
        """The shipped inventory -- the source of truth these cases derive their scope from."""
        return json.loads(pathlib.Path(INVENTORY).read_text(encoding="utf-8"))["skills"]

    @classmethod
    def required_preferred(cls):
        return [e["name"] for e in cls.real_inventory() if e.get("status") == "required"]

    @classmethod
    def fallbacks(cls):
        return {e["name"]: e["fallback"] for e in cls.real_inventory()
                if e.get("fallback") and e.get("status") in ("required", "optional")}


class TestPresence(Base):
    def test_all_required_present_exits_0(self):
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-two", "status": "required"}])
        root = self._tree(["a-one", "a-two"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertIn("ok       a-one", out)
        self.assertIn("ok       a-two", out)
        self.assertNotIn("MISSING", out)

    def test_missing_required_exits_3(self):
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-gone", "status": "required"}])
        root = self._tree(["a-one"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 3)
        self.assertIn("MISSING  a-gone", out)
        self.assertIn("ok       a-one", out)

    def test_missing_optional_warns_but_exits_0(self):
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-opt", "status": "optional"}])
        root = self._tree(["a-one"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertIn("absent   a-opt", out)
        self.assertIn("self-skips", out)

    def test_related_present_surfaces_as_related_row(self):
        """A `related` skill we detect but do not dispatch. Absence is silent; presence
        is surfaced so callers (l3io-help) can enable relationship-aware behaviour."""
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-rel", "status": "related", "note": "adjacent tooling"}])
        root = self._tree(["a-one", "a-rel"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertIn("related  a-rel", out)
        self.assertIn("adjacent tooling", out,
                      "the entry's optional `note` field must reach the output")
        self.assertNotIn("self-skips", out,
                         "related skills must not use the optional 'phase self-skips' phrasing")

    def test_related_absent_is_silent(self):
        """The default state for a related skill is 'not installed', because it is not our
        tooling. A missing related skill is not a warning and must not show up in the report,
        the way a missing optional does."""
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-rel", "status": "related"}])
        root = self._tree(["a-one"])  # a-rel deliberately absent
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertNotIn("a-rel", out)
        self.assertNotIn("absent", out)

    def test_related_json_lands_in_related_present_bucket(self):
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-rel", "status": "related", "note": "for callers"}])
        root = self._tree(["a-one", "a-rel"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        self.assertEqual(len(data["related_present"]), 1)
        self.assertEqual(data["related_present"][0]["name"], "a-rel")
        self.assertEqual(data["related_present"][0]["note"], "for callers")
        self.assertTrue(data["related_present"][0]["path"].endswith("SKILL.md"))
        # `resolved` is for skills we dispatch; a related skill must not appear there.
        self.assertEqual([r["name"] for r in data["resolved"]], ["a-one"])

    def test_related_absent_from_bmad_manifest_is_not_a_contradiction(self):
        """A related skill ships via ITS OWN installer (bmad-loop is the shape), not BMad's,
        so its absence from BMad's skill-manifest.csv is normal, not a contradiction."""
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-rel", "status": "related"}])
        root = self._tree(["a-one", "a-rel"], version="6.12.0")
        # Seed a manifest that lists a-one but NOT a-rel.
        manifest = os.path.join(root, "_bmad", "_config", "skill-manifest.csv")
        os.makedirs(os.path.dirname(manifest), exist_ok=True)
        with open(manifest, "w") as fh:
            fh.write("canonicalId,other\na-one,x\n")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--strict", "--format", "json"])
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        self.assertEqual(data["status_contradictions"], [],
                         "a related skill not listed in the manifest is not a contradiction")


class TestLayouts(Base):
    """Both install layouts, under both roots. Probing only one silently mis-detects on one
    BMad version -- the exact defect Task 7 fixed in the step files."""

    def test_v612_skills_layout_is_detected(self):
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree(["a-one"], layout="skills", version="6.12.0", shims=True)
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        self.assertTrue(data["shims_installed"])
        self.assertTrue(data["resolved"][0]["path"].endswith(
            os.path.join("skills", "a-one", "SKILL.md")), data["resolved"][0]["path"])

    def test_legacy_flat_commands_layout_is_detected(self):
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree(["a-one"], layout="commands", version="6.11.0")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        # A pre-6.12 manifest carries no installShims key at all: absent must mean false,
        # never a KeyError on precisely the older install this script exists to protect.
        self.assertFalse(data["shims_installed"])
        self.assertEqual(data["bmad_version"], "6.11.0")
        self.assertTrue(data["resolved"][0]["path"].endswith(
            os.path.join("commands", "a-one.md")), data["resolved"][0]["path"])

    def test_home_root_is_probed_when_the_project_lacks_the_skill(self):
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree([])
        d = os.path.join(self.home, ".claude", "skills", "a-one")
        os.makedirs(d)
        pathlib.Path(d, "SKILL.md").write_text("x", encoding="utf-8")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertIn("ok       a-one", out)


class TestUnreadable(Base):
    def test_absent_manifest_exits_4(self):
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree(["a-one"])
        os.remove(os.path.join(root, "_bmad", "_config", "manifest.yaml"))
        code, _ = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 4)
        self.assertIn("manifest.yaml", self.err)

    def test_malformed_inventory_exits_2(self):
        inv = self._raw_inv("{ this is not json")
        root = self._tree(["a-one"])
        code, _ = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 2)
        self.assertIn("inventory", self.err)

    def test_unreadable_inventory_exits_4(self):
        root = self._tree(["a-one"])
        code, _ = self.run_cli(["verify", "--project-root", root,
                                "--inventory", os.path.join(root, "no-such-inventory.json")])
        self.assertEqual(code, 4)
        self.assertIn("inventory", self.err)


class TestInventoryShape(Base):
    """A broken inventory must never resolve to a lenient reading. check-docs.mjs validates
    only the shipped inventory, while --inventory accepts any path, so the reach of that rule
    is guarded here -- and a shape error must land on the documented exit 2, never as the
    undefined exit 1 an unchecked .get() would produce."""

    def test_unknown_status_exits_2(self):
        # A typo'd status once fell through to the optional bucket, reporting a REQUIRED skill
        # as "optional -- its phase self-skips" at exit 0: a false green of exactly the class
        # this script exists to prevent. It must be fatal, never coerced to optional.
        inv = self._inv([{"name": "a-one", "status": "requried"}])
        root = self._tree(["a-one"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 2)
        self.assertIn("a-one", self.err)          # the message names the entry
        self.assertIn("'requried'", self.err)     # ...and the bad value
        self.assertNotIn("self-skips", out)       # ...and never reports it as optional

    def test_top_level_array_inventory_exits_2(self):
        # The one malformed shape that slips past both this script's JSON parse and check 16.
        inv = self._raw_inv('[{"name": "a-one", "status": "required"}]')
        root = self._tree(["a-one"])
        code, _ = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 2)
        self.assertIn("expected an object", self.err)

    def test_non_object_entry_exits_2(self):
        inv = self._raw_inv(json.dumps({"skills": ["a-one"]}))
        root = self._tree(["a-one"])
        code, _ = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 2)
        self.assertIn("skills[0]", self.err)

    # The three cases below were all silent passes under `inv.get("skills") or []`: the empty
    # list was substituted BEFORE the isinstance guard could see the bad value, so a missing
    # key and every falsy non-list alike exited 0 having verified nothing, printing only the
    # version/modules line. An inventory declaring no skills is not a usable inventory.
    def test_missing_skills_key_exits_2(self):
        inv = self._raw_inv(json.dumps({"verified_against": "6.12.0"}))
        root = self._tree(["a-one"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 2)
        self.assertIn("no 'skills' key", self.err)
        self.assertEqual(out, "")   # and it must not report a clean run on the way out

    def test_empty_skills_list_exits_2(self):
        inv = self._inv([])
        root = self._tree(["a-one"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 2)
        self.assertIn("empty", self.err)
        self.assertEqual(out, "")

    def test_falsy_non_list_skills_exits_2(self):
        # "" is falsy and not a list: the shape that made the isinstance guard unreachable.
        inv = self._raw_inv(json.dumps({"skills": ""}))
        root = self._tree(["a-one"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 2)
        self.assertIn("'skills' is str", self.err)
        self.assertEqual(out, "")


class TestJson(Base):
    def test_json_format_shape(self):
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-opt", "status": "optional"},
                         {"name": "a-old", "status": "removed", "replaced_by": "a-one"},
                         {"name": "a-not", "status": "not-a-skill", "reason": "x"}])
        root = self._tree(["a-one", "a-old", "a-not"])
        argv = ["verify", "--project-root", root, "--inventory", inv, "--format", "json"]
        code, out = self.run_cli(argv)
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        self.assertEqual(set(data), {"bmad_version", "shims_installed", "modules", "resolved",
                                     "missing_required", "optional_absent", "shims_in_use",
                                     "deprecated_absent", "related_present", "shipped_skills",
                                     "status_contradictions", "baseline_drift"})
        self.assertEqual(data["bmad_version"], "6.12.0")
        self.assertEqual(data["modules"], ["core", "bmm"])
        self.assertEqual([r["name"] for r in data["resolved"]], ["a-one"])
        self.assertEqual(set(data["resolved"][0]), {"name", "status", "resolved_as", "path"})
        self.assertEqual(data["optional_absent"], ["a-opt"])
        self.assertEqual(data["missing_required"], [])
        self.assertEqual([s["name"] for s in data["shims_in_use"]], ["a-old"])
        # not-a-skill is skipped entirely: present on disk, reported nowhere.
        self.assertNotIn("a-not", out)
        # A bare-string modules entry must not crash the manifest read.
        pathlib.Path(root, "_bmad", "_config", "manifest.yaml").write_text(
            "installation:\n  version: 6.12.0\nmodules:\n  - name: core\n  - bare\n",
            encoding="utf-8")
        code, out = self.run_cli(argv)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(json.loads(out)["modules"], ["core"])


class TestFallback(Base):
    """Cases 9-13: the executable form of the "do not break a working install" guarantee."""

    def test_fallback_resolves_when_preferred_absent(self):
        names = [n for n in self.required_preferred() if n != "bmad-review"]
        names.append("bmad-review-adversarial-general")
        root = self._tree(names, layout="commands", version="6.11.0")
        code, out = self.run_cli(["verify", "--project-root", root, "--format", "json"])
        self.assertEqual(code, 0, self.err)
        entry = next(r for r in json.loads(out)["resolved"] if r["name"] == "bmad-review")
        self.assertEqual(entry["resolved_as"], "bmad-review-adversarial-general")
        # the text form must say WHICH name resolved
        code, out = self.run_cli(["verify", "--project-root", root])
        self.assertEqual(code, 0, self.err)
        self.assertIn("(via bmad-review-adversarial-general)", out)

    def test_preferred_wins_when_both_present(self):
        root = self._tree(self.required_preferred() + ["bmad-review-adversarial-general"])
        code, out = self.run_cli(["verify", "--project-root", root, "--format", "json"])
        self.assertEqual(code, 0, self.err)
        entry = next(r for r in json.loads(out)["resolved"] if r["name"] == "bmad-review")
        self.assertEqual(entry["resolved_as"], "bmad-review")

    def test_both_absent_required_exits_3(self):
        inv = self._inv([{"name": "a-new", "status": "required", "fallback": "a-old"}])
        root = self._tree([])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 3)
        self.assertIn("MISSING  a-new", out)

    def test_both_absent_optional_warns_exits_0(self):
        inv = self._inv([{"name": "a-new", "status": "optional", "fallback": "a-old"}])
        root = self._tree([])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertIn("absent   a-new", out)

    def test_pre_612_only_tree_resolves_every_site_via_fallback(self):
        """Spec 12.2: an install carrying only pre-6.12 names still resolves every site."""
        fb = self.fallbacks()
        self.assertTrue(fb, "the inventory declares no fallbacks; this case would be vacuous")
        names = [fb.get(n, n) for n in self.required_preferred()]
        root = self._tree(names, layout="commands", version="6.11.0")
        code, out = self.run_cli(["verify", "--project-root", root, "--format", "json"])
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        self.assertEqual(data["missing_required"], [])
        by = {r["name"]: r for r in data["resolved"]}
        required_with_fallback = [e["name"] for e in self.real_inventory()
                                  if e.get("status") == "required" and e.get("fallback")]
        self.assertTrue(required_with_fallback)
        for name in required_with_fallback:
            self.assertIn(name, by)
            self.assertEqual(by[name]["resolved_as"], fb[name], name)


class TestShims(Base):
    def test_removed_skill_on_disk_is_reported_as_shim_in_use(self):
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-old", "status": "removed", "removed_in": "6.12.0",
                          "replaced_by": "a-one"}])
        root = self._tree(["a-one", "a-old"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertIn("shim     a-old", out)
        self.assertIn("a-one replaces it", out)
        self.assertNotIn("MISSING", out)

    def test_deprecated_skill_on_disk_is_reported_as_shim_in_use(self):
        # Ruling (task-2-shims): a deprecated entry that resolves must land in shims_in_use,
        # exactly like a removed one, not fall through to the required/optional branch and be
        # reported as ordinary `resolved`.
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-shim", "status": "deprecated", "deprecated_in": "6.12.0",
                          "replaced_by": "a-one"}])
        root = self._tree(["a-one", "a-shim"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        self.assertEqual([s["name"] for s in data["shims_in_use"]], ["a-shim"])
        self.assertEqual(data["shims_in_use"][0]["replaced_by"], "a-one")
        self.assertEqual(data["deprecated_absent"], [])
        self.assertNotIn("a-shim", [r["name"] for r in data["resolved"]])
        # text form too
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertIn("shim     a-shim", out)
        self.assertIn("a-one replaces it", out)

    def test_deprecated_skill_absent_is_not_reported_as_optional(self):
        # Ruling (task-2-shims), second half: a non-resolving deprecated entry must not be
        # mislabelled "optional -- its phase self-skips" (false: the skill did not self-skip,
        # it is simply not installed on this project). It gets its own bucket instead.
        inv = self._inv([{"name": "a-one", "status": "required"},
                         {"name": "a-shim", "status": "deprecated", "deprecated_in": "6.12.0",
                          "replaced_by": "a-one"}])
        root = self._tree(["a-one"])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        self.assertEqual(data["shims_in_use"], [])
        self.assertEqual(data["optional_absent"], [])
        self.assertEqual(data["deprecated_absent"], [{"name": "a-shim", "replaced_by": "a-one"}])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertNotIn("self-skips", out)
        self.assertIn("gone     a-shim", out)

    def test_reencoded_shim_entries_still_appear_in_shims_in_use(self):
        # The exact regression the ruling names: bmad-create-story, bmad-dev-story and
        # bmad-review-adversarial-general were re-encoded from removed to deprecated. If
        # verify() fell through to the required/optional branch for `deprecated`, this list
        # would silently become empty while check-deps still exited 0.
        deprecated_names = [e["name"] for e in self.real_inventory()
                            if e.get("status") == "deprecated"]
        self.assertEqual(set(deprecated_names),
                         {"bmad-create-story", "bmad-dev-story",
                          "bmad-review-adversarial-general"})
        # Also install every required skill (by its preferred name) so this case isolates the
        # shim bucket rather than tripping missing_required for unrelated reasons.
        root = self._tree(deprecated_names + self.required_preferred())
        code, out = self.run_cli(["verify", "--project-root", root, "--format", "json"])
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        self.assertEqual(set(s["name"] for s in data["shims_in_use"]), set(deprecated_names))
        self.assertEqual(data["deprecated_absent"], [])


class TestContradictions(Base):
    """status_contradictions: the inventory is an annotation over a set derived from BMad's own
    skill-manifest.csv, not the set itself. These cases attack both contradiction directions and
    the unknown-manifest case, since a check that reports "no contradictions" because it could
    not read the manifest would be a false green of the exact kind this feature exists to catch.
    """

    def test_removed_entry_that_still_ships_is_a_contradiction(self):
        root = self._tree(["bmad-dev-story"],
                          manifest_rows=["bmad-dev-story,Dev Story,desc,bmm,path"])
        inv = self._inv([{"name": "bmad-dev-story", "status": "removed",
                          "removed_in": "6.12.0", "replaced_by": "bmad-build"}])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(
            data["status_contradictions"],
            [{"name": "bmad-dev-story", "declared": "removed", "manifest": "ships"}])

    def test_contradiction_exits_5_under_strict(self):
        root = self._tree(["bmad-dev-story"],
                          manifest_rows=["bmad-dev-story,Dev Story,desc,bmm,path"])
        inv = self._inv([{"name": "bmad-dev-story", "status": "removed",
                          "removed_in": "6.12.0", "replaced_by": "bmad-build"}])
        code, _ = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                "--strict"])
        self.assertEqual(code, 5)

    def test_no_contradiction_does_not_exit_5_under_strict(self):
        # --strict must not change the exit code when status_contradictions is empty -- it is a
        # gate on the finding, not an unconditional stricter mode.
        root = self._tree(["a-one"], manifest_rows=["a-one,A One,desc,bmm,path"])
        inv = self._inv([{"name": "a-one", "status": "required"}])
        code, _ = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                "--strict"])
        self.assertEqual(code, 0, self.err)

    def test_required_entry_absent_from_manifest_is_a_contradiction(self):
        # The other direction: the inventory claims BMad ships it, but the manifest disagrees.
        root = self._tree(["a-one"], manifest_rows=["b-two,B Two,desc,bmm,path"])
        inv = self._inv([{"name": "a-one", "status": "required"}])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(
            data["status_contradictions"],
            [{"name": "a-one", "declared": "required", "manifest": "absent"}])
        # text form names the contradiction too
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv])
        self.assertEqual(code, 0, self.err)
        self.assertIn("CONTRADICTION", out)
        self.assertIn("a-one", out)

    def test_absent_manifest_reports_null_not_contradictions(self):
        root = self._tree(["bmad-dev-story"], manifest_rows=None)
        inv = self._inv([{"name": "bmad-dev-story", "status": "removed",
                          "removed_in": "6.12.0", "replaced_by": "bmad-build"}])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertEqual(code, 0, self.err)
        self.assertIsNone(data["shipped_skills"])
        self.assertEqual(data["status_contradictions"], [])

    def test_shipped_skills_reported_when_manifest_present(self):
        root = self._tree(["a-one"],
                          manifest_rows=["a-one,A One,desc,bmm,path",
                                         "b-two,B Two,desc,bmm,path"])
        inv = self._inv([{"name": "a-one", "status": "required"}])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(data["shipped_skills"], ["a-one", "b-two"])

    def test_not_a_skill_and_deprecated_are_never_contradictions(self):
        # not-a-skill is skipped outright regardless of manifest membership; deprecated is a
        # shipped status, so it must NOT be reported absent when the manifest agrees it ships,
        # and must be silently fine when it does not ship either -- deprecated means "BMad may
        # or may not still ship this", so absence is not a contradiction... except the spec's
        # SHIPPED_STATUSES treats deprecated as "should be in the manifest". Model that: a
        # deprecated entry the manifest still ships is not a contradiction.
        root = self._tree(["a-not", "a-dep"],
                          manifest_rows=["a-dep,A Dep,desc,bmm,path"])
        inv = self._inv([{"name": "a-not", "status": "not-a-skill", "reason": "x"},
                         {"name": "a-dep", "status": "deprecated", "deprecated_in": "6.12.0",
                          "replaced_by": "a-one"}])
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--format", "json"])
        data = json.loads(out)
        self.assertEqual(code, 0, self.err)
        self.assertEqual(data["status_contradictions"], [])


class TestBaselineDrift(Base):
    """baseline_drift: a WARNING signal comparing the installed manifest against the pinned
    assets/bmad-baseline.json (ADR-0006). Must never affect the exit code, under --strict or
    otherwise -- BMad moving on is normal; being unaware of it is the defect this exists to
    surface."""

    def test_matching_baseline_reports_no_drift(self):
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree(["a-one"], version="6.12.0", bmb_version="v2.2.2")
        baseline = self._baseline(core_version="6.12.0", bmb_version="v2.2.2")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--baseline", baseline, "--format", "json"])
        self.assertEqual(code, 0, self.err)
        self.assertEqual(json.loads(out)["baseline_drift"], [])

    def test_core_version_drift_is_reported_without_failing(self):
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree(["a-one"], version="6.13.0", bmb_version="v2.2.2")
        baseline = self._baseline(core_version="6.12.0", bmb_version="v2.2.2")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--baseline", baseline, "--format", "json"])
        self.assertEqual(code, 0, self.err)
        self.assertEqual(json.loads(out)["baseline_drift"],
                         [{"field": "core_version", "expected": "6.12.0", "found": "6.13.0"}])
        # text form carries a BASELINE line naming both the pinned and installed values
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--baseline", baseline])
        self.assertEqual(code, 0, self.err)
        self.assertIn("BASELINE", out)
        self.assertIn("6.12.0", out)
        self.assertIn("6.13.0", out)

    def test_bmb_version_drift_is_reported_without_failing(self):
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree(["a-one"], version="6.12.0", bmb_version="v3.0.0")
        baseline = self._baseline(core_version="6.12.0", bmb_version="v2.2.2")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--baseline", baseline, "--format", "json"])
        self.assertEqual(code, 0, self.err)
        self.assertEqual(json.loads(out)["baseline_drift"],
                         [{"field": "bmb_version", "expected": "v2.2.2", "found": "v3.0.0"}])

    def test_no_baseline_line_in_text_output_when_matching(self):
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree(["a-one"], version="6.12.0", bmb_version="v2.2.2")
        baseline = self._baseline(core_version="6.12.0", bmb_version="v2.2.2")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--baseline", baseline])
        self.assertEqual(code, 0, self.err)
        self.assertNotIn("BASELINE", out)

    def test_missing_baseline_file_yields_no_drift_not_a_crash(self):
        # A missing baseline means "nothing to compare against", not agreement -- and never a
        # crash, since the pinned file is packaging state, not something a caller controls.
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree(["a-one"], version="6.13.0", bmb_version="v3.0.0")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--baseline", os.path.join(root, "no-such-baseline.json"),
                                  "--format", "json"])
        self.assertEqual(code, 0, self.err)
        self.assertEqual(json.loads(out)["baseline_drift"], [])

    def test_drift_does_not_trigger_strict_exit(self):
        # --strict gates status_contradictions only. Drift alone must never turn it into exit 5.
        inv = self._inv([{"name": "a-one", "status": "required"}])
        root = self._tree(["a-one"], version="6.13.0", bmb_version="v3.0.0",
                          manifest_rows=["a-one,A One,desc,bmm,path"])
        baseline = self._baseline(core_version="6.12.0", bmb_version="v2.2.2")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--baseline", baseline, "--strict", "--format", "json"])
        self.assertEqual(code, 0, self.err)
        data = json.loads(out)
        self.assertTrue(data["baseline_drift"])
        self.assertEqual(data["status_contradictions"], [])

    def test_contradiction_still_exits_5_under_strict_alongside_drift(self):
        # Drift and a real contradiction can co-occur; the contradiction must still be the one
        # that decides the exit code, unaffected by drift being present too.
        root = self._tree(["bmad-dev-story"], version="6.13.0", bmb_version="v3.0.0",
                          manifest_rows=["bmad-dev-story,Dev Story,desc,bmm,path"])
        inv = self._inv([{"name": "bmad-dev-story", "status": "removed",
                          "removed_in": "6.12.0", "replaced_by": "bmad-build"}])
        baseline = self._baseline(core_version="6.12.0", bmb_version="v2.2.2")
        code, out = self.run_cli(["verify", "--project-root", root, "--inventory", inv,
                                  "--baseline", baseline, "--strict", "--format", "json"])
        self.assertEqual(code, 5)
        data = json.loads(out)
        self.assertTrue(data["baseline_drift"])
        self.assertTrue(data["status_contradictions"])

    def test_default_baseline_matches_this_repos_pinned_values(self):
        # The shipped bmad-baseline.json must actually describe this repo's baseline pair --
        # a stale default would make every real (non-fixture) run report phantom drift.
        default_baseline = json.loads(
            pathlib.Path(SKILL_ROOT, "assets", "bmad-baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(default_baseline["core_version"], "6.12.0")
        self.assertEqual(default_baseline["bmb_version"], "v2.2.2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
