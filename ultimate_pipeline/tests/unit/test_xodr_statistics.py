# ultimate_pipeline/core/xodr_statistics.py -- structural/geometric/semantic
# stats used for domain-gap evaluation and thesis analysis. Live via
# main_pipeline.py. Zero prior test coverage. No bugs found: unlike the
# earlier lane_overlay.py bug (project_lane_overlay_zero_lanes_fix_20260830),
# _lane_stats here correctly uses ".//lane" (recursive) from laneSection, not
# a direct-child .find() on <left>/<right> -- verified it produces nonzero
# counts on a real 32710-road pinned map.
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.core.xodr_statistics import XODRStatistics


def _write(path, xml: str) -> None:
    path.write_text(f'<?xml version="1.0"?><OpenDRIVE>{xml}</OpenDRIVE>', encoding="utf-8")


# ---------------------------------------------------------------------------
# _road_stats
# ---------------------------------------------------------------------------


def test_road_stats_basic_aggregates(tmp_path):
    p = tmp_path / "m.xodr"
    _write(p, '<road id="1" length="5"/><road id="2" length="15"/>')

    stats = XODRStatistics.compute(str(p))["roads"]

    assert stats["count"] == 2
    assert stats["total_length_m"] == 20.0
    assert stats["avg_length_m"] == 10.0
    assert stats["min_length_m"] == 5.0
    assert stats["max_length_m"] == 15.0


def test_road_stats_no_roads_returns_zeroed_aggregates(tmp_path):
    p = tmp_path / "empty.xodr"
    _write(p, "")

    stats = XODRStatistics.compute(str(p))["roads"]

    assert stats["count"] == 0
    assert stats["total_length_m"] == 0.0
    assert stats["min_length_m"] == 0.0


def test_road_stats_length_histogram_bucketing(tmp_path):
    p = tmp_path / "m.xodr"
    _write(p, '<road id="1" length="5"/><road id="2" length="45"/><road id="3" length="600"/>')

    hist = XODRStatistics.compute(str(p))["roads"]["length_histogram"]

    assert hist["0-10"] == 1
    assert hist["30-60"] == 1
    assert hist[">500"] == 1


def test_road_stats_malformed_length_is_ignored_not_crashing(tmp_path):
    p = tmp_path / "m.xodr"
    _write(p, '<road id="1" length="not_a_number"/><road id="2" length="10"/>')

    stats = XODRStatistics.compute(str(p))["roads"]

    assert stats["count"] == 2  # both roads counted
    assert stats["total_length_m"] == 10.0  # malformed one excluded from length calc


# ---------------------------------------------------------------------------
# _lane_stats
# ---------------------------------------------------------------------------


def test_lane_stats_counts_lanes_nested_under_left_right_center(tmp_path):
    p = tmp_path / "m.xodr"
    _write(
        p,
        """
        <road id="1" length="10">
          <lanes>
            <laneSection s="0">
              <left><lane id="1"><width a="3.5"/></lane></left>
              <center><lane id="0"/></center>
              <right><lane id="-1"><width a="3.0"/></lane></right>
            </laneSection>
          </lanes>
        </road>
        """,
    )

    stats = XODRStatistics.compute(str(p))["lanes"]

    assert stats["total_lanes"] == 2  # center lane 0 excluded
    assert stats["width_min"] == 3.0
    assert stats["width_max"] == 3.5


def test_lane_stats_no_lanes_returns_zeroed_aggregates(tmp_path):
    p = tmp_path / "m.xodr"
    _write(p, '<road id="1" length="10"><lanes/></road>')

    stats = XODRStatistics.compute(str(p))["lanes"]

    assert stats["total_lanes"] == 0
    assert stats["width_min"] == 0.0


def test_lane_stats_real_pinned_map_produces_nonzero_counts():
    """Regression guard against the exact XPath-depth bug class already
    found and fixed in lane_overlay.py's _count_driving_lanes -- confirms
    this sibling implementation does NOT have the same defect."""
    import glob

    candidates = glob.glob(
        "reports/ingolstadt_map_quality_v2/work_package_02_connectivity/*.xodr"
    )
    if not candidates:
        pytest.skip("no real pinned map fixture available in this checkout")

    stats = XODRStatistics.compute(candidates[0])["lanes"]
    assert stats["total_lanes"] > 0


# ---------------------------------------------------------------------------
# _geometry_stats
# ---------------------------------------------------------------------------


def test_geometry_stats_counts_by_type_and_arc_curvature(tmp_path):
    p = tmp_path / "m.xodr"
    _write(
        p,
        """
        <road id="1" length="10">
          <planView>
            <geometry s="0" x="0" y="0" hdg="0" length="5"><line/></geometry>
            <geometry s="5" x="5" y="0" hdg="0" length="5"><arc curvature="0.2"/></geometry>
          </planView>
        </road>
        """,
    )

    stats = XODRStatistics.compute(str(p))["geometry"]

    assert stats["geometry_counts"]["line"] == 1
    assert stats["geometry_counts"]["arc"] == 1
    assert stats["curvature_max"] == pytest.approx(0.2)


def test_geometry_stats_no_planview_skips_road(tmp_path):
    p = tmp_path / "m.xodr"
    _write(p, '<road id="1" length="10"/>')

    stats = XODRStatistics.compute(str(p))["geometry"]

    assert stats["geometry_counts"] == {
        "line": 0, "spiral": 0, "arc": 0, "poly3": 0, "paramPoly3": 0
    }


# ---------------------------------------------------------------------------
# _junction_stats
# ---------------------------------------------------------------------------


def test_junction_stats_counts_junctions(tmp_path):
    p = tmp_path / "m.xodr"
    _write(p, '<junction id="1"/><junction id="2"/>')

    assert XODRStatistics.compute(str(p))["junctions"]["count"] == 2


# ---------------------------------------------------------------------------
# _traffic_stats
# ---------------------------------------------------------------------------


def test_traffic_stats_counts_object_and_signal_traffic_lights(tmp_path):
    p = tmp_path / "m.xodr"
    _write(
        p,
        """
        <road id="1" length="10">
          <objects><object id="1" type="trafficLight"/></objects>
          <signals>
            <signal id="2" type="trafficLight"/>
            <signal id="3" type="speed"/>
          </signals>
        </road>
        """,
    )

    stats = XODRStatistics.compute(str(p))["traffic"]

    assert stats["traffic_lights_objects"] == 1
    assert stats["traffic_lights_signals"] == 1
    assert stats["traffic_lights"] == 2
    assert stats["signals_total"] == 2


def test_traffic_stats_speed_limit_distribution(tmp_path):
    p = tmp_path / "m.xodr"
    _write(
        p,
        """
        <road id="1" length="10">
          <lanes><laneSection><center><lane id="0">
            <speed max="13.9"/>
          </lane></center></laneSection></lanes>
        </road>
        """,
    )

    stats = XODRStatistics.compute(str(p))["traffic"]

    assert stats["speed_limit_distribution"] == {13: 1}


# ---------------------------------------------------------------------------
# _elevation_stats
# ---------------------------------------------------------------------------


def test_elevation_stats_flat_profile_zero_range(tmp_path):
    p = tmp_path / "m.xodr"
    _write(
        p,
        """
        <road id="1" length="10">
          <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
        </road>
        """,
    )

    stats = XODRStatistics.compute(str(p))["elevation"]

    assert stats["min_z"] == 0.0
    assert stats["max_z"] == 0.0
    assert stats["z_range"] == 0.0


def test_elevation_stats_computes_range_across_segments(tmp_path):
    p = tmp_path / "m.xodr"
    _write(
        p,
        """
        <road id="1" length="20">
          <elevationProfile>
            <elevation s="0" a="0" b="1" c="0" d="0"/>
            <elevation s="10" a="10" b="-1" c="0" d="0"/>
          </elevationProfile>
        </road>
        """,
    )

    stats = XODRStatistics.compute(str(p))["elevation"]

    # segment 1: s=0..10, a=0,b=1 -> z(0)=0, z(10)=10
    # segment 2: s=10..20 (road end), a=10,b=-1 -> z(10)=10, z(20)=0
    assert stats["min_z"] == 0.0
    assert stats["max_z"] == 10.0
    assert stats["z_range"] == 10.0


def test_elevation_stats_no_elevation_profile_returns_zeroed(tmp_path):
    p = tmp_path / "m.xodr"
    _write(p, '<road id="1" length="10"/>')

    stats = XODRStatistics.compute(str(p))["elevation"]

    assert stats == {"min_z": 0.0, "max_z": 0.0, "z_range": 0.0}


# ---------------------------------------------------------------------------
# compute() / save_json()
# ---------------------------------------------------------------------------


def test_compute_sets_success_true(tmp_path):
    p = tmp_path / "m.xodr"
    _write(p, "")

    assert XODRStatistics.compute(str(p))["success"] is True


def test_save_json_writes_valid_json(tmp_path):
    import json

    stats = {"roads": {"count": 1}, "success": True}
    out = tmp_path / "stats.json"

    XODRStatistics.save_json(stats, str(out))

    assert json.loads(out.read_text(encoding="utf-8")) == stats
