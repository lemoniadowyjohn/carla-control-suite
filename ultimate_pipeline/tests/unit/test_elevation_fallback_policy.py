# F2 — strict fallback policy: elevation values must come from the DEM,
# never invented via NN extrapolation, graph propagation, median, hardcoded
# constants, or flat samplers.
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.enrichment.elevation_fallback_policy import (
    assert_no_fallback_violations,
    elevation_fallback_policy,
    fallback_kind_violations,
)
from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter

REPO_ROOT = Path(__file__).resolve().parents[2]


def _disable_thesis_strict(monkeypatch):
    monkeypatch.delenv("UP_THESIS_STRICT", raising=False)
    from ultimate_pipeline.config.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "THESIS_STRICT", False)


def _xodr_with_roads(n: int) -> ET.Element:
    root = ET.Element("OpenDRIVE", {"version": "1.4"})
    for i in range(n):
        road = ET.SubElement(
            root,
            "road",
            {"id": str(i), "length": "10.0", "junction": "-1"},
        )
        pv = ET.SubElement(road, "planView")
        g = ET.SubElement(
            pv,
            "geometry",
            {
                "s": "0.0",
                "x": f"{float(i) * 20.0:.3f}",
                "y": "0.0",
                "hdg": "0.0",
                "length": "10.0",
            },
        )
        ET.SubElement(g, "line")
    return root


def _always_valid_sampler(x, y):
    return 100.0 + y / 1000.0, True


def _never_valid_sampler(x, y):
    return None, False


class TestFallbackPolicyResolution:
    def test_default_is_strict(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        assert elevation_fallback_policy() == "strict"

    def test_explicit_lenient(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "lenient")
        assert elevation_fallback_policy() == "lenient"


class TestFallbackKinds:
    def test_classification(self):
        v = fallback_kind_violations(
            extrapolated_road_ids=["2", "1"],
            propagated_road_ids=["1"],
            unresolved_road_ids=["3"],
            flat_sampler_active=True,
        )
        assert v["extrapolated"] == ["1", "2"]
        assert v["propagated"] == ["1"]
        assert v["median_or_hardcoded"] == ["3"]
        assert v["flat_sampler"] == ["__flat_sampler__"]
        assert v["all_forbidden"] == ["1", "2", "3", "__flat_sampler__"]

    def test_no_violations_when_clean(self):
        v = fallback_kind_violations()
        assert v["all_forbidden"] == []


class TestAssertNoFallbackViolations:
    def test_raises_on_extrapolation_in_strict(self):
        with pytest.raises(RuntimeError, match="F2"):
            assert_no_fallback_violations(extrapolated_road_ids=["1"])

    def test_raises_on_propagation_in_strict(self):
        with pytest.raises(RuntimeError, match="F2"):
            assert_no_fallback_violations(propagated_road_ids=["1"])

    def test_raises_on_median_or_hardcoded_in_strict(self):
        with pytest.raises(RuntimeError, match="F2"):
            assert_no_fallback_violations(unresolved_road_ids=["1"])

    def test_raises_on_flat_sampler_in_strict(self):
        with pytest.raises(RuntimeError, match="F2"):
            assert_no_fallback_violations(flat_sampler_active=True)

    def test_passes_when_clean(self):
        rec = assert_no_fallback_violations()
        assert rec["passed"] is True
        assert rec["violation_count"] == 0

    def test_lenient_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "lenient")
        rec = assert_no_fallback_violations(extrapolated_road_ids=["1"])
        assert rec["passed"] is False
        assert rec["violation_count"] == 1


class TestApplyDemFallbackGate:
    def test_direct_dem_sampling_no_violation(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(3)
        qc = ElevationImporter.apply_dem(root, _always_valid_sampler, collect_qc=True)
        assert qc is not None
        assert qc["f2_fallback_gate_passed"] is True
        assert qc["f2_fallback_violation_count"] == 0

    def test_nodata_road_fails_closed_in_strict(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        with pytest.raises(RuntimeError, match="F2"):
            ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)

    def test_nodata_road_reports_violations_in_lenient(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "lenient")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        qc = ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)
        assert qc["f2_fallback_gate_passed"] is False
        assert qc["f2_fallback_violation_count"] >= 1
        assert "0" in qc["f2_fallback_violations"]["all_forbidden"]


def _sampler_valid_start_only():
    """Valid at the road start (0,0); invalid everywhere else (endpoint no-data)."""
    def _sampler(x, y):
        if abs(x) < 5.0 and abs(y) < 5.0:
            return 100.0, True
        return None, False
    return _sampler


def _xodr_linked(n: int) -> ET.Element:
    """Roads 0..n-1 in a chain: road i+1 precedes road i."""
    root = _xodr_with_roads(n)
    roads = root.findall("road")
    for i in range(1, n):
        link = ET.SubElement(roads[i], "link")
        pred = ET.SubElement(link, "predecessor", {"elementType": "road", "elementId": str(i - 1)})
    return root


class TestEndpointNoData:
    def test_endpoint_nodata_fails_closed_in_strict(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        with pytest.raises(RuntimeError, match="F2"):
            ElevationImporter.apply_dem(
                root, _sampler_valid_start_only(), collect_qc=True, linear_grade=True
            )
        assert root.findall("road/elevationProfile") == []

    def test_endpoint_nodata_recorded_and_not_mutated_in_audit(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "audit")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        qc = ElevationImporter.apply_dem(
            root, _sampler_valid_start_only(), collect_qc=True, linear_grade=True
        )
        assert qc["endpoint_nodata_road_ids"] == ["0"]
        assert qc["f2_fallback_violation_count"] >= 1
        assert root.findall("road/elevationProfile") == []

    def test_endpoint_nodata_lenient_applies_flat(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "lenient")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        qc = ElevationImporter.apply_dem(
            root, _sampler_valid_start_only(), collect_qc=True, linear_grade=True
        )
        assert "0" in qc["f2_fallback_violations"]["endpoint_nodata"]


class TestAuditMode:
    def test_audit_records_violations_without_mutating(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "audit")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(2)
        qc = ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)
        assert qc["f2_fallback_gate_passed"] is False
        assert qc["f2_fallback_violation_count"] == 2
        assert "0" in qc["f2_fallback_violations"]["median_or_hardcoded"]
        assert root.findall("road/elevationProfile") == []

    def test_audit_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "audit")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        qc = ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)
        assert qc is not None

    def test_audit_collect_qc_false_returns_none(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "audit")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        result = ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=False)
        assert result is None


class TestForbiddenFallbackReachability:
    """Each forbidden fallback kind must be recorded and unreachable in strict."""

    @staticmethod
    def _valid_then_nodata_sampler():
        def _sampler(x, y):
            if abs(x) < 5.0:
                return 100.0, True
            return None, False
        return _sampler

    def test_nearest_neighbour_unreachable_in_strict(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(2)
        with pytest.raises(RuntimeError, match="F2"):
            ElevationImporter.apply_dem(
                root, self._valid_then_nodata_sampler(), collect_qc=True
            )
        assert root.findall("road/elevationProfile") == []

    def test_graph_propagation_unreachable_in_strict(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        monkeypatch.setenv("UP_ELEV_EXTRAPOLATION_MAX_DIST_M", "0")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_linked(2)
        with pytest.raises(RuntimeError, match="F2"):
            ElevationImporter.apply_dem(
                root, self._valid_then_nodata_sampler(), collect_qc=True
            )

    def test_median_fallback_unreachable_in_strict(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        monkeypatch.setenv("UP_ELEV_EXTRAPOLATION_MAX_DIST_M", "0")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(2)
        with pytest.raises(RuntimeError, match="F2"):
            ElevationImporter.apply_dem(
                root, self._valid_then_nodata_sampler(), collect_qc=True
            )

    def test_hardcoded_375_unreachable_in_strict(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        with pytest.raises(RuntimeError, match="F2"):
            ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)
        assert root.findall("road/elevationProfile") == []
        serialized = ET.tostring(root, encoding="unicode")
        assert "375.0" not in serialized
        assert "375.000" not in serialized

    def test_hardcoded_375_reachable_only_in_lenient(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "lenient")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        qc = ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)
        assert "0" in qc["f2_fallback_violations"]["median_or_hardcoded"]
        elev = root.find("road/elevationProfile/elevation")
        assert float(elev.get("a")) == 375.0

    def test_nearest_neighbour_reachable_only_in_lenient(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "lenient")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(2)
        qc = ElevationImporter.apply_dem(
            root, self._valid_then_nodata_sampler(), collect_qc=True
        )
        assert "1" in qc["extrapolated_road_ids"]
        assert root.find("road/elevationProfile") is not None

    def test_graph_propagation_reachable_only_in_lenient(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "lenient")
        monkeypatch.setenv("UP_ELEV_EXTRAPOLATION_MAX_DIST_M", "0")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_linked(2)
        qc = ElevationImporter.apply_dem(
            root, self._valid_then_nodata_sampler(), collect_qc=True
        )
        assert "1" in qc["propagated_road_ids"]

    def test_violation_counts_deterministic(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "audit")
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(5)
        first = ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)
        second = ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)
        assert first["f2_fallback_violation_count"] == second["f2_fallback_violation_count"] == 5
        assert first["f2_fallback_violations"] == second["f2_fallback_violations"]

    def test_strict_inserts_no_forbidden_values(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        _disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(3)
        with pytest.raises(RuntimeError, match="F2"):
            ElevationImporter.apply_dem(
                root, self._valid_then_nodata_sampler(), collect_qc=True
            )
        for road in root.findall("road"):
            assert road.find("elevationProfile") is None


class TestEnvironmentVariableSubprocesses:
    """UP_ELEVATION_FALLBACK_POLICY is read dynamically at call time; verify
    in fresh interpreters because SETTINGS is constructed at import time."""

    @staticmethod
    def _run_snippet(code: str, env: dict) -> str:
        import os as _os
        import subprocess
        import sys as _sys

        repo = Path(__file__).resolve().parents[2]
        full_env = dict(_os.environ)
        full_env.pop("UP_ELEVATION_FALLBACK_POLICY", None)
        full_env["PYTHONPATH"] = str(repo) + _os.pathsep + full_env.get("PYTHONPATH", "")
        full_env.update(env)
        proc = subprocess.run(
            [_sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=full_env,
            cwd=str(repo),
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()

    def test_env_set_before_import_strict(self):
        out = self._run_snippet(
            "import os; os.environ['UP_ELEVATION_FALLBACK_POLICY']='strict'; "
            "import sys; sys.path.insert(0, '.'); "
            "from ultimate_pipeline.enrichment.elevation_fallback_policy import elevation_fallback_policy; "
            "print(elevation_fallback_policy())",
            {},
        )
        assert out == "strict"

    def test_env_set_before_import_audit(self):
        out = self._run_snippet(
            "import os; os.environ['UP_ELEVATION_FALLBACK_POLICY']='audit'; "
            "import sys; sys.path.insert(0, '.'); "
            "from ultimate_pipeline.enrichment.elevation_fallback_policy import elevation_fallback_policy; "
            "print(elevation_fallback_policy())",
            {},
        )
        assert out == "audit"

    def test_env_set_after_import_takes_effect(self):
        # F2 policy is read dynamically (sole authority), so setting the env
        # var after the settings import still changes the resolved policy.
        out = self._run_snippet(
            "import sys; sys.path.insert(0, '.'); "
            "import ultimate_pipeline.config.settings; "
            "import os; os.environ['UP_ELEVATION_FALLBACK_POLICY']='audit'; "
            "from ultimate_pipeline.enrichment.elevation_fallback_policy import elevation_fallback_policy; "
            "print(elevation_fallback_policy())",
            {},
        )
        assert out == "audit"

    def test_default_strict_in_fresh_interpreter(self):
        out = self._run_snippet(
            "import sys; sys.path.insert(0, '.'); "
            "from ultimate_pipeline.enrichment.elevation_fallback_policy import elevation_fallback_policy; "
            "print(elevation_fallback_policy())",
            {},
        )
        assert out == "strict"


def _os_pathsep() -> str:
    import os as _os

    return _os.pathsep
