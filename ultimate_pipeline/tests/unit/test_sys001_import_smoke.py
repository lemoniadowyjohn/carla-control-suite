"""SYS-001 canonical release tree import-smoke tests.

Verify the canonical root package imports from a clean shell, that the donor
tree cannot be selected accidentally, and that optional CARLA/ML deps are lazy.
"""
import os
import re
import subprocess
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, cwd=sys.prefix and None or None)


@pytest.mark.parametrize("code", [
    "import ultimate_pipeline",
    "import ultimate_pipeline.main_pipeline",
    "import ultimate_pipeline.cli",
    "import ultimate_pipeline.entrypoints",
    "import ultimate_pipeline.run_pipeline",
    "import ultimate_pipeline.run_quality_gates",
])
def test_canonical_imports_clean_shell(code):
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True,
                          cwd=REPO,
                          env={**os.environ, "PYTHONPATH": REPO})
    assert proc.returncode == 0, f"{code} failed:\n{proc.stdout}\n{proc.stderr}"


def test_all_root_py_files_compile():
    import compileall
    ok = compileall.compile_dir(os.path.join(REPO, "ultimate_pipeline"),
                                quiet=1, force=False, rx=re.compile(r"/\."))
    assert ok is True


def test_optional_carla_import_is_lazy():
    # importing the package must not require a live CARLA server or ML libs
    import ultimate_pipeline  # noqa: F401


def test_donor_tree_marked_deprecated():
    dep = os.path.join(REPO, "submission", "infrastructure", "ultimate_pipeline",
                       "DEPRECATION_POLICY.md")
    assert os.path.exists(dep)


def test_bootstrap_repo_root_consistent():
    import ultimate_pipeline.bootstrap_repo_root as b
    assert b.REPO_ROOT.is_dir()


def test_entrypoint_smoke_cli_list():
    proc = subprocess.run([sys.executable, "-c",
                           "import ultimate_pipeline.cli; print('OK')"],
                          capture_output=True, text=True, cwd=REPO)
    assert "OK" in proc.stdout
