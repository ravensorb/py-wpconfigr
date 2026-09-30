#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""
Tests for check-pm-status.py. Run with:
  uv run skills/l3io-doctor/scripts/tests/test-check-pm-status.py

Every CLI case drives the real script through subprocess against a real installed copy --
a stub at {project-root}/_bmad/scripts/pm-status.py that prints the version the case needs
-- so the exit code is the one /l3io-doctor check-pm-status actually returns. The exit
codes are the whole interface here (0 current, 3 stale, 4 absent, 2 unreadable), so each
gets a case; asserting only on stdout would let any of them drift to 0 unnoticed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(os.path.dirname(_HERE), "check-pm-status.py")
_SPEC = importlib.util.spec_from_file_location("check_pm_status", _SCRIPT)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

STUB = '#!/usr/bin/env python3\n# /// script\n# requires-python = ">=3.11"\n# ///\nprint("{v}")\n'


class TestParseVersion(unittest.TestCase):
    def test_a_bare_version_and_a_prefixed_one_agree(self):
        self.assertEqual(mod._parse_version("2.5.2"), (2, 5, 2))
        self.assertEqual(mod._parse_version("pm-status.py 2.5.2"), (2, 5, 2))

    def test_two_and_four_component_versions_both_parse(self):
        self.assertEqual(mod._parse_version("3.1"), (3, 1))
        self.assertEqual(mod._parse_version("3.1.2.4"), (3, 1, 2, 4))

    def test_garbage_is_none_rather_than_a_guess(self):
        for bad in ("", "unknown", "vNext", None):
            self.assertIsNone(mod._parse_version(bad), bad)

    def test_ordering_is_numeric_not_lexicographic(self):
        """'3.1.10' vs '3.1.9': a string compare calls 10 older than 9 and would report a
        current copy as stale on the tenth patch of any minor."""
        self.assertGreater(mod._parse_version("3.1.10"), mod._parse_version("3.1.9"))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.expected = mod._expected_version()
        self.assertIsNotNone(self.expected, "premise: the doctor's module.yaml is readable")

    def install(self, version: str):
        p = Path(self.d) / "_bmad" / "scripts"
        p.mkdir(parents=True, exist_ok=True)
        f = p / "pm-status.py"
        f.write_text(STUB.format(v=version), encoding="utf-8")
        f.chmod(0o755)

    def run_cli(self, *extra):
        r = subprocess.run([sys.executable, _SCRIPT, "--project-root", self.d, *extra],
                           capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def test_absent_is_exit_4_and_names_the_fix(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 4)
        self.assertIn("absent", out)
        self.assertIn("self-install runs at", out)

    def test_matching_version_is_exit_0(self):
        self.install(self.expected)
        code, out, err = self.run_cli()
        self.assertEqual(code, 0, err)
        self.assertIn("current", out)

    def test_an_older_installed_copy_is_exit_3(self):
        self.install("0.0.1")
        code, out, _ = self.run_cli()
        self.assertEqual(code, 3)
        self.assertIn("stale", out)

    def test_a_newer_installed_copy_is_accepted_not_flagged(self):
        """Self-install refuses to downgrade, so a newer copy is a tester on an unreleased
        build, not a fault. Reporting it stale would send them to a 'fix' that cannot work."""
        self.install("999.0.0")
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("current", out)

    def test_a_version_banner_rather_than_a_bare_number_still_compares(self):
        self.install(f"pm-status.py {self.expected}")
        code, _, _ = self.run_cli()
        self.assertEqual(code, 0)

    def test_json_format_carries_status_expected_and_installed(self):
        self.install("0.0.1")
        code, out, _ = self.run_cli("--format", "json")
        self.assertEqual(code, 3)
        d = json.loads(out)
        self.assertEqual(d["status"], "stale")
        self.assertEqual(d["expected"], self.expected)
        self.assertIn("0.0.1", d["installed"])

    def test_json_absent_reports_installed_null(self):
        code, out, _ = self.run_cli("--format", "json")
        self.assertEqual(code, 4)
        d = json.loads(out)
        self.assertEqual((d["status"], d["installed"]), ("absent", None))

    def test_project_root_is_required(self):
        r = subprocess.run([sys.executable, _SCRIPT], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_an_unreadable_module_yaml_is_exit_2_not_a_false_current(self):
        """The one case that must never degrade to 0: with no expected version there is
        nothing to compare against, and saying 'current' would be an unfounded all-clear."""
        self.install(self.expected)
        env = {**os.environ}
        r = subprocess.run(
            [sys.executable, "-c",
             "import importlib.util,sys;"
             f"s=importlib.util.spec_from_file_location('m',{_SCRIPT!r});"
             "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
             "m._MODULE_YAML=__import__('pathlib').Path('/nonexistent/module.yaml');"
             f"sys.exit(m.main(['--project-root',{self.d!r}]))"],
            capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot read module_version", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
