#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""Unit tests for init-sanctum.py."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent / "init-sanctum.py"
_spec = importlib.util.spec_from_file_location("init_sanctum", _SCRIPT)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


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
    _RUN_TMP = tempfile.mkdtemp(prefix="test-init-sanctum-")
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


# A stand-in for BMad core's resolver, at the path config-resolution.md §2 fixes it to. It is a
# real script run as a real subprocess, so these tests drive the same code path a real project
# does -- argv, exit code, stdout, JSON parse -- rather than a patched-out function whose
# contract only this test believes in.
#
# Built from escaped-newline literals rather than a `"""..."""` block: a triple-quoted string
# puts its own `# /// script` / `# ///` lines at column 0 of THIS file's real source text, which
# a PEP 723 metadata scanner reads no differently than this file's own header above -- it does
# not know Python string-literal syntax, only line patterns. That reads as two metadata blocks
# in one script and `uv run test-init-sanctum.py` (this test, run directly, as CI runs it)
# refuses with "multiple PEP 723 metadata blocks" before a single test executes. Escaped `\n`
# keeps the header text identical once written to the stub file on disk, while every line of
# this file's own source stays indented past column 0 and inside quotes, so it cannot itself
# match `^# ///`. `test_a_failing_resolver_warns` below already uses this form for the same
# reason.
_STUB_RESOLVER = (
    "#!/usr/bin/env python3\n"
    "# /// script\n"
    "# requires-python = \">=3.9\"\n"
    "# ///\n"
    "import json, sys\n"
    "print(json.dumps({\"core\": {\"user_name\": \"Alice\", \"communication_language\": \"Welsh\"}}))\n"
)


def _install_stub_resolver(project_root: Path, body: str = _STUB_RESOLVER) -> Path:
    resolver = project_root / m.RESOLVER_REL
    resolver.parent.mkdir(parents=True, exist_ok=True)
    resolver.write_text(body)
    resolver.chmod(0o755)
    return resolver


class TestResolveCoreConfig(unittest.TestCase):
    """The config contract: four TOML layers via BMad core's resolver, never a config.yaml.

    The script used to read `_bmad/config.yaml` and `_bmad/config.user.yaml` through a
    hand-written line-splitter. Neither file has existed since the TOML migration, so the read
    was a permanent no-op and every sanctum silently took the hardcoded defaults. These tests
    pin the replacement, INCLUDING that a config.yaml is not consulted.
    """

    def test_reads_the_resolver_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            _install_stub_resolver(project_root)
            warnings = []
            config = m.resolve_core_config(project_root, warnings)
            self.assertEqual(config.get("user_name"), "Alice")
            self.assertEqual(config.get("communication_language"), "Welsh")
            self.assertEqual(warnings, [])

    def test_accepts_a_bare_core_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            _install_stub_resolver(project_root, _STUB_RESOLVER.replace(
                '{"core": {"user_name": "Alice", "communication_language": "Welsh"}}',
                '{"user_name": "Bob", "communication_language": "Welsh"}'))
            warnings = []
            self.assertEqual(m.resolve_core_config(project_root, warnings).get("user_name"), "Bob")
            self.assertEqual(warnings, [])

    def test_missing_resolver_warns_rather_than_defaulting_in_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            warnings = []
            config = m.resolve_core_config(Path(tmp), warnings)
            self.assertEqual(config, {})
            self.assertEqual(len(warnings), 1)
            self.assertIn("config resolver is not installed", warnings[0])

    def test_a_failing_resolver_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            _install_stub_resolver(project_root, "#!/usr/bin/env python3\n"
                                   "# /// script\n# requires-python = \">=3.9\"\n# ///\n"
                                   "import sys\nsys.stderr.write('boom\\n')\nsys.exit(1)\n")
            warnings = []
            self.assertEqual(m.resolve_core_config(project_root, warnings), {})
            self.assertEqual(len(warnings), 1)
            self.assertIn("could not resolve config", warnings[0])

    def test_a_config_yaml_is_not_a_config_source(self):
        """The regression itself: a `_bmad/config.yaml` on disk must change nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            (project_root / "_bmad").mkdir(parents=True)
            (project_root / "_bmad" / "config.yaml").write_text("user_name: Mallory\n")
            (project_root / "_bmad" / "config.user.yaml").write_text("user_name: Mallory\n")
            _install_stub_resolver(project_root)
            warnings = []
            config = m.resolve_core_config(project_root, warnings)
            self.assertEqual(config.get("user_name"), "Alice",
                             "config.yaml must not be read; the resolver is the only source")

    def test_the_hand_rolled_yaml_reader_is_gone(self):
        """Global rule 1: no hand-written parser. Re-adding one must fail here."""
        self.assertFalse(hasattr(m, "parse_yaml_config"),
                         "parse_yaml_config was removed with the config.yaml read; a "
                         "hand-written YAML reader must not come back")


class TestParseFrontmatter(unittest.TestCase):
    def test_extracts_fields(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nname: test-cap\ncode: TC\ndescription: A test capability\n---\n\n# Body\n")
            path = Path(f.name)
            self.addCleanup(path.unlink, missing_ok=True)
        result = m.parse_frontmatter(path)
        self.assertEqual(result["name"], "test-cap")
        self.assertEqual(result["code"], "TC")

    def test_no_frontmatter_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# No frontmatter here\n")
            path = Path(f.name)
            self.addCleanup(path.unlink, missing_ok=True)
        result = m.parse_frontmatter(path)
        self.assertEqual(result, {})


class TestSubstituteVars(unittest.TestCase):
    def test_replaces_placeholders(self):
        result = m.substitute_vars("Hello {user_name}, born {birth_date}", {"user_name": "Alice", "birth_date": "2026-01-01"})
        self.assertEqual(result, "Hello Alice, born 2026-01-01")

    def test_unknown_placeholder_left_intact(self):
        result = m.substitute_vars("Hello {unknown}", {"user_name": "Alice"})
        self.assertIn("{unknown}", result)


class TestGenerateCapabilitiesMd(unittest.TestCase):
    def test_generates_table_rows(self):
        caps = [{"code": "SM", "name": "Scope Mapping", "description": "Maps attack surface", "source": "references/scope-mapping.md"}]
        output = m.generate_capabilities_md(caps)
        self.assertIn("SM", output)
        self.assertIn("Scope Mapping", output)
        self.assertIn("WebSearch", output)


class TestDiscoverCapabilities(unittest.TestCase):
    def test_discovers_capability_with_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            cap = Path(d) / "scope-mapping.md"
            cap.write_text("---\nname: scope-mapping\ncode: SM\ndescription: Maps attack surface\n---\n\n# Body\n")
            result = m.discover_capabilities(Path(d), "./references")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "SM")

    def test_ignores_files_without_code(self):
        with tempfile.TemporaryDirectory() as d:
            cap = Path(d) / "notes.md"
            cap.write_text("---\nname: notes\n---\n\n# Body\n")
            result = m.discover_capabilities(Path(d), "./references")
        self.assertEqual(len(result), 0)


class TestSanctumCreation(unittest.TestCase):
    def test_creates_sanctum_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            skill_path = Path(tmp) / "skill"

            # Minimal skill structure
            (skill_path / "assets").mkdir(parents=True)
            (skill_path / "references").mkdir()

            # Stub template carrying a placeholder, to verify substitution happens
            (skill_path / "assets" / "INDEX-template.md").write_text("# Index\n{user_name}\n")

            # A capability reference file, to verify copy_references runs for real
            (skill_path / "references" / "scope-mapping.md").write_text(
                "---\nname: scope-mapping\ncode: SM\ndescription: Maps attack surface\n---\n\n# Body\n"
            )

            # Project config, supplied the one documented way: BMad core's resolver at its
            # fixed path, run as a real subprocess.
            (project_root / "_bmad").mkdir(parents=True)
            _install_stub_resolver(project_root)

            sanctum = project_root / "_bmad" / "memory" / m.SKILL_NAME
            self.assertFalse(sanctum.exists(), "sanctum must not exist before main() runs")

            # Patch TEMPLATE_FILES for this test (the fixture only stubs INDEX)
            original = m.TEMPLATE_FILES
            m.TEMPLATE_FILES = ["INDEX-template.md"]
            saved_argv = sys.argv
            sys.argv = ["init-sanctum.py", str(project_root), str(skill_path), "--json"]
            stdout = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout):
                    m.main()
            finally:
                m.TEMPLATE_FILES = original
                sys.argv = saved_argv

            # main() reports the run it actually performed
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "created")
            self.assertEqual(result["warnings"], [],
                             "a resolvable config must produce no personalisation warning")
            self.assertIn("INDEX.md", result["created"])
            self.assertIn("references/scope-mapping.md", result["created"])

            # The sanctum now exists on disk, with the subdirectories First Breath promises
            self.assertTrue(sanctum.is_dir())
            self.assertTrue((sanctum / "sessions").is_dir())
            self.assertTrue((sanctum / "research-cache").is_dir())

            # The template landed and its placeholder was substituted
            index_content = (sanctum / "INDEX.md").read_text()
            self.assertIn("Alice", index_content)
            self.assertNotIn("{user_name}", index_content)

            # The reference file was copied into the sanctum, unmodified
            self.assertEqual(
                (sanctum / "references" / "scope-mapping.md").read_text(),
                (skill_path / "references" / "scope-mapping.md").read_text(),
            )


if __name__ == "__main__":
    unittest.main()
