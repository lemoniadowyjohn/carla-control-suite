"""Tests for O3 tile frame consistency proof."""
from __future__ import annotations

import json
from pathlib import Path

from tools.tile_frame_consistency import generate_report


def _cook(tmp_path: Path, offsets: list[list[float]], bounds: list[list[list[float]] | None]):
    root = tmp_path / "artifacts"
    results = []
    for i, (tx, ty) in enumerate(((0, 0), (1, 0), (0, 1))):
        d = root / f"tile_{tx}_{ty}"
        d.mkdir(parents=True)
        manifest = d / f"Ingolstadt_Tile_{tx}_{ty}.tile_fbx.json"
        manifest.write_text(json.dumps({"source_provenance": {"map_of_record_sha256": "a" * 64, "header_offset_xy": offsets[i]}}))
        (d / f"Ingolstadt_Tile_{tx}_{ty}.fbx").write_bytes(b"fbx")
        if bounds[i] is not None:
            (d / "fbx_roundtrip_manifest.json").write_text(json.dumps({"objects": [{"bounds": bounds[i]}]}))
        results.append({"fbx_name": f"Ingolstadt_Tile_{tx}_{ty}.fbx", "tile_index": [tx, ty]})
    p = tmp_path / "COOK_RESULTS.json"
    p.write_text(json.dumps({"source_provenance": {"map_of_record_sha256": "a" * 64}, "results": results}))
    return p


def test_same_frame_is_pass_and_has_frame_hash(tmp_path: Path):
    p = _cook(tmp_path, [[1.0, 2.0]] * 3, [[[0, 0, 0], [1, 1, 1]]] * 3)
    report = generate_report(p, 1000.0, [1.0, 2.0])
    assert report["status"] == "PASS"
    assert report["frame_identity_count"] == 1
    assert report["frame_identity_hash"]


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
