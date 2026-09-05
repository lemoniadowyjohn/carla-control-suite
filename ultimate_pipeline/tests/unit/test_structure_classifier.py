# Round-6: structure_classifier.py (F3) already has a complete, correct
# bridge/tunnel elevation *policy* (STRUCTURE_PROFILE_POLICY, structure_road_ids,
# apply_dem_structure_gate) but had zero dedicated tests before this file, and
# was never wired into the live pipeline (see stage_05_geometry.py's new
# structure-classification block). These tests lock in the policy semantics the
# wiring depends on.
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pyproj import CRS, Transformer

from ultimate_pipeline.enrichment.structure_classifier import (
    OSM2ODR_NATIVE_PROJ4,
    _classify_road_centreline,
    _wgs84_to_native_transformer,
    apply_dem_structure_gate,
    classify_xodr_roads,
    structure_road_ids,
)


def _native_xy(lon: float, lat: float) -> tuple[float, float]:
    tf = Transformer.from_crs(
        CRS.from_epsg(4326), CRS.from_proj4(OSM2ODR_NATIVE_PROJ4), always_xy=True
    )
    x, y = tf.transform(lon, lat)
    return float(x), float(y)


def _write_fixture(tmp_path: Path, monkeypatch) -> tuple[str, str, dict]:
    """A bridge-tagged way + an unrelated plain way, both projected into the
    real Osm2Odr native frame so classify_xodr_roads's real spatial-matching
    code runs unmodified -- only the F1 CRS-contract *identity check* is
    monkeypatched, since establishing that independently is a whole other
    module's concern (dem_crs_contract.py), not what this test is about."""
    bridge_lon0, bridge_lat0 = 11.0, 48.0
    bridge_lon1, bridge_lat1 = 11.0005, 48.0
    far_lon0, far_lat0 = 12.0, 49.0
    far_lon1, far_lat1 = 12.0005, 49.0

    osm_path = tmp_path / "fixture.osm"
    osm_path.write_text(
        f"""<osm version="0.6">
          <node id="1" lat="{bridge_lat0}" lon="{bridge_lon0}"/>
          <node id="2" lat="{bridge_lat1}" lon="{bridge_lon1}"/>
          <node id="3" lat="{far_lat0}" lon="{far_lon0}"/>
          <node id="4" lat="{far_lat1}" lon="{far_lon1}"/>
          <way id="100">
            <nd ref="1"/><nd ref="2"/>
            <tag k="bridge" v="yes"/>
          </way>
          <way id="101">
            <nd ref="3"/><nd ref="4"/>
            <tag k="highway" v="residential"/>
          </way>
        </osm>""",
        encoding="utf-8",
    )

    bx0, by0 = _native_xy(bridge_lon0, bridge_lat0)
    bx1, by1 = _native_xy(bridge_lon1, bridge_lat0)
    fx0, fy0 = _native_xy(far_lon0, far_lat0)
    fx1, fy1 = _native_xy(far_lon1, far_lat0)

    import math

    bridge_len = math.hypot(bx1 - bx0, by1 - by0)
    bridge_hdg = math.atan2(by1 - by0, bx1 - bx0)
    far_len = math.hypot(fx1 - fx0, fy1 - fy0)
    far_hdg = math.atan2(fy1 - fy0, fx1 - fx0)

    xodr_path = tmp_path / "fixture.xodr"
    root = ET.Element("OpenDRIVE")
    for rid, x0, y0, hdg, length in (
        ("bridge_road", bx0, by0, bridge_hdg, bridge_len),
        ("plain_road", fx0, fy0, far_hdg, far_len),
    ):
        road = ET.SubElement(root, "road", id=rid, junction="-1", length=str(length))
        pv = ET.SubElement(road, "planView")
        geom = ET.SubElement(
            pv, "geometry", s="0", x=str(x0), y=str(y0), hdg=str(hdg), length=str(length)
        )
        ET.SubElement(geom, "line")
    ET.ElementTree(root).write(str(xodr_path), encoding="unicode")

    monkeypatch.setattr(
        "ultimate_pipeline.enrichment.structure_classifier._wgs84_to_native_transformer",
        lambda xodr_path, osm_path: (
            Transformer.from_crs(
                CRS.from_epsg(4326), CRS.from_proj4(OSM2ODR_NATIVE_PROJ4), always_xy=True
            ),
            {"verdict": "OSM2ODR_NATIVE_VERIFIED", "native_frame": OSM2ODR_NATIVE_PROJ4},
        ),
    )

    return str(xodr_path), str(osm_path), {"bridge_road": "bridge_road", "plain_road": "plain_road"}


class TestWgs84ToNativeTransformerCrsFallback:
    """Round-6 real-regen catch: the real Ingolstadt candidate's F1 CRS
    contract resolves to AMBIGUOUS (both the claimed geoReference and the
    Osm2Odr native frame are geographically plausible against the OSM
    bounds) -- resolve_sampling_crs (what DEM sampling itself uses) already
    handles this by falling back to the claimed CRS with a warning, but
    _wgs84_to_native_transformer only ever accepted the narrower
    OSM2ODR_NATIVE_VERIFIED verdict, so structure classification always
    raised on the real map even though DEM elevation sampling succeeded fine
    for the exact same file. This broke a real end-to-end regen."""

    def test_ambiguous_verdict_succeeds_via_claimed_crs_fallback(self, tmp_path, monkeypatch):
        claimed_crs = CRS.from_proj4(OSM2ODR_NATIVE_PROJ4)
        record = {"verdict": "AMBIGUOUS", "reason": "both_frames_plausible;prefer_claimed_with_warning"}
        monkeypatch.setattr(
            "ultimate_pipeline.enrichment.structure_classifier.resolve_sampling_crs",
            lambda xodr_path, osm_path=None, strict=True: (claimed_crs, "claimed_geoReference_ambiguous", record),
        )
        tf, returned_record = _wgs84_to_native_transformer("whatever.xodr", "whatever.osm")
        x, y = tf.transform(11.0, 48.0)
        assert x != 0.0 or y != 0.0
        assert returned_record["verdict"] == "AMBIGUOUS"

    def test_unresolved_verdict_still_raises(self, tmp_path, monkeypatch):
        def _raise(xodr_path, osm_path=None, strict=True):
            raise RuntimeError("F1 CRS contract unresolved: cannot establish the geographic frame")

        monkeypatch.setattr(
            "ultimate_pipeline.enrichment.structure_classifier.resolve_sampling_crs", _raise
        )
        with pytest.raises(RuntimeError, match="F1 CRS contract unresolved"):
            _wgs84_to_native_transformer("whatever.xodr", "whatever.osm")


class _BruteForceIndex:
    """Reference oracle: candidate set = every structure, regardless of
    query point (i.e. the pre-fix behavior of scanning all structures per
    point). Used to prove the real spatial index never drops a true match."""

    def __init__(self, n: int) -> None:
        self._all = list(range(n))

    def candidate_indices_near(self, x: float, y: float, max_dist_m: float) -> list:
        return self._all


class TestClassifyRoadCentrelineSpatialIndexEquivalence:
    """Round-6 perf fix: classify_xodr_roads took >10 minutes on the real
    32,267-road map because _classify_road_centreline scanned every OSM
    structure way for every sampled road point (same bug class as
    crosswalk_writer.py's nearest_point_on_road, fixed earlier this round).
    _StructureSpatialIndex must return results identical to the brute-force
    full scan, not just "fast" -- these tests hold it to that bar directly."""

    def _scattered_structures(self):
        import itertools

        classes = ["bridge", "tunnel", "covered", "embankment"]
        structures = []
        for i, (gx, gy) in enumerate(itertools.product(range(0, 2000, 100), range(0, 2000, 400))):
            structures.append({
                "way_id": f"w{i}",
                "class": classes[i % len(classes)],
                "polyline_m": [(float(gx), float(gy)), (float(gx) + 60.0, float(gy) + 15.0)],
            })
        return structures

    def test_spatial_index_matches_brute_force_full_scan(self):
        import math as _math

        structures = self._scattered_structures()
        pts = [
            (float(x), 20.0 + 8.0 * _math.sin(x / 137.0))
            for x in range(0, 2000, 5)
        ]
        buffer_m = 12.0
        class_fraction = 0.6

        fast_index = None  # let _classify_road_centreline build its real spatial index
        fast_result = _classify_road_centreline(
            pts, structures, buffer_m, class_fraction, spatial_index=fast_index
        )
        brute_result = _classify_road_centreline(
            pts, structures, buffer_m, class_fraction,
            spatial_index=_BruteForceIndex(len(structures)),
        )
        assert fast_result["class"] == brute_result["class"]
        assert fast_result["coverage_by_class"] == brute_result["coverage_by_class"]
        assert fast_result["matched_structures"] == brute_result["matched_structures"]
        assert abs(fast_result["matched_length_m"] - brute_result["matched_length_m"]) < 1e-9


class TestClassifyXodrRoads:
    def test_bridge_matched(self, tmp_path, monkeypatch):
        xodr_path, osm_path, ids = _write_fixture(tmp_path, monkeypatch)
        result = classify_xodr_roads(xodr_path, osm_path=osm_path)
        assert result["ok"] is True
        assert result["per_road"][ids["bridge_road"]]["class"] == "bridge"

    def test_unmatched_road_is_terrain_following(self, tmp_path, monkeypatch):
        xodr_path, osm_path, ids = _write_fixture(tmp_path, monkeypatch)
        result = classify_xodr_roads(xodr_path, osm_path=osm_path)
        assert result["per_road"][ids["plain_road"]]["class"] == "terrain_following"


class TestStructureRoadIds:
    def test_excludes_unknown_and_terrain_following_and_covered(self):
        classification = {
            "per_road": {
                "a": {"class": "bridge"},
                "b": {"class": "unknown"},
                "c": {"class": "terrain_following"},
                "d": {"class": "covered"},
                "e": {"class": "tunnel"},
            }
        }
        assert structure_road_ids(classification) == ["a", "e"]


class TestApplyDemStructureGate:
    def test_raises_when_strict_and_identity_not_established(self):
        with pytest.raises(RuntimeError):
            apply_dem_structure_gate({"ok": False}, strict=True)

    def test_skips_without_raising_when_not_strict(self):
        result = apply_dem_structure_gate({"ok": False}, strict=False)
        assert result["gate"] == "SKIPPED"

    def test_passes_when_identity_established(self):
        classification = {
            "ok": True,
            "class_counts": {"bridge": 2, "terrain_following": 10},
            "per_road": {
                "a": {"class": "bridge"}, "b": {"class": "bridge"},
                **{str(i): {"class": "terrain_following"} for i in range(10)},
            },
        }
        result = apply_dem_structure_gate(classification, strict=True)
        assert result["gate"] == "PASS"
        assert result["structure_road_count"] == 2
