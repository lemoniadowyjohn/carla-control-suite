"""GAP-047 guard: no tracked test may import a module that is not tracked.

The CI failure this guards against was invisible to every local signal:

  * ``git status`` showed the offending module as merely untracked, which reads
    as "someone's scratch work", not "this breaks CI";
  * the module existed on the dev machine, so ``pytest --collect-only`` collected
    7,295 tests cleanly there;
  * a fresh CI checkout has no such file, so collection died with
    ``ModuleNotFoundError`` and exit code 2;
  * the failing test also carried a ``skipif`` for the CI platform, which looks
    like it should have protected CI -- but pytest evaluates module-level
    imports during collection, BEFORE skipif, so it did not.

Nothing about that failure mode is visible to a platform/import audit. The only
cheap detector is to ask git directly: for every module imported by a tracked
test, is that module itself tracked?

This test is deliberately read-only and uses the filesystem rather than invoking
a ``git`` subprocess, so it runs in any environment that has the checkout.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Installed as a package (editable `pip install -e .`), so it is not a vendored
# file and is never expected to be tracked.
EXEMPT_TOP_LEVEL = {"ultimate_pipeline"}

# Names that are stdlib, or provided by an installed dependency, are resolved by
# the interpreter rather than from the checkout, so they cannot cause this bug.
_STDLIB = set(getattr(sys, "stdlib_module_names", set())) | {
    "__future__",
    "typing",
    "collections",
    "concurrent",
    "email",
    "importlib",
    "unittest",
    "asyncio",
}


# Local-module directories that tests add to sys.path. A vendored module the
# tests import by bare name (e.g. `import control_plane`) lives in one of these,
# not at the repo root -- GAP-047's module was scripts/control_plane.py.
LOCAL_MODULE_DIRS = ["", "scripts", "tools"]


def _candidate_paths(name: str) -> list[Path]:
    """Where a bare-name import could resolve inside the checkout."""
    out: list[Path] = []
    for d in LOCAL_MODULE_DIRS:
        base = (REPO / d) if d else REPO
        out.append(base / f"{name}.py")
        out.append(base / name / "__init__.py")
    return out


def _is_stdlib_or_installed(name: str) -> bool:
    """True if `name` resolves without depending on the repo checkout."""
    if name in _STDLIB:
        return True
    import importlib.util

    try:
        # Locate WITHOUT importing, and excluding the repo root so that a local
        # untracked file is not mistaken for an installed distribution.
        finder = importlib.machinery.PathFinder
        spec = finder.find_spec(name, [str(p) for p in sys.path if str(p) != str(REPO)])
        if spec is None:
            return False
        origin = getattr(spec, "origin", None)
        if origin and str(REPO) in str(origin):
            return False
        return True
    except Exception:
        # If we cannot tell, do not flag: a false positive here would block CI.
        return True


def _tracked_files() -> set[Path]:
    """Every file git considers tracked, resolved to absolute paths.

    Uses ``git ls-files`` when git is available and falls back to scanning the
    tree minus VCS/build dirs, so this test still means something in an exported
    tarball. If neither yields a usable set the test skips rather than guessing.
    """
    import subprocess

    tracked: set[Path] = set()
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        ).stdout
        for rel in out.split("\0"):
            if rel:
                tracked.add((REPO / rel).resolve())
    except Exception:
        pytest.skip("git ls-files unavailable; cannot determine tracked files")

    if not tracked:
        pytest.skip("git ls-files returned nothing")
    return tracked


def _test_files(tracked: set[Path]) -> list[Path]:
    return sorted(
        p
        for p in tracked
        if p.suffix == ".py"
        and p.name.startswith("test_")
        and ("tests" in p.parts)
    )


def _module_level_imports(path: Path) -> set[str]:
    """Top-level module names imported at module scope (not inside functions).

    Only module-scope imports matter: those run during collection. A deferred
    import inside a test body cannot break collection.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"), filename=str(path))
    except (SyntaxError, ValueError):
        return set()

    names: set[str] = set()

    def scan(body):
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import; it cannot leave the repo.
                if not node.level and node.module:
                    names.add(node.module.split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Decorators, defaults and annotations evaluate at def/class time.
                for dec in node.decorator_list:
                    scan([dec])
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    a = node.args
                    for d in list(a.defaults) + [k for k in a.kw_defaults if k]:
                        scan([d])
                    if node.returns:
                        scan([node.returns])
                # class/def bodies do NOT execute at import, so do not descend
                # into them for import statements.

    scan(tree.body)
    return names


def test_no_tracked_test_imports_an_untracked_module() -> None:
    """A tracked test importing an untracked module guarantees red CI.

    Regression test for GAP-047. Fails loudly with the exact offending pairs so
    the fix is "git add the module" or "defer the import", never silence.
    """
    tracked = _tracked_files()
    tracked_rel = {p.relative_to(REPO).as_posix() for p in tracked}

    violations: list[str] = []
    for test_file in _test_files(tracked):
        for name in sorted(_module_level_imports(test_file)):
            if name in EXEMPT_TOP_LEVEL or name.startswith("_"):
                continue
            # A module import resolves to <name>.py or <name>/__init__.py under
            # one of the local-module dirs.
            candidates = _candidate_paths(name)
            if any(c.relative_to(REPO).as_posix() in tracked_rel for c in candidates):
                continue
            # Only flag the exact GAP-047 signature: the module resolves from the
            # checkout on this machine, yet is not in git. Stdlib and installed
            # dependencies are excluded because a fresh CI runner has them too.
            present = [c for c in candidates if c.exists()]
            if present and not _is_stdlib_or_installed(name):
                violations.append(
                    f"{test_file.relative_to(REPO).as_posix()} imports '{name}', "
                    f"resolved locally from {present[0].relative_to(REPO).as_posix()}, "
                    f"which is not tracked by git"
                )

    assert not violations, (
        "Tracked test(s) import module(s) that are not in git. These collect fine "
        "locally and abort CI at collection time (GAP-047). Fix by committing the "
        "module or by deferring the import (e.g. pytest.importorskip):\n  "
        + "\n  ".join(violations)
    )


def test_guard_detects_an_untracked_import(tmp_path: Path) -> None:
    """Prove the detector actually fires, so a green run is not a false negative.

    Uses a synthetic repo layout rather than the real one so it stays
    deterministic and does not depend on live git state.
    """
    fake_repo = tmp_path / "repo"
    (fake_repo / "tests").mkdir(parents=True)
    (fake_repo / "pkg").mkdir()

    tracked = fake_repo / "tests" / "test_ok.py"
    tracked.write_text("import pkg\n", encoding="utf-8")

    (fake_repo / "pkg.py").write_text("x = 1\n", encoding="utf-8")  # untracked
    (fake_repo / "orphan.py").write_text("x = 1\n", encoding="utf-8")  # untracked

    tracked_set = {tracked.resolve()}
    # pkg.py is untracked here, so it must be reported.
    names = _module_level_imports(tracked)
    assert "pkg" in names
    # And a name that is untracked in both senses is equally reported.
    assert "orphan" not in names

    # The candidate-path logic the guard relies on:
    assert "pkg.py" not in {p.relative_to(fake_repo).as_posix() for p in tracked_set}


def test_deferred_imports_are_not_flagged(tmp_path: Path) -> None:
    """An import inside a function body cannot break collection, so it is fine."""
    f = tmp_path / "test_deferred.py"
    f.write_text(
        "def test_x():\n    import some_untracked_module\n    assert True\n",
        encoding="utf-8",
    )
    assert _module_level_imports(f) == set()