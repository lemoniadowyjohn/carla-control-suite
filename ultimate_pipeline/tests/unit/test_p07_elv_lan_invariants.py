# -*- coding: utf-8 -*-
"""P07 ELV-LAN-001 tests: seam fixer, DEM provenance, elevation/lane invariants."""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.dem.dem_provenance import (
    DEMProvenance,
    load_dem_provenance,
    record_dem_provenance,
    save_dem_provenance,
    verify_dem_provenance,
)
from ultimate_pipeline.elevation.elevation_seam_fixer import fix_elevation_seams
from ultimate_pipeline.quality.elevation_structure_invariants import (
    validate_elevation_profile_structure,
)
from ultimate_pipeline.quality.lane_structure_invariants import (
    validate_lane_structure,
)


def _road(rid: str, length: float, link_attrib=None, link_elem="predecessor"):
    road = ET.Element("road", id=str(rid), length=f"{length:.3f}")
    if link_attrib is not None:
        link = ET.SubElement(road, "link")
        ET.SubElement(link, link_elem, attrib=link_attrib)
    return road


def _elevation_profile(road, segments):
    profile = ET.SubElement(road, "elevationProfile")
    for s, a, b, c, d in segments:
        ET.SubElement(profile, "elevation", s=f"{s:.4f}", a=f"{a:.4f}",
                      b=f"{b:.4f}", c=f"{c:.4f}", d=f"{d:.4f}")
    return road


def _lanes(road, sections):
    lanes = ET.SubElement(road, "lanes")
    for s, left_ids in sections:
        section = ET.SubElement(lanes, "laneSection", s=f"{s:.4f}")
        center = ET.SubElement(section, "center")
        ET.SubElement(center, "lane", id="0")
        left = ET.SubElement(section, "left")
        for lid in left_ids:
            lane = ET.SubElement(left, "lane", id=str(lid))
            ET.SubElement(lane, "width", sOffset="0", a="3.5", b="0", c="0", d="0")
    return road


def _write_xodr(path, roads):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    tree = ET.ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _z_at(road, s):
    for seg in road.findall("./elevationProfile/elevation"):
        pass
    segs = []
    for el in road.findall("./elevationProfile/elevation"):
        segs.append(tuple(float(el.get(k)) for k in ("s", "a", "b", "c", "d")))
    segs.sort(key=lambda v: v[0])
    seg = segs[0]
    for cand in segs:
        if s >= cand[0]:
            seg = cand
        else:
            break
    s0, a, b, c, d = seg
    ds = max(0.0, s - s0)
    return a + b * ds + c * ds * ds + d * ds * ds * ds


# ---------------------------------------------------------------- seam fixer
class TestSeamFixer:
    def test_fixes_flat_boundary_gap(self, tmp_path):
        a = _elevation_profile(_road("1", 100.0), [(0.0, 0.0, 0.0, 0.0, 0.0)])
        b = _elevation_profile(_road("2", 100.0, {"elementType": "road", "elementId": "1", "contactPoint": "end"}, "predecessor"),
                               [(0.0, 0.2, 0.0, 0.0, 0.0)])
        src = tmp_path / "in.xodr"
        out = tmp_path / "out.xodr"
        _write_xodr(str(src), [a, b])

        stats = fix_elevation_seams(str(src), str(out))

        assert stats["seams_checked"] == 1
        assert stats["seams_fixed"] == 1
        assert out.exists()
        tree = ET.parse(str(out))
        fixed = {r.get("id"): r for r in tree.getroot().findall("road")}
        assert _z_at(fixed["2"], 0.0) == pytest.approx(_z_at(fixed["1"], 100.0))
        # blend decays: far from boundary the original profile is restored
        assert 0.15 < _z_at(fixed["2"], 24.0) < 0.2
        assert _z_at(fixed["2"], 100.0) == pytest.approx(0.2)

    def test_over_threshold_not_forced(self, tmp_path):
        a = _elevation_profile(_road("1", 100.0), [(0.0, 0.0, 0.0, 0.0, 0.0)])
        b = _elevation_profile(_road("2", 100.0, {"elementType": "road", "elementId": "1", "contactPoint": "end"}, "predecessor"),
                               [(0.0, 50.0, 0.0, 0.0, 0.0)])
        src = tmp_path / "in.xodr"
        out = tmp_path / "out.xodr"
        _write_xodr(str(src), [a, b])

        stats = fix_elevation_seams(str(src), str(out), max_snap_m=0.25)

        assert stats["seams_fixed"] == 0
        assert stats["seams_over_threshold"] == 1
        assert not out.exists()
        assert any("exceeds max_snap_m" in w for w in stats["warnings"])

    def test_no_geometry_no_output(self, tmp_path):
        a = _elevation_profile(_road("1", 100.0), [(0.0, 0.0, 0.0, 0.0, 0.0)])
        src = tmp_path / "in.xodr"
        out = tmp_path / "out.xodr"
        _write_xodr(str(src), [a])
        stats = fix_elevation_seams(str(src), str(out))
        assert stats["seams_checked"] == 0
        assert stats["seams_fixed"] == 0
        assert not out.exists()

    def test_parse_failure_returns_stats(self, tmp_path):
        bad = tmp_path / "bad.xodr"
        bad.write_text("<OpenDRIVE", encoding="utf-8")
        stats = fix_elevation_seams(str(bad), str(tmp_path / "out.xodr"))
        assert stats["seams_fixed"] == 0
        assert any("failed to parse" in w for w in stats["warnings"])


# -------------------------------------------------------------- provenance
class TestDemProvenance:
    def test_record_and_verify_match(self, tmp_path):
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"DEMDATA" * 64)
        rec = record_dem_provenance(str(dem), crs="EPSG:32632",
                                    provider="copernicus", licence="CC-BY-4.0")
        assert rec.sha256 and len(rec.sha256) == 64
        res = verify_dem_provenance(rec)
        assert res["ok"] is True

    def test_verify_detects_drift(self, tmp_path):
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"DEMDATA" * 64)
        rec = record_dem_provenance(str(dem))
        dem.write_bytes(b"DEMDATA" * 65)
        res = verify_dem_provenance(rec)
        assert res["ok"] is False
        assert res["reason"] == "hash_mismatch"

    def test_record_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            record_dem_provenance(str(tmp_path / "nope.tif"))

    def test_save_load_round_trip(self, tmp_path):
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"DEMDATA")
        rec = record_dem_provenance(str(dem), provider="provider")
        out = str(tmp_path / "provenance.json")
        save_dem_provenance(rec, out)
        loaded = load_dem_provenance(out)
        assert loaded.sha256 == rec.sha256
        assert loaded.provider == "provider"


# -------------------------------------------- elevation profile invariants
class TestElevationStructure:
    def _root(self, roads):
        root = ET.Element("OpenDRIVE")
        for r in roads:
            root.append(r)
        return root

    def test_valid_piecewise_ok(self):
        road = _elevation_profile(_road("1", 100.0),
                                  [(0.0, 100.0, 0.02, 0.0, 0.0),
                                   (40.0, 100.8, -0.02, 0.0, 0.0)])
        res = validate_elevation_profile_structure(self._root([road]))
        assert res["ok"] is True

    def test_single_linear_long_road_fails_elv002(self):
        road = _elevation_profile(_road("1", 100.0), [(0.0, 100.0, 0.05, 0.0, 0.0)])
        res = validate_elevation_profile_structure(self._root([road]))
        assert res["ok"] is False
        assert any(i["rule"] == "ELV-002" for i in res["issues"])

    def test_unordered_segments_fail_elv003(self):
        road = _elevation_profile(_road("1", 100.0),
                                  [(40.0, 100.8, 0.0, 0.0, 0.0),
                                   (0.0, 100.0, 0.02, 0.0, 0.0)])
        res = validate_elevation_profile_structure(self._root([road]))
        assert res["ok"] is False
        assert any(i["rule"] == "ELV-003" for i in res["issues"])

    def test_c0_gap_fails_elv004(self):
        road = _elevation_profile(_road("1", 100.0),
                                  [(0.0, 100.0, 0.02, 0.0, 0.0),
                                   (40.0, 500.0, 0.0, 0.0, 0.0)])
        res = validate_elevation_profile_structure(self._root([road]))
        assert res["ok"] is False
        assert any(i["rule"] == "ELV-004" for i in res["issues"])

    def test_flat_missing_profile_warns(self):
        road = _road("1", 100.0)
        res = validate_elevation_profile_structure(self._root([road]))
        assert res["ok"] is True
        assert any(i["severity"] == "warn" for i in res["issues"])


# --------------------------------------------------- lane structure invariants
class TestLaneStructure:
    def _root(self, roads):
        root = ET.Element("OpenDRIVE")
        for r in roads:
            root.append(r)
        return root

    def test_valid_structure_ok(self):
        road = _lanes(_road("1", 100.0), [(0.0, [1, 2])])
        res = validate_lane_structure(self._root([road]))
        assert res["ok"] is True

    def test_first_section_not_zero_fails(self):
        road = _lanes(_road("1", 100.0), [(25.0, [1])])
        res = validate_lane_structure(self._root([road]))
        assert res["ok"] is False
        assert any(i["rule"] == "LAN-001" for i in res["issues"])

    def test_missing_center_lane_fails(self):
        road = _road("1", 100.0)
        lanes = ET.SubElement(road, "lanes")
        section = ET.SubElement(lanes, "laneSection", s="0.0")
        left = ET.SubElement(section, "left")
        lane = ET.SubElement(left, "lane", id="1")
        ET.SubElement(lane, "width", sOffset="0", a="3.5")
        res = validate_lane_structure(self._root([road]))
        assert res["ok"] is False
        assert any(i["rule"] == "LAN-002" for i in res["issues"])

    def test_duplicate_lane_ids_fail(self):
        road = _road("1", 100.0)
        lanes = ET.SubElement(road, "lanes")
        section = ET.SubElement(lanes, "laneSection", s="0.0")
        ET.SubElement(section, "center").append(ET.Element("lane", id="0"))
        left = ET.SubElement(section, "left")
        for lid in ("1", "1"):
            lane = ET.SubElement(left, "lane", id=lid)
            ET.SubElement(lane, "width", sOffset="0", a="3.5")
        res = validate_lane_structure(self._root([road]))
        assert res["ok"] is False
        assert any(i["rule"] == "LAN-002" for i in res["issues"])

    def test_negative_width_fails(self):
        road = _road("1", 100.0)
        lanes = ET.SubElement(road, "lanes")
        section = ET.SubElement(lanes, "laneSection", s="0.0")
        ET.SubElement(section, "center").append(ET.Element("lane", id="0"))
        lane = ET.SubElement(ET.SubElement(section, "left"), "lane", id="1")
        ET.SubElement(lane, "width", sOffset="0", a="-2.0")
        res = validate_lane_structure(self._root([road]))
        assert res["ok"] is False
        assert any(i["rule"] == "LAN-007" for i in res["issues"])

    def test_unordered_lane_offsets_fail(self):
        road = _road("1", 100.0)
        lanes = ET.SubElement(road, "lanes")
        section = ET.SubElement(lanes, "laneSection", s="0.0")
        ET.SubElement(section, "center").append(ET.Element("lane", id="0"))
        ET.SubElement(lanes, "laneOffset", s="5.0", a="0.5")
        ET.SubElement(lanes, "laneOffset", s="0.0", a="0.1")
        res = validate_lane_structure(self._root([road]))
        assert res["ok"] is False
        assert any(i["rule"] == "LAN-009" for i in res["issues"])
