# -*- coding: utf-8 -*-
"""V5 dependency contract tests (NEW-204 / J09 and NEW-205 / J10).

Two things are pinned here:

1. The dependency *profile* files are mutually consistent: the shared base
   declares no OpenCV provider, and the two environment profiles each declare
   exactly one. This makes the `cv2` namespace conflict structurally impossible
   rather than merely discouraged.
2. The distribution metadata is internally consistent and the declared feature
   extras are installable/parseable, so a wheel can no longer pass an import
   smoke test while its feature dependencies are wrong.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


def _repo_root() -> Path:
    # this file lives at <root>/ultimate_pipeline/tests/unit/
    return Path(__file__).resolve().parents[3]


def _req_lines(path: Path) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _parse_pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in _req_lines(path):
        if line.startswith(("-r ", "--")):
            continue
        match = re.match(r"^([A-Za-z0-9._\-]+)\s*==\s*(\S+)$", line)
        assert match, f"unpinned requirement in {path.name}: {line!r}"
        pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


OPENCV_PROVIDERS = {"opencv-python", "opencv-python-headless"}


# ---------------------------------------------------------------------------
# NEW-205: profile separation
# ---------------------------------------------------------------------------


def test_base_profile_declares_no_opencv_provider():
    pins = _parse_pins(_repo_root() / "requirements.txt")
    assert not (set(pins) & OPENCV_PROVIDERS), (
        "the shared base profile must not pin an OpenCV provider; "
        "that choice belongs to an environment profile"
    )


@pytest.mark.parametrize(
    "profile,expected", [("requirements-ci.txt", "opencv-python-headless"),
                         ("requirements-desktop.txt", "opencv-python")]
)
def test_each_environment_profile_declares_exactly_one_provider(profile, expected):
    pins = _parse_pins(_repo_root() / profile)
    present = set(pins) & OPENCV_PROVIDERS
    assert present == {expected}, f"{profile} must pin exactly {expected}, got {sorted(present)}"


def test_no_single_profile_declares_both_opencv_providers():
    for name in ("requirements.txt", "requirements-ci.txt", "requirements-desktop.txt"):
        pins = _parse_pins(_repo_root() / name)
        assert len(set(pins) & OPENCV_PROVIDERS) <= 1, (
            f"{name} pins multiple mutually exclusive cv2 providers: {sorted(set(pins) & OPENCV_PROVIDERS)}"
        )


def test_environment_profiles_include_the_base_layer():
    for name in ("requirements-ci.txt", "requirements-desktop.txt"):
        lines = _req_lines(_repo_root() / name)
        assert any(ln.startswith("-r requirements.txt") for ln in lines), (
            f"{name} must layer on top of requirements.txt"
        )


def test_opencv_provider_versions_are_deliberately_pinned():
    ci = _parse_pins(_repo_root() / "requirements-ci.txt")
    desktop = _parse_pins(_repo_root() / "requirements-desktop.txt")
    assert ci["opencv-python-headless"] == "4.13.0.92"
    assert desktop["opencv-python"] == "4.13.0.92"
    # Deliberate: the two providers are version-aligned so a profile swap does
    # not also change the cv2 API level.


# ---------------------------------------------------------------------------
# the runtime conflict gate
# ---------------------------------------------------------------------------


def test_runtime_conflict_detector_is_reachable():
    from ultimate_pipeline.tools.repo_health import dependency_conflicts

    result = dependency_conflicts()
    assert result["status"] in {"PASS", "FAIL"}
    assert "cv2" in result["groups"]


def test_conflict_detector_flags_both_providers(monkeypatch):
    import ultimate_pipeline.tools.repo_health as rh

    monkeypatch.setattr(
        rh, "_installed_distributions",
        lambda: {"opencv-python": "4.12.0.88", "opencv-python-headless": "4.13.0.92"},
    )
    result = rh.dependency_conflicts()
    assert result["status"] == "FAIL"
    conflict = result["conflicts"][0]
    assert conflict["namespace"] == "cv2"
    assert set(conflict["distributions"]) == OPENCV_PROVIDERS


def test_conflict_detector_passes_with_a_single_provider(monkeypatch):
    import ultimate_pipeline.tools.repo_health as rh

    monkeypatch.setattr(
        rh, "_installed_distributions", lambda: {"opencv-python-headless": "4.13.0.92"}
    )
    result = rh.dependency_conflicts()
    assert result["status"] == "PASS"
    assert result["conflicts"] == []


def test_conflict_detector_normalizes_name_separators(monkeypatch):
    import ultimate_pipeline.tools.repo_health as rh

    monkeypatch.setattr(rh, "_installed_distributions", lambda: {"opencv.python": "1.0"})
    assert rh.dependency_conflicts()["status"] == "PASS"


def test_torch_and_torchvision_are_not_treated_as_conflicting(monkeypatch):
    """torchvision legitimately co-installs with torch; flagging it would be wrong."""
    import ultimate_pipeline.tools.repo_health as rh

    monkeypatch.setattr(
        rh, "_installed_distributions", lambda: {"torch": "2.9.1", "torchvision": "0.24.1"}
    )
    assert rh.dependency_conflicts()["status"] == "PASS"


def test_dependency_conflicts_is_a_required_offline_section():
    from ultimate_pipeline.tools.repo_health import OFFLINE_REQUIRED_SECTIONS

    assert "dependency_conflicts" in OFFLINE_REQUIRED_SECTIONS


def test_health_payload_includes_conflict_section():
    from ultimate_pipeline.tools.repo_health import build_repo_health

    payload = build_repo_health(
        _repo_root(), test_result="PASS", run_pip_check=False, verify_maps=False
    )
    assert "dependency_conflicts" in payload["sections"]


# ---------------------------------------------------------------------------
# NEW-204: distribution metadata contract
# ---------------------------------------------------------------------------


@pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")
def test_core_dependencies_stay_minimal_and_installable_offline():
    data = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
    core = [re.split(r"[<>=!\[]", d)[0].lower().replace("_", "-")
            for d in data["project"]["dependencies"]]
    # The core layer must not drag in compiled/CARLA/perception stacks.
    for forbidden in ("carla", "torch", "opencv-python", "opencv-python-headless",
                      "ultralytics", "torch-geometric", "geopandas", "rasterio"):
        assert forbidden not in core, f"{forbidden} must not be a core dependency"


@pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")
def test_expected_feature_extras_are_declared():
    data = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
    extras = set(data["project"].get("optional-dependencies", {}))
    for expected in ("geometry", "geo", "gnn", "perception", "runtime",
                     "visualization", "full", "test", "dev"):
        assert expected in extras, f"missing declared extra: {expected}"


@pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")
def test_runtime_extra_pins_the_accepted_carla_version():
    data = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = data["project"]["optional-dependencies"]["runtime"]
    assert any(r.lower().startswith("carla") and "0.9.16" in r for r in runtime), (
        "the runtime extra must bind the accepted CARLA build 0.9.16"
    )


@pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")
def test_perception_extra_uses_the_headless_opencv_provider():
    """The wheel extra must not drag the GUI OpenCV build into CI installs."""
    data = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
    perception = data["project"]["optional-dependencies"]["perception"]
    names = [re.split(r"[<>=!\[]", r)[0].lower().replace("_", "-") for r in perception]
    assert "opencv-python-headless" in names
    assert "opencv-python" not in names


@pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")
def test_self_referential_extras_are_wellformed():
    """`full`/`dev` reference this distribution by its own extras, not bare."""
    data = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
    name = data["project"]["name"]
    extras = data["project"]["optional-dependencies"]
    for key in ("full", "dev"):
        for req in extras[key]:
            if req.startswith(f"{name}["):
                inner = req[len(name) + 1:].split("]")[0]
                for referenced in inner.split(","):
                    assert referenced in extras, f"{key} references unknown extra {referenced!r}"


@pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")
def test_installed_metadata_matches_pyproject_extras():
    """The installed distribution must expose the same extras we declare."""
    import importlib.metadata as md

    try:
        dist = md.distribution("ultimate-pipeline")
    except md.PackageNotFoundError:
        pytest.skip("ultimate-pipeline is not installed as a distribution")

    declared = {
        v.strip()
        for v in (dist.metadata.get_all("Provides-Extra") or [])
        if v.strip()
    }
    if not declared:
        pytest.skip("installed distribution predates the V5 extras contract")
    for extra in ("geometry", "runtime", "perception"):
        assert extra in declared, f"installed metadata is missing extra {extra!r}"


# ---------------------------------------------------------------------------
# requirement pinning hygiene across all profiles
# ---------------------------------------------------------------------------


def test_all_profiles_are_fully_pinned():
    for name in ("requirements.txt", "requirements-ci.txt", "requirements-desktop.txt"):
        _parse_pins(_repo_root() / name)  # raises on any unpinned line


def test_base_profile_keeps_its_operational_scale():
    """The base layer still carries the operational environment, minus providers."""
    pins = _parse_pins(_repo_root() / "requirements.txt")
    for required in ("numpy", "carla", "torch", "torchvision", "shapely", "pyproj", "rasterio"):
        assert required in pins, f"base profile lost operational dependency {required}"
