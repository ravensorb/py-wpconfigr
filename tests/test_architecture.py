"""
Architecture contract tests.

Each derives its scope by walking the package rather than from a hand-kept list,
so a module added later cannot quietly escape the rule.
"""

import ast
import pathlib
from collections.abc import Iterator

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "src"
NAMESPACE = "wp"
PACKAGE = SRC / "l3io" / NAMESPACE / "config"

# A rename that misses this file must FAIL, not skip. The path used to be built
# from separate quoted segments, so a search-and-replace over "l3io/wp" never
# reached it: PACKAGE silently pointed at a directory that did not exist, the
# parametrised AD-1 tests got an empty parameter set and pytest SKIPPED them, and
# the AD-27 assertion below started checking a path that cannot exist. Ten tests
# vanished with zero failures.
assert PACKAGE.is_dir(), f"PACKAGE does not exist: {PACKAGE} — did the namespace change?"

INWARD_ONLY = ("core", "domain")
OUTWARD_LAYERS = ("ports", "adapters", "cli")


def _modules(*relative: str) -> Iterator[pathlib.Path]:
    for part in relative:
        found = sorted((PACKAGE / part).rglob("*.py"))
        assert found, f"no modules under {PACKAGE / part} — an empty scope skips, not fails"
        yield from found


def test_no_init_marker_at_either_namespace_level():
    """
    AD-27: an `__init__.py` at l3io/ or l3io/wp/ makes this a regular package,
    shadows the PEP 420 namespace, and makes the sibling distributions
    unimportable -- while this package's own tests still pass.
    """
    assert not (SRC / "l3io" / "__init__.py").exists()
    assert not (SRC / "l3io" / NAMESPACE / "__init__.py").exists()


def test_the_only_init_files_live_at_or_below_the_area_package():
    found = {p.relative_to(SRC).as_posix() for p in SRC.rglob("__init__.py")}
    escaped = {p for p in found if not p.startswith("l3io/wp/config/")}
    assert not escaped, f"__init__.py outside the area package: {escaped}"


@pytest.mark.parametrize("module", list(_modules(*INWARD_ONLY)), ids=lambda p: p.name)
def test_the_functional_core_imports_no_outward_layer(module):
    """AD-1: core/ and domain/ never import ports/, adapters/ or cli/."""
    tree = ast.parse(module.read_text(), filename=str(module))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    for name in imported:
        for layer in OUTWARD_LAYERS:
            assert f"l3io.wp.config.{layer}" not in name, (
                f"{module.name} imports {name}, which is outward of it"
            )


@pytest.mark.parametrize("module", list(_modules(*INWARD_ONLY)), ids=lambda p: p.name)
def test_the_functional_core_performs_no_io(module):
    """
    AD-1 again. An import-linter contract cannot see builtins, so `open` is
    checked here by AST rather than assumed covered.
    """
    forbidden_modules = {"os", "pathlib", "shutil", "subprocess", "socket", "tempfile"}
    tree = ast.parse(module.read_text(), filename=str(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_modules, (
                    f"{module.name} imports the I/O module {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_modules, (
                f"{module.name} imports from the I/O module {node.module}"
            )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open", f"{module.name} calls open()"


def test_the_package_declares_no_runtime_dependencies():
    """AD-2: zero runtime dependencies, permanently."""
    import tomllib

    pyproject = REPO / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    assert data["project"]["dependencies"] == []
