# ultimate_pipeline/tests/unit/test_connectivity_gap.py
"""
Unit tests for ConnectivityGap.

Each test builds a minimal XODR string in-memory so there are no
external file dependencies.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.domain_gap.connectivity_gap import (
    ConnectivityGap,
    _road_link_metrics,
    _lane_count_per_road,
    _junction_lane_link_completeness,
    _road_lane_link_validity,
)
from ultimate_pipeline.run_full_domain_gap import _finalize_results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_xodr(roads: list[dict], junctions: list[dict] | None = None) -> ET.Element:
    """
    Build a minimal <OpenDRIVE> element from road/junction specs.

    road spec keys:
      id, junction (default "-1"), predecessor_id, successor_id,
      lane_counts (list of per-section non-center lane counts, default [2]),
      link_valid (bool, whether pred/succ ids actually exist in the map)

    junction spec keys:
      id, connections (list of {incoming, connecting, lane_links: [{from, to}]})
    """
    root = ET.Element("OpenDRIVE")
    for r in roads:
        road = ET.SubElement(root, "road", {
            "id": str(r["id"]),
            "junction": str(r.get("junction", "-1")),
            "length": "100.0",
            "name": "",
        })
        # planView (required for a valid XODR, minimal)
        pv = ET.SubElement(road, "planView")
        ET.SubElement(pv, "geometry", {"s": "0", "x": "0", "y": str(r["id"]),
                                        "hdg": "0", "length": "100"})
        ET.SubElement(pv, "geometry").append(ET.Element("line"))

        # link
        link = ET.SubElement(road, "link")
        if "predecessor_id" in r:
            ET.SubElement(link, "predecessor", {
                "elementType": "road",
                "elementId": str(r["predecessor_id"]),
                "contactPoint": "end",
            })
        if "successor_id" in r:
            ET.SubElement(link, "successor", {
                "elementType": "road",
                "elementId": str(r["successor_id"]),
                "contactPoint": "start",
            })

        # lanes
        lanes = ET.SubElement(road, "lanes")
        for sec_lane_count in r.get("lane_counts", [2]):
            sec = ET.SubElement(lanes, "laneSection", {"s": "0"})
            left = ET.SubElement(sec, "left")
            center = ET.SubElement(sec, "center")
            ET.SubElement(center, "lane", {"id": "0", "type": "none"})
            right = ET.SubElement(sec, "right")
            for i in range(1, sec_lane_count + 1):
                ET.SubElement(left, "lane", {"id": str(i), "type": "driving"})
                ET.SubElement(right, "lane", {"id": str(-i), "type": "driving"})

    for j in (junctions or []):
        junc = ET.SubElement(root, "junction", {"id": str(j["id"]), "name": ""})
        for c in j.get("connections", []):
            conn = ET.SubElement(junc, "connection", {
                "id": "0",
                "incomingRoad": str(c["incoming"]),
                "connectingRoad": str(c["connecting"]),
                "contactPoint": "start",
            })
            for ll in c.get("lane_links", []):
                ET.SubElement(conn, "laneLink", {
                    "from": str(ll.get("from", "")),
                    "to": str(ll.get("to", "")),
                })
    return root


def _write_xodr(path: Path, root: ET.Element) -> str:
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return str(path)


# ---------------------------------------------------------------------------
# road_link_metrics
# ---------------------------------------------------------------------------

class TestRoadLinkMetrics:
    def test_all_valid(self):
        # Roads 0→1→2 chain; all pred/succ resolve to existing roads
        root = _build_xodr([
            {"id": 0, "successor_id": 1},
            {"id": 1, "predecessor_id": 0, "successor_id": 2},
            {"id": 2, "predecessor_id": 1},
        ])
        m = _road_link_metrics(root)
        assert m["total_roads"] == 3
        assert m["predecessor_valid_rate"] == 1.0
        assert m["successor_valid_rate"] == 1.0

    def test_dangling_link_reduces_valid_rate(self):
        # Road 0 declares predecessor=999 which does not exist
        root = _build_xodr([
            {"id": 0, "predecessor_id": 999},
            {"id": 1},
        ])
        m = _road_link_metrics(root)
        assert m["predecessor_valid_rate"] == 0.0

    def test_no_links_gives_zero_rates(self):
        root = _build_xodr([{"id": 0}, {"id": 1}])
        m = _road_link_metrics(root)
        assert m["predecessor_declared_rate"] == 0.0
        assert m["roads_with_valid_pred_pct"] == 0.0

    def test_junction_target_counts_as_valid(self):
        # Road 0 links to junction 10
        root = _build_xodr(
            [{"id": 0, "successor_id": 10}],
            junctions=[{"id": 10, "connections": []}],
        )
        m = _road_link_metrics(root)
        assert m["successor_valid_rate"] == 1.0


# ---------------------------------------------------------------------------
# lane_count_per_road
# ---------------------------------------------------------------------------

class TestLaneCountPerRoad:
    def test_two_lane_road(self):
        root = _build_xodr([{"id": 0, "lane_counts": [2]}])
        counts = _lane_count_per_road(root)
        # 2 left + 2 right non-center lanes
        assert counts == [4]

    def test_multi_section_sums(self):
        root = _build_xodr([{"id": 0, "lane_counts": [1, 2]}])
        counts = _lane_count_per_road(root)
        # Section 0: 1+1=2, Section 1: 2+2=4 → total=6
        assert counts == [6]

    def test_zero_lane_road(self):
        root = _build_xodr([{"id": 0, "lane_counts": [0]}])
        counts = _lane_count_per_road(root)
        assert counts == [0]


# ---------------------------------------------------------------------------
# junction_lane_link_completeness
# ---------------------------------------------------------------------------

class TestJunctionLaneLinkCompleteness:
    def test_complete(self):
        root = _build_xodr(
            [{"id": 0}, {"id": 1}],
            junctions=[{"id": 10, "connections": [
                {"incoming": 0, "connecting": 1, "lane_links": [{"from": "-1", "to": "-1"}]},
            ]}],
        )
        rate = _junction_lane_link_completeness(root)
        assert rate == 1.0

    def test_missing_to_attribute(self):
        root = _build_xodr(
            [{"id": 0}, {"id": 1}],
            junctions=[{"id": 10, "connections": [
                {"incoming": 0, "connecting": 1, "lane_links": [{"from": "-1", "to": ""}]},
            ]}],
        )
        rate = _junction_lane_link_completeness(root)
        assert rate == 0.0

    def test_no_lane_links(self):
        root = _build_xodr(
            [{"id": 0}],
            junctions=[{"id": 10, "connections": [
                {"incoming": 0, "connecting": 0, "lane_links": []},
            ]}],
        )
        rate = _junction_lane_link_completeness(root)
        # No laneLink elements → denominator 0 → returns 0.0
        assert rate == 0.0


# ---------------------------------------------------------------------------
# road_lane_link_validity
# ---------------------------------------------------------------------------

class TestRoadLaneLinkValidity:
    def _build_road_with_lane_links(self, valid: bool) -> ET.Element:
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", {"id": "0", "junction": "-1", "length": "200"})
        lanes = ET.SubElement(road, "lanes")

        # Section 0
        sec0 = ET.SubElement(lanes, "laneSection", {"s": "0"})
        right0 = ET.SubElement(sec0, "right")
        lane0 = ET.SubElement(right0, "lane", {"id": "-1", "type": "driving"})
        link0 = ET.SubElement(lane0, "link")
        # Successor in section 1: valid → id="-1" exists; invalid → id="-99" does not
        ET.SubElement(link0, "successor", {"id": "-1" if valid else "-99"})

        # Section 1
        sec1 = ET.SubElement(lanes, "laneSection", {"s": "100"})
        right1 = ET.SubElement(sec1, "right")
        ET.SubElement(right1, "lane", {"id": "-1", "type": "driving"})

        return root

    def test_valid_intra_road_link(self):
        root = self._build_road_with_lane_links(valid=True)
        rate = _road_lane_link_validity(root)
        assert rate == 1.0

    def test_invalid_intra_road_link(self):
        root = self._build_road_with_lane_links(valid=False)
        rate = _road_lane_link_validity(root)
        assert rate == 0.0


# ---------------------------------------------------------------------------
# ConnectivityGap.compute (integration)
# ---------------------------------------------------------------------------

class TestConnectivityGapCompute:
    def test_identical_maps_produce_zero_gap(self, tmp_path: Path):
        roads = [
            {"id": 0, "successor_id": 1, "lane_counts": [2]},
            {"id": 1, "predecessor_id": 0, "lane_counts": [2]},
        ]
        p1 = _write_xodr(tmp_path / "a.xodr", _build_xodr(roads))
        p2 = _write_xodr(tmp_path / "b.xodr", _build_xodr(roads))

        result = ConnectivityGap.compute(p1, p2)

        assert result["disabled"] is False
        gap = result["gap"]
        assert gap["road_link"]["predecessor_valid_rate"] == pytest.approx(0.0)
        assert gap["road_link"]["successor_valid_rate"] == pytest.approx(0.0)
        assert gap["lane_count"]["l1_gap"] == pytest.approx(0.0)
        assert gap["lane_count"]["mean_delta"] == pytest.approx(0.0)

    def test_lane_count_gap_detected(self, tmp_path: Path):
        manual_roads = [{"id": 0, "lane_counts": [1]}, {"id": 1, "lane_counts": [1]}]
        auto_roads   = [{"id": 0, "lane_counts": [3]}, {"id": 1, "lane_counts": [3]}]
        p_m = _write_xodr(tmp_path / "manual.xodr", _build_xodr(manual_roads))
        p_a = _write_xodr(tmp_path / "auto.xodr",   _build_xodr(auto_roads))

        result = ConnectivityGap.compute(p_m, p_a)

        assert result["disabled"] is False
        # Auto has more lanes → mean_delta > 0
        assert result["gap"]["lane_count"]["mean_delta"] > 0

    def test_dangling_links_show_as_gap(self, tmp_path: Path):
        manual_roads = [
            {"id": 0, "successor_id": 1},
            {"id": 1, "predecessor_id": 0},
        ]
        auto_roads = [
            {"id": 0, "successor_id": 999},   # 999 does not exist
            {"id": 1, "predecessor_id": 998},  # 998 does not exist
        ]
        p_m = _write_xodr(tmp_path / "manual.xodr", _build_xodr(manual_roads))
        p_a = _write_xodr(tmp_path / "auto.xodr",   _build_xodr(auto_roads))

        result = ConnectivityGap.compute(p_m, p_a)

        # Manual validity = 1.0, auto validity = 0.0 → delta = -1.0
        assert result["gap"]["road_link"]["successor_valid_rate"] == pytest.approx(-1.0)

    def test_output_has_expected_structure(self, tmp_path: Path):
        roads = [{"id": 0}]
        p = _write_xodr(tmp_path / "x.xodr", _build_xodr(roads))
        result = ConnectivityGap.compute(p, p)

        assert "manual" in result
        assert "auto" in result
        assert "gap" in result
        for section in ("road_link", "lane_count", "junction_degree", "lane_link"):
            assert section in result["manual"]
            assert section in result["gap"]


class TestFullReportConnectivityWiring:
    def test_finalize_results_writes_connectivity_gap(self, tmp_path: Path):
        manual = _write_xodr(
            tmp_path / "manual.xodr",
            _build_xodr(
                [{"id": 0}, {"id": 1}],
                junctions=[
                    {
                        "id": 10,
                        "connections": [
                            {"incoming": 0, "connecting": 1, "lane_links": [{"from": "-1", "to": "-1"}]}
                        ],
                    }
                ],
            ),
        )
        auto = _write_xodr(
            tmp_path / "auto.xodr",
            _build_xodr(
                [
                    {"id": 0, "successor_id": 1},
                    {"id": 1, "predecessor_id": 0},
                ]
            ),
        )
        whole_conn_gap = ConnectivityGap.compute(manual, auto)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        result = _finalize_results(
            output_dir=str(out_dir),
            reference_xodr=manual,
            aligned_auto=auto,
            generated_xodr=auto,
            transform={},
            whole_geom_gap={"disabled": True, "reason": "test"},
            whole_curv_gap={"disabled": True, "reason": "test"},
            whole_elev_gap={"disabled": True, "reason": "dem_qc_failed"},
            whole_inter_gap={"disabled": True, "reason": "test"},
            whole_sem_gap={"disabled": True, "reason": "test"},
            whole_class_gap={"disabled": True, "reason": "test"},
            whole_conn_gap=whole_conn_gap,
            tile_geom_gaps={},
            tile_curv_gaps={},
            tile_gap_vector={},
            tile_map={},
            perception_gap=None,
            latent_whole=None,
            latent_per_tile=None,
            aggregated=None,
            run_meta={
                "manual_map_choice": None,
                "manual_xodr_resolved": manual,
                "manual_xodr_source": "test_fixture",
            },
            combined_repro_hash="test-hash",
            tile_pairing_provenance={},
        )

        full_report = json.loads((out_dir / "full_report.json").read_text(encoding="utf-8"))

        assert "connectivity_gap" in result
        assert "connectivity_gap" in full_report
        assert full_report["structural_domain_gap"]["connectivity"] == full_report["connectivity_gap"]
        assert "predecessor_declared_rate" in full_report["connectivity_gap"]["auto"]["road_link"]
        assert (
            "junction_lane_link_completeness_rate"
            in full_report["connectivity_gap"]["manual"]["lane_link"]
        )
