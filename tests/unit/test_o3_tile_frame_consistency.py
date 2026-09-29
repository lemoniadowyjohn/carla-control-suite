"""Tests for O3 tile frame consistency proof.

GAP-031: the prior version of this tool never applied any tile-placement
transform (comparing two independently-OSM2World-auto-centered local frames
directly) and its per-pair ``status`` was dead code (initialized to
"INCOMPLETE", never reassigned -- ``report["status"]`` was driven only by
manifest/SHA presence, never by any seam-delta judgement). These tests cover
both the old (still-valid) frame-offset/SHA-provenance checks AND the new,
real world-frame seam check this file adds:

  * ``test_real_evidence_reproduces_gap031_north_south_defect`` runs the tool
    against the actual committed full-grid cook evidence
    (``reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK``)
    and asserts it now independently reproduces the ~170-270m north-south
    seam defect documented in
    ``reports/verification/O3_FULLGRID_VERIFICATION_20260929.md`` -- the
    single most important regression here, since it proves both that the
    dead per-pair ``status`` is now real (FAIL, not permanently INCOMPLETE)
    and that the fix's numbers agree with an independently-derived,
    differently-sampled ground truth.
  * The synthetic PASS/FAIL pair below constructs two tiny, fully-controlled
    OSM fixtures (via exact inverse-projection of a chosen target local
    point) proving the seam check assigns real PASS *and* real FAIL
    depending on the actual geometry -- not a hardcoded constant either way.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pyproj import Transformer

from tools.tile_frame_consistency import generate_report

_INV_TRANSFORMER = Transformer.from_crs(
    "+proj=tmerc +datum=WGS84 +units=m +no_defs", "EPSG:4326", always_xy=True
)


def _cook(tmp_path: Path, offsets: list[list[float]], bounds: list[list[list[float]] | None],
          osm_local_centers: list[tuple[float, float] | None] | None = None):
    """Build a synthetic COOK_RESULTS.json + per-tile artifacts fixture.

    ``osm_local_centers[i]``, when given, is the exact local-frame (x, y)
    point this tile's synthetic OSM XML's two nodes should bbox-center on
    (computed via exact inverse tmerc projection, then rebased by that
    tile's own ``offsets[i]`` header offset) -- giving full, non-tautological
    control over ``world_placement_offset_m`` for each tile.
    """
    root = tmp_path / "artifacts"
    results = []
    osm_local_centers = osm_local_centers or [None, None, None]
    for i, (tx, ty) in enumerate(((0, 0), (1, 0), (0, 1))):
        d = root / f"tile_{tx}_{ty}"
        d.mkdir(parents=True)
        manifest = d / f"Ingolstadt_Tile_{tx}_{ty}.tile_fbx.json"
        manifest.write_text(json.dumps({"source_provenance": {"map_of_record_sha256": "a" * 64, "header_offset_xy": offsets[i]}}))
        (d / f"Ingolstadt_Tile_{tx}_{ty}.fbx").write_bytes(b"fbx")
        if bounds[i] is not None:
            (d / "fbx_roundtrip_manifest.json").write_text(json.dumps({"objects": [{"bounds": bounds[i]}]}))
        center = osm_local_centers[i]
        if center is not None:
            ox, oy = offsets[i]
            gx, gy = center[0] + ox, center[1] + oy
            # Two nodes symmetric (+-5m in projected space) around the target
            # so their bbox center is (to sub-mm precision) exactly `center`.
            lon, lat = _INV_TRANSFORMER.transform(gx - 5.0, gy - 5.0)
            lon2, lat2 = _INV_TRANSFORMER.transform(gx + 5.0, gy + 5.0)
            osm_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6">\n'
                f'  <node id="-1" lat="{lat:.9f}" lon="{lon:.9f}"/>\n'
                f'  <node id="-2" lat="{lat2:.9f}" lon="{lon2:.9f}"/>\n'
                "</osm>\n"
            )
            (d / f"Ingolstadt_Tile_{tx}_{ty}.osm").write_text(osm_xml, encoding="utf-8")
        results.append({"fbx_name": f"Ingolstadt_Tile_{tx}_{ty}.fbx", "tile_index": [tx, ty]})
    p = tmp_path / "COOK_RESULTS.json"
    p.write_text(json.dumps({"source_provenance": {"map_of_record_sha256": "a" * 64}, "results": results}))
    return p


def test_same_frame_is_pass_and_has_frame_hash(tmp_path: Path):
    # Each tile's OSM bbox center is placed exactly on its own nominal grid
    # corner (tx*1000, ty*1000) -> zero placement correction everywhere ->
    # zero world-frame seam delta between every adjacent pair -> real PASS.
    p = _cook(
        tmp_path, [[1.0, 2.0]] * 3, [[[0, 0, 0], [1, 1, 1]]] * 3,
        osm_local_centers=[(0.0, 0.0), (1000.0, 0.0), (0.0, 1000.0)],
    )
    report = generate_report(p, 1000.0, [1.0, 2.0])
    assert report["status"] == "PASS"
    assert report["frame_identity_count"] == 1
    assert report["frame_identity_hash"]
    assert all(pair["status"] == "PASS" for pair in report["adjacent_pairs"])
    for pair in report["adjacent_pairs"]:
        assert pair["world_seam_delta_m"] < 1e-3


def test_real_world_seam_defect_is_a_real_fail_not_dead_code(tmp_path: Path):
    """The core GAP-031 regression: a genuine placement inconsistency must
    produce a real per-pair and top-level FAIL, not the old permanently-
    "INCOMPLETE" dead-code status."""
    p = _cook(
        tmp_path, [[1.0, 2.0]] * 3, [[[0, 0, 0], [1, 1, 1]]] * 3,
        # tile (0, 1)'s true center is shoved 250m off its nominal grid
        # corner ON THE Y (north-south) AXIS -- e.g. a real OSM2World-style
        # per-tile auto-centering drift -- while (0, 0) and (1, 0) remain
        # perfectly nominal, so only the (0,0)<->(0,1) y-axis pair should FAIL.
        osm_local_centers=[(0.0, 0.0), (1000.0, 0.0), (0.0, 1250.0)],
    )
    report = generate_report(p, 1000.0, [1.0, 2.0], world_seam_tolerance_m=10.0)
    assert report["status"] == "FAIL"
    pairs_by_axis = {(tuple(p["left_tile"]), tuple(p["right_tile"])): p for p in report["adjacent_pairs"]}
    y_pair = pairs_by_axis[((0, 0), (0, 1))]
    assert y_pair["axis"] == "y"
    assert y_pair["status"] == "FAIL"
    assert y_pair["world_seam_delta_m"] == pytest.approx(250.0, abs=1e-2)
    x_pair = pairs_by_axis[((0, 0), (1, 0))]
    assert x_pair["status"] == "PASS"
    assert any("exceeds tolerance" in f for f in report["failures"])


def test_frame_drift_is_incomplete(tmp_path: Path):
    p = _cook(tmp_path, [[1.0, 2.0], [9.0, 2.0], [1.0, 2.0]], [[[0, 0, 0], [1, 1, 1]]] * 3)
    report = generate_report(p, 1000.0, [1.0, 2.0])
    assert report["status"] == "INCOMPLETE"
    assert any("frame offset differs" in failure for failure in report["failures"])


def test_missing_exported_bounds_is_incomplete(tmp_path: Path):
    p = _cook(tmp_path, [[1.0, 2.0]] * 3, [[[0, 0, 0], [1, 1, 1]], None, [[0, 0, 0], [1, 1, 1]]])
    report = generate_report(p, 1000.0, [1.0, 2.0])
    assert report["status"] == "INCOMPLETE"
    assert report["max_seam_delta_m"] is not None


def test_missing_osm_source_is_incomplete_not_silent_pass(tmp_path: Path):
    """No OSM source at all (e.g. an older cook run) means world-frame
    placement cannot be independently verified -- this must be surfaced as
    INCOMPLETE, never silently reported as PASS (the exact failure mode
    GAP-031 found in the tool's previous version)."""
    p = _cook(tmp_path, [[0.0, 0.0]] * 3, [[[0, 0, 0], [1, 1, 1]]] * 3)
    report = generate_report(p, 1000.0, [0.0, 0.0])
    assert report["status"] == "INCOMPLETE"
    assert all(pair["world_seam_delta_m"] is None for pair in report["adjacent_pairs"])
    assert any("no OSM source available" in failure for failure in report["failures"])


def test_adjacent_pairs_and_expected_shared_border(tmp_path: Path):
    p = _cook(tmp_path, [[0.0, 0.0]] * 3, [None, None, None])
    report = generate_report(p, 1000.0, [0.0, 0.0])
    assert report["status"] == "INCOMPLETE"
    assert len(report["adjacent_pairs"]) == 2
    assert {pair["axis"] for pair in report["adjacent_pairs"]} == {"x", "y"}
    assert all(pair["expected_shared_border_m"] == 1000.0 for pair in report["adjacent_pairs"])


def test_source_sha_drift_is_incomplete(tmp_path: Path):
    p = _cook(tmp_path, [[0.0, 0.0]] * 3, [[[0, 0, 0], [1, 1, 1]]] * 3)
    doc = json.loads(p.read_text())
    doc["source_provenance"]["map_of_record_sha256"] = "b" * 64
    p.write_text(json.dumps(doc))
    report = generate_report(p, 1000.0, [0.0, 0.0])
    assert report["status"] == "INCOMPLETE"
    assert any("source SHA differs" in failure for failure in report["failures"])


def test_real_evidence_reproduces_gap031_north_south_defect():
    """Run the fixed tool against the actual committed full-grid cook
    evidence and confirm it independently reproduces GAP-031's ~170-270m
    north-south seam defect (reports/verification/O3_FULLGRID_VERIFICATION_20260929.md),
    via a completely different sampling method (every building-footprint node
    in each tile's own OSM XML, vs. that report's sparse 5-14 named-building
    sample) -- cross-validating both the fix and the original finding.
    """
    repo_root = Path(__file__).resolve().parents[2]
    cook_results = (
        repo_root / "reports" / "production_readiness"
        / "20260924T100614Z_FULL_GRID_TILE_FBX_COOK" / "COOK_RESULTS.json"
    )
    if not cook_results.is_file():
        pytest.skip("real full-grid cook evidence not present in this checkout")

    report = generate_report(cook_results, 1000.0, [832671.676, 5458671.104])

    # The dead-code regression: pair status must be a real, computed verdict.
    assert {pair["status"] for pair in report["adjacent_pairs"]} <= {"PASS", "FAIL", "INCOMPLETE"}
    assert any(pair["status"] == "FAIL" for pair in report["adjacent_pairs"])
    assert report["status"] == "FAIL"

    pairs_by_tiles = {(tuple(p["left_tile"]), tuple(p["right_tile"])): p for p in report["adjacent_pairs"]}

    ns_pair_1 = pairs_by_tiles[((8, 8), (8, 9))]
    assert ns_pair_1["axis"] == "y"
    assert ns_pair_1["status"] == "FAIL"
    # O3's independent finding: 176.5m (sparse named-building sample).
    assert 100.0 < ns_pair_1["world_seam_delta_m"] < 260.0

    ns_pair_2 = pairs_by_tiles[((7, 8), (7, 9))]
    assert ns_pair_2["axis"] == "y"
    assert ns_pair_2["status"] == "FAIL"
    # O3's independent finding: 270.1m (sparse named-building sample).
    assert 150.0 < ns_pair_2["world_seam_delta_m"] < 400.0
