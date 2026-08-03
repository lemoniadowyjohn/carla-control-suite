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
    @staticmethod
    def _disable_thesis_strict(monkeypatch):
        monkeypatch.delenv("UP_THESIS_STRICT", raising=False)
        from ultimate_pipeline.config.settings import SETTINGS

        monkeypatch.setattr(SETTINGS, "THESIS_STRICT", False)

    def test_direct_dem_sampling_no_violation(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        self._disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(3)
        qc = ElevationImporter.apply_dem(root, _always_valid_sampler, collect_qc=True)
        assert qc is not None
        assert qc["f2_fallback_gate_passed"] is True
        assert qc["f2_fallback_violation_count"] == 0

    def test_nodata_road_fails_closed_in_strict(self, monkeypatch):
        monkeypatch.delenv("UP_ELEVATION_FALLBACK_POLICY", raising=False)
        self._disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        with pytest.raises(RuntimeError, match="F2"):
            ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)

    def test_nodata_road_reports_violations_in_lenient(self, monkeypatch):
        monkeypatch.setenv("UP_ELEVATION_FALLBACK_POLICY", "lenient")
        self._disable_thesis_strict(monkeypatch)
        root = _xodr_with_roads(1)
        qc = ElevationImporter.apply_dem(root, _never_valid_sampler, collect_qc=True)
        assert qc["f2_fallback_gate_passed"] is False
        assert qc["f2_fallback_violation_count"] >= 1
        assert "0" in qc["f2_fallback_violations"]["all_forbidden"]
