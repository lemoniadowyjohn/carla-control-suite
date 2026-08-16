# tests/unit/test_c9_tail_gate_controls.py
# -*- coding: utf-8 -*-

"""
C9 tail-gate positive/negative controls.

Per the C9 audit (reports/post_audit_hardening/C9_GATE_CORRECTNESS.md), 13
quality/acceptance checkers had NO dedicated unit tests -- a checker that
silently passes everything would look identical to a healthy map. This file
adds one positive control (clean fixture -> no issue) and one negative
control (same fixture + ONE deliberate defect -> issue flagged) per checker,
grouped by checker.

This file is TEST-ONLY: it does not modify any checker implementation. Where
a checker could not be cleanly driven to a pass/fail pair offline, that is
documented inline and in reports/post_audit_hardening/C9_TAIL_GATE_CONTROLS.md
rather than silently skipped or faked.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import pytest


def _write(tmp_path: Path, name: str, xml_text: str) -> str:
    path = tmp_path / name
    path.write_text(xml_text, encoding="utf-8")
    return str(path)


# ===========================================================================
# 1. check_dem_coverage.check_dem_coverage_with_sampler
#    (sampler-injected variant avoids needing a real georeferenced DEM/CRS
#    stack; check_dem_coverage() itself is a thin CRS+rasterio wrapper around
#    the same _get_road_sample_points()/threshold logic exercised here.)
# ===========================================================================

from ultimate_pipeline.quality.check_dem_coverage import (
    check_dem_coverage_with_sampler,
    check_dem_coverage,
)


def _two_road_xodr(tmp_path: Path, name: str) -> str:
    return _write(
        tmp_path,
        name,
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
    )


def test_check_dem_coverage_with_sampler_positive_control(tmp_path: Path) -> None:
    """All sample points report valid DEM coverage -> ok, ratio == 1.0."""
    xodr = _two_road_xodr(tmp_path, "dem_ok.xodr")

    def all_valid_sampler(x: float, y: float):
        return (100.0, True)

    report = check_dem_coverage_with_sampler(xodr, all_valid_sampler, threshold=0.6)

    assert report["ok"] is True
    assert report["valid_ratio"] == pytest.approx(1.0)
    assert report["total_samples"] > 0
    assert report["invalid_samples"] == 0


def test_check_dem_coverage_with_sampler_negative_control(tmp_path: Path) -> None:
    """All sample points report nodata/out-of-bounds -> ok is False, ratio 0."""
    xodr = _two_road_xodr(tmp_path, "dem_bad.xodr")

    def all_invalid_sampler(x: float, y: float):
        return (None, False)

    report = check_dem_coverage_with_sampler(xodr, all_invalid_sampler, threshold=0.6)

    assert report["ok"] is False
    assert report["valid_ratio"] == pytest.approx(0.0)
    assert report["invalid_samples"] == report["total_samples"]


def test_check_dem_coverage_missing_georeference_fails_closed(tmp_path: Path) -> None:
    """check_dem_coverage() (the CRS-aware entry point) must fail closed with
    reason 'no_georeference' when the XODR header has no <geoReference>, even
    though rasterio/pyproj ARE installed in this environment -- this is the
    behavior actually gating real pipeline runs, so it is covered directly
    rather than only through the sampler-injected variant."""
    xodr = _two_road_xodr(tmp_path, "dem_no_georef.xodr")

    import rasterio
    from rasterio.transform import from_origin
    import numpy as np

    dem_path = tmp_path / "flat.tif"
    data = np.full((10, 10), 100.0, dtype="float32")
    transform = from_origin(0, 10, 1, 1)
    with rasterio.open(
        str(dem_path), "w", driver="GTiff", height=10, width=10, count=1,
        dtype="float32", transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)

    report = check_dem_coverage(xodr, str(dem_path), threshold=0.6)

    assert report["ok"] is False
    assert report["reason"] == "no_georeference"


# ===========================================================================
# 2. check_dem_full_coverage.check_dem_full_coverage
#    (sampler-injected variant; the DEM file must still exist/open because
#    the function unconditionally calls rasterio.open(dem_tif_path), but with
#    a sampler supplied the CRS transform path is bypassed entirely.)
# ===========================================================================

from ultimate_pipeline.quality.check_dem_full_coverage import check_dem_full_coverage


def _flat_dem_tif(tmp_path: Path, name: str = "dem.tif") -> str:
    import rasterio
    from rasterio.transform import from_origin
    import numpy as np

    path = tmp_path / name
    data = np.full((10, 10), 100.0, dtype="float32")
    transform = from_origin(0, 10, 1, 1)
    with rasterio.open(
        str(path), "w", driver="GTiff", height=10, width=10, count=1,
        dtype="float32", transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)
    return str(path)


def test_check_dem_full_coverage_positive_control(tmp_path: Path) -> None:
    """Sampler reports every sampled point as covered -> ok True, ratio 1.0."""
    xodr = _two_road_xodr(tmp_path, "dfc_ok.xodr")
    dem = _flat_dem_tif(tmp_path)
    out_json = tmp_path / "dfc_ok_report.json"

    def all_covered(x: float, y: float):
        return (100.0, True)

    report = check_dem_full_coverage(
        xodr_path=xodr, dem_tif_path=dem, out_json=str(out_json),
        step_m=2.0, threshold=0.6, sampler=all_covered,
    )

    assert report["ok"] is True
    assert report["coverage_ratio"] == pytest.approx(1.0)
    assert report["total_samples"] > 0
    assert out_json.exists()


def test_check_dem_full_coverage_negative_control(tmp_path: Path) -> None:
    """Sampler reports every sampled point as uncovered -> ok is False."""
    xodr = _two_road_xodr(tmp_path, "dfc_bad.xodr")
    dem = _flat_dem_tif(tmp_path)
    out_json = tmp_path / "dfc_bad_report.json"

    def none_covered(x: float, y: float):
        return (None, False)

    report = check_dem_full_coverage(
        xodr_path=xodr, dem_tif_path=dem, out_json=str(out_json),
        step_m=2.0, threshold=0.6, sampler=none_covered,
    )

    assert report["ok"] is False
    assert report["coverage_ratio"] == pytest.approx(0.0)
    assert len(report["uncovered_examples"]) > 0


# ===========================================================================
# 3. check_determinism.check_determinism
# ===========================================================================

from ultimate_pipeline.quality.check_determinism import check_determinism


def _structural_xodr(tmp_path: Path, name: str, *, road2_length: float = 10.0) -> str:
    return _write(
        tmp_path,
        name,
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        f'<road id="2" length="{road2_length}" junction="-1">'
        f'<planView><geometry s="0" x="10" y="0" hdg="0" length="{road2_length}"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
    )


def test_check_determinism_positive_control_identical_structure(tmp_path: Path) -> None:
    """Two structurally identical XODR files -> deterministic=True, hashes equal."""
    a = _structural_xodr(tmp_path, "det_a.xodr")
    b = _structural_xodr(tmp_path, "det_b.xodr")

    report = check_determinism(a, b)

    assert report["deterministic"] is True
    assert report["hash_a"] == report["hash_b"]
    assert report["differences"] == {}


def test_check_determinism_negative_control_structural_drift_detected(tmp_path: Path) -> None:
    """Injected defect: road 2's length differs by > 0.1m between 'runs' ->
    deterministic=False and the mismatch is surfaced in differences."""
    a = _structural_xodr(tmp_path, "det_drift_a.xodr", road2_length=10.0)
    b = _structural_xodr(tmp_path, "det_drift_b.xodr", road2_length=12.5)

    report = check_determinism(a, b)

    assert report["deterministic"] is False
    assert report["hash_a"] != report["hash_b"]
    assert "total_road_length" in report["differences"]


# ===========================================================================
# 4. check_drivability_smoke.check_drivability_smoke
#
#    NOTE: real `carla` Python bindings ARE importable in this environment
#    (CARLA_AVAILABLE resolves True), but no CARLA server is running/allowed
#    offline (UP_DISABLE_CARLA=1). A true "spawn succeeds and ticks" positive
#    control requires a live server and is out of scope here. The two control
#    cases below instead cover the two deterministic, offline-reachable
#    branches: (a) CARLA python API absent -> non-blocking pass, and
#    (b) missing XODR file -> hard failure, BOTH evaluated before any network
#    call is attempted (verified: os.path.exists check precedes
#    carla.Client(...) in the source).
# ===========================================================================

from ultimate_pipeline.quality import check_drivability_smoke as _drivability_mod


def test_check_drivability_smoke_positive_control_carla_absent_is_nonblocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the CARLA python API is unavailable, the gate must be a
    non-blocking pass (ok=True) rather than failing closed."""
    monkeypatch.setattr(_drivability_mod, "CARLA_AVAILABLE", False)

    report = _drivability_mod.check_drivability_smoke(str(tmp_path / "whatever.xodr"))

    assert report["ok"] is True
    assert report["carla_available"] is False
    assert any("skipped" in w for w in report["warnings"])


def test_check_drivability_smoke_negative_control_missing_xodr_fails(
    tmp_path: Path,
) -> None:
    """A nonexistent XODR path must fail closed (ok=False) with an explicit
    error, reached deterministically offline before any CARLA connection is
    attempted."""
    missing = tmp_path / "does_not_exist.xodr"

    report = _drivability_mod.check_drivability_smoke(str(missing))

    assert report["ok"] is False
    assert report["error"] is not None
    assert "not found" in report["error"]


# ===========================================================================
# 5. check_elevation_missing_and_cliffs.check_elevation_missing_and_cliffs
# ===========================================================================

from ultimate_pipeline.quality.check_elevation_missing_and_cliffs import (
    check_elevation_missing_and_cliffs,
)


def test_check_elevation_missing_and_cliffs_positive_control(tmp_path: Path) -> None:
    """Every road has nonzero elevation and links agree at the seam ->
    zero_ratio 0, no cliff, ok True."""
    xodr = _write(
        tmp_path,
        "cliffs_ok.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="2"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="100.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="100.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        "</OpenDRIVE>",
    )

    report = check_elevation_missing_and_cliffs(xodr, max_zero_ratio=0.01, max_link_dz_m=50.0)

    assert report["ok"] is True
    assert report["zero_ratio"] == pytest.approx(0.0)
    assert report["max_link_dz"] == pytest.approx(0.0)


def test_check_elevation_missing_and_cliffs_negative_control_cliff(tmp_path: Path) -> None:
    """Injected defect: road 1 ends at z=100 but its successor (road 2)
    starts at z=500 -- a 400m cliff far beyond max_link_dz_m -- must be
    flagged."""
    xodr = _write(
        tmp_path,
        "cliffs_bad.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="2"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="100.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="500.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road>"
        "</OpenDRIVE>",
    )

    report = check_elevation_missing_and_cliffs(xodr, max_zero_ratio=0.01, max_link_dz_m=50.0)

    assert report["ok"] is False
    assert report["max_link_dz"] == pytest.approx(400.0, abs=1e-6)
    assert len(report["examples"]) == 1


def test_check_elevation_missing_and_cliffs_negative_control_missing_elevation(
    tmp_path: Path,
) -> None:
    """Injected defect: every road has no elevationProfile at all (both
    endpoints default to 0.0) -> zero_ratio 1.0, exceeding max_zero_ratio."""
    xodr = _write(
        tmp_path,
        "cliffs_missing.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
    )

    report = check_elevation_missing_and_cliffs(xodr, max_zero_ratio=0.01, max_link_dz_m=50.0)

    assert report["ok"] is False
    assert report["zero_ratio"] == pytest.approx(1.0)


# ===========================================================================
# 6. check_elevation_profile.check_elevation_profile
#
#    NOTE: this function returns (report, invalid_found) where invalid_found
#    tracks unparsable/non-finite numeric attributes, NOT grade spikes. Grade
#    spikes are surfaced per-road in report["roads"][i]["spikes"] but do not
#    flip a top-level ok/invalid flag. The positive/negative pair below
#    therefore targets what the function actually returns: spikes list
#    empty vs non-empty for a genuine grade violation, and invalid_found
#    True vs False for a genuinely malformed numeric attribute.
# ===========================================================================

from ultimate_pipeline.quality.check_elevation_profile import check_elevation_profile


def test_check_elevation_profile_positive_control_no_spikes(tmp_path: Path) -> None:
    """A gentle, within-threshold grade must produce zero spikes and
    invalid_found False."""
    xodr = _write(
        tmp_path,
        "profile_ok.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="100.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="100.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="100.0" b="0.05" c="0.0" d="0.0"/></elevationProfile>'
        "</road></OpenDRIVE>",
    )

    report, invalid_found = check_elevation_profile(Path(xodr), max_grade=0.2)

    assert invalid_found is False
    road_entry = report["roads"][0]
    assert road_entry["spikes"] == []


def test_check_elevation_profile_negative_control_grade_spike(tmp_path: Path) -> None:
    """Injected defect: a road climbs at grade 0.9 (b=0.9), far exceeding the
    0.2 threshold -- must be recorded as a spike."""
    xodr = _write(
        tmp_path,
        "profile_spike.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="100.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="100.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="100.0" b="0.9" c="0.0" d="0.0"/></elevationProfile>'
        "</road></OpenDRIVE>",
    )

    report, invalid_found = check_elevation_profile(Path(xodr), max_grade=0.2)

    road_entry = report["roads"][0]
    assert len(road_entry["spikes"]) > 0
    assert road_entry["spikes"][0]["grade"] == pytest.approx(0.9, abs=1e-6)


def test_check_elevation_profile_negative_control_invalid_attribute(tmp_path: Path) -> None:
    """Injected defect: a non-finite ('nan') elevation coefficient must set
    invalid_found True."""
    xodr = _write(
        tmp_path,
        "profile_nan.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="100.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="100.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="nan" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road></OpenDRIVE>",
    )

    report, invalid_found = check_elevation_profile(Path(xodr), max_grade=0.2)

    assert invalid_found is True


# ===========================================================================
# 7. check_elevation_seams.check_elevation_seams
#    (within-road sampling: samples a single road's own elevation polynomial
#    at sample_step_m intervals and flags large jumps between consecutive
#    samples.)
# ===========================================================================

from ultimate_pipeline.quality.check_elevation_seams import check_elevation_seams


def test_check_elevation_seams_positive_control_smooth_road(tmp_path: Path) -> None:
    """A long, flat road sampled every 5m must show no seam jumps."""
    xodr = _write(
        tmp_path,
        "seams_ok.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="50.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="50.0"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="100.0" b="0.0" c="0.0" d="0.0"/></elevationProfile>'
        "</road></OpenDRIVE>",
    )

    report = check_elevation_seams(
        xodr, sample_step_m=5.0, step_threshold_m=1.5, max_jump_m=5.0, p95_threshold_m=1.0
    )

    assert report["ok"] is True
    assert report["seam_stats"]["max_jump"] == pytest.approx(0.0)


def test_check_elevation_seams_negative_control_abrupt_jump(tmp_path: Path) -> None:
    """Injected defect: a second elevation record mid-road introduces an
    abrupt 20m step at s=25, exceeding max_jump_m -- must be flagged."""
    xodr = _write(
        tmp_path,
        "seams_bad.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="50.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="50.0"><line/></geometry></planView>'
        "<elevationProfile>"
        '<elevation s="0" a="100.0" b="0.0" c="0.0" d="0.0"/>'
        '<elevation s="25" a="120.0" b="0.0" c="0.0" d="0.0"/>'
        "</elevationProfile>"
        "</road></OpenDRIVE>",
    )

    report = check_elevation_seams(
        xodr, sample_step_m=5.0, step_threshold_m=1.5, max_jump_m=5.0, p95_threshold_m=1.0
    )

    assert report["ok"] is False
    assert report["seam_stats"]["max_jump"] >= 20.0 - 1e-6


# ===========================================================================
# 8. check_lane_geometry_continuity.check_lane_geometry_continuity
#    (laneSection-boundary laneOffset / lane-width continuity within a road)
# ===========================================================================

from ultimate_pipeline.quality.check_lane_geometry_continuity import (
    check_lane_geometry_continuity,
)


def _two_section_road_xodr(
    tmp_path: Path,
    name: str,
    *,
    width_a: float,
    width_b: float,
) -> str:
    return _write(
        tmp_path,
        name,
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="20.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="20.0"><line/></geometry></planView>'
        "<lanes>"
        '<laneSection s="0.0">'
        "<center><lane id=\"0\" type=\"none\"/></center>"
        "<right>"
        f'<lane id="-1" type="driving"><width sOffset="0.0" a="{width_a}" b="0.0" c="0.0" d="0.0"/></lane>'
        "</right>"
        "</laneSection>"
        '<laneSection s="10.0">'
        "<center><lane id=\"0\" type=\"none\"/></center>"
        "<right>"
        f'<lane id="-1" type="driving"><width sOffset="0.0" a="{width_b}" b="0.0" c="0.0" d="0.0"/></lane>'
        "</right>"
        "</laneSection>"
        "</lanes>"
        "</road></OpenDRIVE>",
    )


def test_check_lane_geometry_continuity_positive_control(tmp_path: Path) -> None:
    """Lane width matches (3.5 -> 3.5) across the laneSection boundary ->
    no issues."""
    xodr = _two_section_road_xodr(tmp_path, "lgc_ok.xodr", width_a=3.5, width_b=3.5)

    report = check_lane_geometry_continuity(xodr, lane_width_eps=0.10)

    assert report["ok"] is True
    assert report["n_issues"] == 0


def test_check_lane_geometry_continuity_negative_control_width_jump(tmp_path: Path) -> None:
    """Injected defect: lane width jumps from 3.5m to 6.0m at the
    laneSection boundary, exceeding lane_width_eps -> flagged."""
    xodr = _two_section_road_xodr(tmp_path, "lgc_bad.xodr", width_a=3.5, width_b=6.0)

    report = check_lane_geometry_continuity(xodr, lane_width_eps=0.10)

    assert report["ok"] is False
    assert report["n_issues"] >= 1
    assert any(issue["type"] == "lane_width" for issue in report["issues"])


# ===========================================================================
# 9. check_lane_link_targets_exist.check_lane_link_targets_exist
# ===========================================================================

from ultimate_pipeline.quality.check_lane_link_targets_exist import (
    check_lane_link_targets_exist,
)


def _linked_lane_sections_xodr(tmp_path: Path, name: str, *, successor_target_id: str) -> str:
    return _write(
        tmp_path,
        name,
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="20.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="20.0"><line/></geometry></planView>'
        "<lanes>"
        '<laneSection s="0.0">'
        "<center><lane id=\"0\" type=\"none\"/></center>"
        "<right>"
        '<lane id="-1" type="driving">'
        f'<link><successor id="{successor_target_id}"/></link>'
        '<width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>'
        "</lane>"
        "</right>"
        "</laneSection>"
        '<laneSection s="10.0">'
        "<center><lane id=\"0\" type=\"none\"/></center>"
        "<right>"
        '<lane id="-1" type="driving"><width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/></lane>'
        "</right>"
        "</laneSection>"
        "</lanes>"
        "</road></OpenDRIVE>",
    )


def test_check_lane_link_targets_exist_positive_control(tmp_path: Path) -> None:
    """Lane -1 in section 0 has a successor link to lane -1, which DOES exist
    in section 1 -> no issues."""
    xodr = _linked_lane_sections_xodr(tmp_path, "llt_ok.xodr", successor_target_id="-1")

    report = check_lane_link_targets_exist(xodr, allow_dead_ends=True)

    assert report["ok"] is True
    assert report["num_issues"] == 0


def test_check_lane_link_targets_exist_negative_control_dangling_target(
    tmp_path: Path,
) -> None:
    """Injected defect: the successor link points at lane id -2, which does
    NOT exist in the next laneSection -> flagged."""
    xodr = _linked_lane_sections_xodr(tmp_path, "llt_bad.xodr", successor_target_id="-2")

    report = check_lane_link_targets_exist(xodr, allow_dead_ends=True)

    assert report["ok"] is False
    assert report["num_issues"] == 1
    assert report["issues"][0]["direction"] == "successor"
    assert report["issues"][0]["target_lane_id"] == -2


# ===========================================================================
# 10. check_lane_width_continuity.check_lane_width_continuity
# ===========================================================================

from ultimate_pipeline.quality.check_lane_width_continuity import (
    check_lane_width_continuity,
)


def test_check_lane_width_continuity_positive_control(tmp_path: Path) -> None:
    """Positive width, matching width at the laneSection boundary -> ok."""
    xodr = _two_section_road_xodr(tmp_path, "lwc_ok.xodr", width_a=3.5, width_b=3.5)

    report = check_lane_width_continuity(xodr, min_width=0.01, max_jump=1.0)

    assert report["ok"] is True
    assert report["num_issues"] == 0


def test_check_lane_width_continuity_negative_control_nonpositive_width(
    tmp_path: Path,
) -> None:
    """Injected defect: lane width is 0.0 (<= min_width) at a laneSection
    start -> flagged as nonpositive_width."""
    xodr = _write(
        tmp_path,
        "lwc_zero.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "<lanes>"
        '<laneSection s="0.0">'
        "<center><lane id=\"0\" type=\"none\"/></center>"
        "<right>"
        '<lane id="-1" type="driving"><width sOffset="0.0" a="0.0" b="0.0" c="0.0" d="0.0"/></lane>'
        "</right>"
        "</laneSection>"
        "</lanes>"
        "</road></OpenDRIVE>",
    )

    report = check_lane_width_continuity(xodr, min_width=0.01, max_jump=1.0)

    assert report["ok"] is False
    assert any(issue["type"] == "nonpositive_width" for issue in report["issues"])


def test_check_lane_width_continuity_negative_control_width_jump(tmp_path: Path) -> None:
    """Injected defect: lane width jumps from 3.5m to 6.0m at the
    laneSection boundary, exceeding max_jump -> flagged as width_jump."""
    xodr = _two_section_road_xodr(tmp_path, "lwc_jump.xodr", width_a=3.5, width_b=6.0)

    report = check_lane_width_continuity(xodr, min_width=0.01, max_jump=1.0)

    assert report["ok"] is False
    assert any(issue["type"] == "width_jump" for issue in report["issues"])


# ===========================================================================
# 11. check_origin_sanity.check_origin_sanity
# ===========================================================================

from ultimate_pipeline.quality.check_origin_sanity import check_origin_sanity


def test_check_origin_sanity_positive_control_near_origin(tmp_path: Path) -> None:
    """Coordinates near (0,0) -> centroid distance well under warn/fail
    thresholds, ok True, no warnings."""
    xodr = _write(
        tmp_path,
        "origin_ok.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="100" y="100" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road></OpenDRIVE>",
    )

    report = check_origin_sanity(xodr, warn_distance_m=50_000.0, fail_distance_m=500_000.0)

    assert report["ok"] is True
    assert report["warnings"] == []
    assert report["centroid_distance_m"] < 50_000.0


def test_check_origin_sanity_negative_control_far_from_origin(tmp_path: Path) -> None:
    """Injected defect: road geometry sits ~1,000,000m from the coordinate
    origin (e.g. raw unsubtracted UTM easting/northing bug) -- exceeds
    fail_distance_m -> ok False."""
    xodr = _write(
        tmp_path,
        "origin_bad.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<OpenDRIVE><road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="1000000.0" y="1000000.0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road></OpenDRIVE>",
    )

    report = check_origin_sanity(xodr, warn_distance_m=50_000.0, fail_distance_m=500_000.0)

    assert report["ok"] is False
    assert report["centroid_distance_m"] > 500_000.0
    assert any("exceeds fail threshold" in w for w in report["warnings"])


# ===========================================================================
# 12. check_post_tiling_integrity.check_post_tiling_integrity
#
#    NOTE: this checker delegates seam-endpoint sanity to C6's
#    check_geometric_continuity (out of scope to modify/depend on its inner
#    behavior). The controls here instead exercise this module's OWN direct
#    logic -- duplicate-ID detection and orphan-link detection -- which is
#    unaffected by C6's implementation and keeps this test decoupled from a
#    sibling agent's concurrent edits to check_geometric_continuity.py.
# ===========================================================================

from ultimate_pipeline.quality.check_post_tiling_integrity import (
    check_post_tiling_integrity,
)


def test_check_post_tiling_integrity_positive_control(tmp_path: Path) -> None:
    """Unique road/junction/signal IDs, no orphan links, geometrically
    continuous seam -> ok True, no issues."""
    xodr = _write(
        tmp_path,
        "pti_ok.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
    )

    report = check_post_tiling_integrity(xodr)

    assert report["ok"] is True
    assert report["issues"] == []


def test_check_post_tiling_integrity_negative_control_duplicate_road_id(
    tmp_path: Path,
) -> None:
    """Injected defect: two <road> elements share id="1" -> flagged as
    duplicate_road_ids."""
    xodr = _write(
        tmp_path,
        "pti_dup.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        '<road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="20" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
    )

    report = check_post_tiling_integrity(xodr)

    assert report["ok"] is False
    dup_issue = next(i for i in report["issues"] if i["type"] == "duplicate_road_ids")
    assert dup_issue["ids"] == ["1"]


def test_check_post_tiling_integrity_negative_control_orphan_link(tmp_path: Path) -> None:
    """Injected defect: road 1's successor points at road id 99, which does
    not exist anywhere in the map -> flagged as orphan_road_link."""
    xodr = _write(
        tmp_path,
        "pti_orphan.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<link><successor elementType="road" elementId="99" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
    )

    report = check_post_tiling_integrity(xodr)

    assert report["ok"] is False
    assert any(i["type"] == "orphan_road_link" for i in report["issues"])


# ===========================================================================
# 13. check_xodr_schema.check_xml_uniqueness / validate_xodr_schema
# ===========================================================================

from ultimate_pipeline.quality.check_xodr_schema import (
    check_xml_uniqueness,
    validate_xodr_schema,
)


def test_check_xml_uniqueness_positive_control() -> None:
    """Unique road ids and unique (road, laneSection, side, laneId) tuples ->
    no issues reported."""
    root = ET.fromstring(
        '<OpenDRIVE>'
        '<road id="1">'
        '<lanes><laneSection s="0.0">'
        '<left><lane id="1"/></left>'
        '<right><lane id="-1"/></right>'
        "</laneSection></lanes>"
        "</road>"
        '<road id="2">'
        '<lanes><laneSection s="0.0">'
        '<right><lane id="-1"/></right>'
        "</laneSection></lanes>"
        "</road>"
        "</OpenDRIVE>"
    )

    issues = check_xml_uniqueness(root)

    assert issues == []


def test_check_xml_uniqueness_negative_control_duplicate_road_id() -> None:
    """Injected defect: two <road> elements share id="1" -> flagged."""
    root = ET.fromstring(
        '<OpenDRIVE>'
        '<road id="1"/>'
        '<road id="1"/>'
        "</OpenDRIVE>"
    )

    issues = check_xml_uniqueness(root)

    assert len(issues) == 1
    assert "Duplicate road id" in issues[0]


def test_check_xml_uniqueness_negative_control_duplicate_lane_id() -> None:
    """Injected defect: the same road/laneSection/side has two <lane
    id="-1"> entries -> flagged as a duplicate lane id."""
    root = ET.fromstring(
        '<OpenDRIVE>'
        '<road id="1">'
        '<lanes><laneSection s="0.0">'
        '<right><lane id="-1"/><lane id="-1"/></right>'
        "</laneSection></lanes>"
        "</road>"
        "</OpenDRIVE>"
    )

    issues = check_xml_uniqueness(root)

    assert len(issues) == 1
    assert "Duplicate lane id" in issues[0]


def test_validate_xodr_schema_positive_control_no_xsd_skips_and_passes(
    tmp_path: Path,
) -> None:
    """With xsd_path=None (the actual call pattern used throughout the
    pipeline -- see stage_08_integrity.py / crash_safe_length_repair.py),
    schema validation is intentionally skipped and must report ok."""
    xodr = _write(
        tmp_path,
        "schema_any.xodr",
        '<?xml version="1.0" encoding="utf-8"?><OpenDRIVE><road id="1"/></OpenDRIVE>',
    )

    ok, err = validate_xodr_schema(xodr, None)

    assert ok is True
    assert err is None


def test_validate_xodr_schema_negative_control_real_xsd_rejects_invalid_xml(
    tmp_path: Path,
) -> None:
    """With a real minimal XSD supplied, an XODR file that violates it (an
    <OpenDRIVE> root containing a disallowed child element) must fail
    validation with a non-None error message. This exercises the actual
    lxml XMLSchema validation path, not just the xsd_path=None skip branch."""
    xsd = _write(
        tmp_path,
        "mini.xsd",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="OpenDRIVE">'
        "<xs:complexType>"
        '<xs:sequence><xs:element name="header" minOccurs="1" maxOccurs="1"/></xs:sequence>'
        "</xs:complexType>"
        "</xs:element>"
        "</xs:schema>",
    )
    # Schema requires a <header> child; this file has none -> must fail.
    xodr = _write(
        tmp_path,
        "schema_invalid.xodr",
        '<?xml version="1.0" encoding="utf-8"?><OpenDRIVE><road id="1"/></OpenDRIVE>',
    )

    ok, err = validate_xodr_schema(xodr, xsd)

    assert ok is False
    assert err is not None


def test_validate_xodr_schema_positive_control_real_xsd_accepts_valid_xml(
    tmp_path: Path,
) -> None:
    """Positive counterpart: a file that DOES satisfy the same minimal XSD
    (has the required <header> child) must pass validation."""
    xsd = _write(
        tmp_path,
        "mini2.xsd",
        '<?xml version="1.0" encoding="utf-8"?>'
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="OpenDRIVE">'
        "<xs:complexType>"
        '<xs:sequence><xs:element name="header" minOccurs="1" maxOccurs="1"/></xs:sequence>'
        "</xs:complexType>"
        "</xs:element>"
        "</xs:schema>",
    )
    xodr = _write(
        tmp_path,
        "schema_valid.xodr",
        '<?xml version="1.0" encoding="utf-8"?><OpenDRIVE><header/></OpenDRIVE>',
    )

    ok, err = validate_xodr_schema(xodr, xsd)

    assert ok is True
    assert err is None
