# ultimate_pipeline/tools/evaluate_tiling.py -- zero prior test coverage.
#
# Not directly imported by the live run_full_domain_gap.py flow at runtime
# (_auto_generate_correspondence there is defined but never called -- dead
# code, superseded by the documented manual workflow: run this script's CLI
# to produce correspondence.csv, then point run_full_domain_gap.py at it via
# UP_TILE_CORRESPONDENCE_CSV). That documented manual workflow is the real,
# human-run path that feeds RQ1 domain-gap tile correspondence, so this is
# still worth covering even though nothing imports it at runtime.
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pytest

from ultimate_pipeline.tools import evaluate_tiling as et


# ---------------------------------------------------------------------------
# _bbox_iou
# ---------------------------------------------------------------------------

def test_bbox_iou_identical_boxes_is_one():
    box = (0.0, 0.0, 10.0, 10.0)
    assert et._bbox_iou(box, box) == pytest.approx(1.0)


def test_bbox_iou_disjoint_boxes_is_zero():
    a = (0.0, 0.0, 10.0, 10.0)
    b = (100.0, 100.0, 110.0, 110.0)
    assert et._bbox_iou(a, b) == 0.0


def test_bbox_iou_half_overlap():
    a = (0.0, 0.0, 10.0, 10.0)
    b = (5.0, 0.0, 15.0, 10.0)
    # intersection = 5x10=50, union = 100+100-50=150
    assert et._bbox_iou(a, b) == pytest.approx(50.0 / 150.0)


def test_bbox_iou_touching_edges_is_zero():
    a = (0.0, 0.0, 10.0, 10.0)
    b = (10.0, 0.0, 20.0, 10.0)
    assert et._bbox_iou(a, b) == 0.0


# ---------------------------------------------------------------------------
# _frame_diagnosis
# ---------------------------------------------------------------------------

def test_frame_diagnosis_empty_is_unknown():
    result = et._frame_diagnosis([])
    assert result["label"] == "unknown"
    assert result["min"] is None


def test_frame_diagnosis_degrees_label():
    coords = [11.4, 48.7, 11.5, 48.8]
    result = et._frame_diagnosis(coords)
    assert result["label"] == "degrees"


def test_frame_diagnosis_local_meters_label():
    coords = [1200.0, 3400.0, -1500.0, 5000.0]
    result = et._frame_diagnosis(coords)
    assert result["label"] == "local_meters"


def test_frame_diagnosis_projected_meters_label():
    coords = [690000.0, 5400000.0, 691000.0, 5401000.0]
    result = et._frame_diagnosis(coords)
    assert result["label"] == "projected_meters"


# ---------------------------------------------------------------------------
# _parse_bbox
# ---------------------------------------------------------------------------

def test_parse_bbox_list_form():
    meta = {"core_bbox": [1.0, 2.0, 3.0, 4.0]}
    assert et._parse_bbox(meta) == (1.0, 2.0, 3.0, 4.0)


def test_parse_bbox_dict_min_max_keys():
    meta = {"bbox": {"min_x": 1.0, "min_y": 2.0, "max_x": 3.0, "max_y": 4.0}}
    assert et._parse_bbox(meta) == (1.0, 2.0, 3.0, 4.0)


def test_parse_bbox_nested_core_key():
    meta = {"bounds": {"core": {"min_x": 1.0, "min_y": 2.0, "max_x": 3.0, "max_y": 4.0}}}
    assert et._parse_bbox(meta) == (1.0, 2.0, 3.0, 4.0)


def test_parse_bbox_min_max_list_pair():
    meta = {"bbox": {"min": [1.0, 2.0], "max": [3.0, 4.0]}}
    assert et._parse_bbox(meta) == (1.0, 2.0, 3.0, 4.0)


def test_parse_bbox_missing_returns_none():
    assert et._parse_bbox({}) is None


def test_parse_bbox_malformed_short_list_returns_none():
    meta = {"core_bbox": [1.0, 2.0]}
    assert et._parse_bbox(meta) is None


# ---------------------------------------------------------------------------
# _match_tiles
# ---------------------------------------------------------------------------

def _idx(entries):
    """entries: dict[str, (minx, miny, maxx, maxy)] -> built index"""
    meta = {k: {"core_bbox": list(v)} for k, v in entries.items()}
    return et._build_index(meta)


def test_match_tiles_exact_grid_all_match():
    a = _idx({"a0": (0, 0, 10, 10), "a1": (10, 0, 20, 10)})
    b = _idx({"b0": (0, 0, 10, 10), "b1": (10, 0, 20, 10)})
    matches, stats = et._match_tiles(a, b, max_dist_mult=3.0, min_iou=0.5)
    assert stats["matched"] == 2
    assert stats["unmatched_a"] == 0
    assert stats["unmatched_b"] == 0
    pairs = {(m["a_tile"], m["b_tile"]) for m in matches}
    assert pairs == {("a0", "b0"), ("a1", "b1")}


def test_match_tiles_conflict_resolved_by_smaller_distance():
    # b0 is closer to a0 than b1 is; both would want a0 if not for the gate.
    a = _idx({"a0": (0, 0, 10, 10)})
    b = _idx({"b0": (0.1, 0, 10.1, 10), "b1": (2, 0, 12, 10)})
    matches, stats = et._match_tiles(a, b, max_dist_mult=5.0, min_iou=0.01)
    assert stats["matched"] == 1
    assert matches[0]["b_tile"] == "b0"
    assert stats["unmatched_b"] == 1


def test_match_tiles_min_iou_gate_excludes_low_overlap():
    a = _idx({"a0": (0, 0, 10, 10)})
    b = _idx({"b0": (9, 0, 19, 10)})  # 10% overlap: iou = 10/190 ~ 0.0526
    matches, stats = et._match_tiles(a, b, max_dist_mult=10.0, min_iou=0.5)
    assert stats["matched"] == 0


def test_match_tiles_max_dist_gate_excludes_far_tiles():
    a = _idx({"a0": (0, 0, 10, 10)})
    b = _idx({"b0": (1000, 1000, 1010, 1010)})
    matches, stats = et._match_tiles(a, b, max_dist_mult=3.0, min_iou=0.0)
    assert stats["matched"] == 0


def test_match_tiles_empty_indices():
    matches, stats = et._match_tiles({}, {}, max_dist_mult=3.0, min_iou=0.01)
    assert matches == []
    assert stats["matched"] == 0
    assert stats["unmatched_a"] == 0
    assert stats["unmatched_b"] == 0


# ---------------------------------------------------------------------------
# _loose_translation / _apply_translation
# ---------------------------------------------------------------------------

def test_loose_translation_median_of_matches():
    matches = [
        {"dx": 10.0, "dy": -5.0},
        {"dx": 12.0, "dy": -4.0},
        {"dx": 8.0, "dy": -6.0},
    ]
    dx, dy = et._loose_translation(matches)
    assert dx == 10.0
    assert dy == -5.0


def test_loose_translation_no_matches_is_zero():
    assert et._loose_translation([]) == (0.0, 0.0)


def test_apply_translation_shifts_bbox_and_center():
    idx = _idx({"a0": (0, 0, 10, 10)})
    shifted = et._apply_translation(idx, 5.0, -3.0)
    assert shifted["a0"]["bbox"] == (5.0, -3.0, 15.0, 7.0)
    assert shifted["a0"]["center"] == (5.0 + 5.0, 5.0 - 3.0)
    # diag must be preserved (shape doesn't change under translation)
    assert shifted["a0"]["diag"] == idx["a0"]["diag"]


# ---------------------------------------------------------------------------
# evaluate() end-to-end via real files
# ---------------------------------------------------------------------------

def _write_meta(path: Path, tiles: dict) -> None:
    payload = {"tiles": {k: {"core_bbox": list(v)} for k, v in tiles.items()}}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _default_args(tmp_path: Path, a_meta: Path, b_meta: Path) -> argparse.Namespace:
    return argparse.Namespace(
        a_meta=str(a_meta),
        b_meta=str(b_meta),
        a_metrics=None,
        b_metrics=None,
        out=str(tmp_path / "out"),
        max_dist_mult=3.0,
        min_iou=0.01,
        estimate_translation=False,
        bootstrap_loose=False,
        min_bootstrap_matches=10,
    )


def test_evaluate_end_to_end_produces_correspondence(tmp_path: Path):
    a_meta = tmp_path / "a_meta.json"
    b_meta = tmp_path / "b_meta.json"
    _write_meta(a_meta, {"t0": (0, 0, 500, 500), "t1": (500, 0, 1000, 500)})
    _write_meta(b_meta, {"t0": (0, 0, 500, 500), "t1": (500, 0, 1000, 500)})

    args = _default_args(tmp_path, a_meta, b_meta)
    rc = et.evaluate(args)

    assert rc == 0
    out_dir = Path(args.out)
    assert (out_dir / "correspondence.csv").is_file()
    assert (out_dir / "alignment_stats.json").is_file()
    stats = json.loads((out_dir / "alignment_stats.json").read_text(encoding="utf-8"))
    assert stats["matched"] == 2
    assert stats["unmatched_a"] == 0
    assert stats["unmatched_b"] == 0


def test_evaluate_zero_matches_writes_no_match_diagnosis(tmp_path: Path):
    a_meta = tmp_path / "a_meta.json"
    b_meta = tmp_path / "b_meta.json"
    _write_meta(a_meta, {"t0": (0, 0, 500, 500)})
    _write_meta(b_meta, {"t0": (100000, 100000, 100500, 100500)})

    args = _default_args(tmp_path, a_meta, b_meta)
    rc = et.evaluate(args)

    assert rc == 0
    out_dir = Path(args.out)
    stats = json.loads((out_dir / "alignment_stats.json").read_text(encoding="utf-8"))
    assert stats["matched"] == 0
    assert (out_dir / "NO_MATCH_DIAGNOSIS.txt").is_file()


def test_evaluate_missing_a_meta_returns_error_code(tmp_path: Path, capsys):
    # Real bug: _load_meta -> _load_json does path.read_text() with no
    # try/except, so a missing/malformed --a-meta path raised an unhandled
    # FileNotFoundError/JSONDecodeError instead of hitting the graceful
    # "ERROR: failed to load A metadata..." + return 2 path the code
    # clearly intends (the print message and return code make the intent
    # unambiguous). Fixed: evaluate() now catches (OSError,
    # json.JSONDecodeError) around both _load_meta calls.
    a_meta = tmp_path / "does_not_exist.json"
    b_meta = tmp_path / "b_meta.json"
    _write_meta(b_meta, {"t0": (0, 0, 500, 500)})

    args = _default_args(tmp_path, a_meta, b_meta)
    rc = et.evaluate(args)

    assert rc == 2
    assert "failed to load A metadata" in capsys.readouterr().out


def test_evaluate_malformed_json_returns_error_code(tmp_path: Path, capsys):
    a_meta = tmp_path / "a_meta.json"
    a_meta.write_text("{not valid json", encoding="utf-8")
    b_meta = tmp_path / "b_meta.json"
    _write_meta(b_meta, {"t0": (0, 0, 500, 500)})

    args = _default_args(tmp_path, a_meta, b_meta)
    rc = et.evaluate(args)

    assert rc == 2
    assert "failed to load A metadata" in capsys.readouterr().out


def test_evaluate_bootstrap_loose_recovers_translated_tiles(tmp_path: Path):
    a_meta = tmp_path / "a_meta.json"
    b_meta = tmp_path / "b_meta.json"
    # B is A shifted by a constant (dx=200, dy=100) for every tile -- a
    # uniform coordinate-frame offset that bootstrap-loose is designed to
    # detect and correct before the strict (tight-gate) match.
    a_tiles = {f"t{i}": (i * 500, 0, i * 500 + 500, 500) for i in range(6)}
    b_tiles = {k: (v[0] + 200, v[1] + 100, v[2] + 200, v[3] + 100) for k, v in a_tiles.items()}
    _write_meta(a_meta, a_tiles)
    _write_meta(b_meta, b_tiles)

    args = _default_args(tmp_path, a_meta, b_meta)
    args.bootstrap_loose = True
    args.min_bootstrap_matches = 3
    rc = et.evaluate(args)

    assert rc == 0
    stats = json.loads((Path(args.out) / "alignment_stats.json").read_text(encoding="utf-8"))
    assert stats["matched"] == 6
    assert stats["translation_applied"] is True
    # dx/dy are defined as a_center - b_center (the correction that, when
    # added to B, moves it onto A) -- B was shifted +200/+100 from A, so
    # the correction is the negation.
    assert stats["translation_dx"] == pytest.approx(-200.0)
    assert stats["translation_dy"] == pytest.approx(-100.0)
