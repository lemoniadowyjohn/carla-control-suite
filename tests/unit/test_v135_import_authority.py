"""F15 packaging/sparse-checkout/import-authority classification tests (V135)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_optional_carla_api_is_tracked_and_present_in_checkout():
    # Prior audits flagged missing carla_api in sparse checkouts as an import
    # issue; classify correctly: tracked source file vs sparse omission vs optional
    # runtime dependency on the CARLA Python package.
    tracked = _git("ls-files", "--", "ultimate_pipeline/optional/carla_api.py")
    assert tracked.returncode == 0
    assert "ultimate_pipeline/optional/carla_api.py" in tracked.stdout.splitlines()

    path = REPO_ROOT / "ultimate_pipeline" / "optional" / "carla_api.py"
    assert path.is_file(), (
        "tracked module missing from this checkout; classify as sparse-checkout omission, "
        "not a packaging/source defect"
    )

    spec = importlib.util.find_spec("ultimate_pipeline.optional.carla_api")
    assert spec is not None and spec.origin is not None
    assert Path(spec.origin).resolve() == path.resolve()


def test_pyproject_declares_ultimate_pipeline_package():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "ultimate-pipeline"' in pyproject
    assert 'include = ["ultimate_pipeline*"' in pyproject


def test_optional_carla_runtime_dependency_is_not_a_source_import_failure():
    # The module itself must be importable without the CARLA wheel; only probing
    # CARLA availability/import should depend on the optional runtime package.
    spec = importlib.util.find_spec("ultimate_pipeline.optional.carla_api")
    assert spec is not None
    # Import should not raise merely because CARLA is unavailable in this env.
    mod = importlib.import_module("ultimate_pipeline.optional.carla_api")
    assert hasattr(mod, "get_carla") and hasattr(mod, "carla_available")
    # carla_available() returning False indicates missing optional CARLA package,
    # not a broken repository/package layout.
    _ = mod.carla_available()
