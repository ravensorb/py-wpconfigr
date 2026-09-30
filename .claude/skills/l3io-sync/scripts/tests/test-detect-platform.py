#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""
Tests for detect-platform.py. Run with:
  uv run skills/l3io-sync/scripts/tests/test-detect-platform.py

The CLI cases drive the real script through subprocess against real git repositories, so
the exit code and stdout are the ones /l3io-sync setup actually sees. URL parsing is
also exercised directly, because the shapes that matter (SSH, .git suffix, a host that is
not GitHub) are cheaper to enumerate as data than as twenty throwaway repos.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(os.path.dirname(_HERE), "detect-platform.py")
_SPEC = importlib.util.spec_from_file_location("detect_platform", _SCRIPT)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV,
                          capture_output=True, text=True)


class TestUrlParsing(unittest.TestCase):
    def test_ssh_url_is_normalised_to_owner_and_repo(self):
        r = mod.detect_from_url("git@github.com:ravensorb/bmad-extensions.git")
        self.assertEqual((r["platform"], r["owner"], r["repo"]),
                         ("github", "ravensorb", "bmad-extensions"))
        self.assertEqual(r["remote_url"], "https://github.com/ravensorb/bmad-extensions")

    def test_https_url_with_and_without_git_suffix_agree(self):
        a = mod.detect_from_url("https://github.com/o/r.git")
        b = mod.detect_from_url("https://github.com/o/r")
        self.assertEqual(a, b)
        self.assertEqual(a["platform"], "github")

    def test_http_is_accepted_as_well_as_https(self):
        self.assertEqual(mod.detect_from_url("http://github.com/o/r")["platform"], "github")

    def test_trailing_whitespace_does_not_defeat_the_match(self):
        self.assertEqual(mod.detect_from_url("  https://github.com/o/r\n")["platform"], "github")

    def test_a_non_github_host_is_unknown_and_says_what_to_do(self):
        r = mod.detect_from_url("git@gitlab.com:o/r.git")
        self.assertEqual(r["platform"], "unknown")
        self.assertIn("sync-config.yaml", r["note"])
        self.assertNotIn("owner", r)

    def test_a_deeper_path_is_not_claimed_as_github(self):
        """`$` anchors the repo segment: github.com/o/r/sub is not an owner/repo pair, and
        reporting it as one would put a wrong `repo` into sync-config.yaml."""
        self.assertEqual(mod.detect_from_url("https://github.com/o/r/sub")["platform"], "unknown")


class TestCli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.d, ignore_errors=True))
        git("init", "-q", self.d, cwd=".")

    def run_cli(self, *args):
        r = subprocess.run([sys.executable, _SCRIPT, *args],
                           capture_output=True, text=True, env=GIT_ENV)
        return r.returncode, r.stdout, r.stderr

    def test_origin_is_reported_with_its_remote_name(self):
        git("remote", "add", "origin", "https://github.com/o/r.git", cwd=self.d)
        code, out, err = self.run_cli(self.d)
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual((d["platform"], d["owner"], d["repo"], d["remote_name"]),
                         ("github", "o", "r", "origin"))

    def test_origin_wins_over_upstream(self):
        git("remote", "add", "upstream", "https://github.com/up/stream.git", cwd=self.d)
        git("remote", "add", "origin", "https://github.com/o/r.git", cwd=self.d)
        code, out, _ = self.run_cli(self.d)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["repo"], "r")

    def test_upstream_is_used_when_there_is_no_origin(self):
        git("remote", "add", "upstream", "https://github.com/up/stream.git", cwd=self.d)
        code, out, _ = self.run_cli(self.d)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["remote_name"], "upstream")

    def test_a_remote_named_neither_still_resolves_through_the_fallback(self):
        """The `git remote -v` fallback is the only path that reads an arbitrary remote
        name, and nothing else in the suite reaches it."""
        git("remote", "add", "fork", "https://github.com/f/k.git", cwd=self.d)
        code, out, err = self.run_cli(self.d)
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual((d["remote_name"], d["repo"]), ("fork", "k"))

    def test_no_remote_at_all_fails_and_names_the_fix(self):
        code, out, err = self.run_cli(self.d)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("git remote add origin", err)

    def test_a_missing_project_root_fails_rather_than_scanning_the_cwd(self):
        code, _, err = self.run_cli(os.path.join(self.d, "nope"))
        self.assertEqual(code, 1)
        self.assertIn("project-root not found", err)


if __name__ == "__main__":
    unittest.main(verbosity=1)
