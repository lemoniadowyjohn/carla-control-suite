"""ultimate_pipeline/run_determinism_audit.py -- determines whether a thesis determinism
claim is TRUE or FALSE by comparing repeated-run signatures. This pass covers only the pure
classification/comparison/file-signature functions (verdict logic, coefficient of variation,
manifest diffing, xodr/tile-metadata discovery); main()/_run_once (subprocess orchestration of
real pipeline runs) are out of scope, matching this sweep's established pattern. A bug in the
verdict functions here could make a nondeterministic pipeline look deterministic (or vice
versa) in exported thesis evidence. 1843-line module; found untested via the orphaned-.pyc
sweep.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.run_determinism_audit import (
    _all_required_artifacts_exist,
    _classify_signature,
    _classify_verdict,
    _coeff_of_variation,
    _compare_all_manifests,
    _compare_manifests,
    _compute_overall_verdict,
    _compute_topology_cv,
    _count_roads_and_junctions,
    _count_timed_out_runs,
    _count_tiles,
    _find_final_xodr,
    _find_tile_metadata,
    _required_successful_runs_for_request,
    _safe_sha256,
    _should_ignore,
)


# ---------------------------------------------------------------------------
# _should_ignore
# ---------------------------------------------------------------------------

def test_should_ignore_logs_directory():
    assert _should_ignore("logs/run.log") is True
    assert _should_ignore("nested/logs/run.log") is True


def test_should_ignore_log_tmp_cache_extensions():
    assert _should_ignore("output.log") is True
    assert _should_ignore("scratch.tmp") is True
    assert _should_ignore("data.cache") is True


def test_should_ignore_settings_snapshot_has_timestamps():
    assert _should_ignore("run/settings_snapshot.json") is True
    assert _should_ignore("run/domain_gap_settings_snapshot.json") is True


def test_should_ignore_sqlite_db_files():
    assert _should_ignore("state.sqlite") is True
    assert _should_ignore("state.db") is True


def test_should_ignore_normalizes_backslashes():
    assert _should_ignore("logs\\run.log") is True


def test_should_ignore_normal_content_file_is_not_ignored():
    assert _should_ignore("08_final.xodr") is False
    assert _should_ignore("tile_metadata.json") is False


# ---------------------------------------------------------------------------
# _classify_signature
# ---------------------------------------------------------------------------

def _sig(**overrides):
    base = dict(xodr_sha256="a" * 64, tile_metadata_sha256="b" * 64,
                tile_count=4, road_count=100, junction_count=10)
    base.update(overrides)
    return base


def test_classify_signature_identical_to_baseline_is_deterministic():
    baseline = _sig()
    identical, verdict = _classify_signature(_sig(), baseline)
    assert identical is True
    assert verdict == "DETERMINISTIC"


def test_classify_signature_missing_field_is_nondeterministic():
    baseline = _sig()
    identical, verdict = _classify_signature(_sig(xodr_sha256=""), baseline)
    assert identical is False
    assert verdict == "NONDETERMINISTIC"


def test_classify_signature_same_topology_different_hash_is_natural_randomization():
    baseline = _sig()
    identical, verdict = _classify_signature(_sig(xodr_sha256="c" * 64), baseline)
    assert identical is False
    assert verdict == "NATURAL_RANDOMIZATION"


def test_classify_signature_different_topology_is_nondeterministic():
    baseline = _sig()
    identical, verdict = _classify_signature(_sig(xodr_sha256="c" * 64, road_count=101), baseline)
    assert identical is False
    assert verdict == "NONDETERMINISTIC"


# ---------------------------------------------------------------------------
# _compute_overall_verdict
# ---------------------------------------------------------------------------

def test_compute_overall_verdict_needs_at_least_two_signatures():
    assert _compute_overall_verdict([_sig()]) == "VERDICT_UNDETERMINED"
    assert _compute_overall_verdict([]) == "VERDICT_UNDETERMINED"


def test_compute_overall_verdict_all_identical_is_deterministic():
    verdict = _compute_overall_verdict([_sig(), _sig(), _sig()])
    assert verdict == "DETERMINISTIC"


def test_compute_overall_verdict_missing_signature_forces_nondeterministic():
    verdict = _compute_overall_verdict([_sig(), _sig(tile_count=None)])
    assert verdict == "NONDETERMINISTIC"


def test_compute_overall_verdict_same_topology_different_hash_is_natural_randomization():
    verdict = _compute_overall_verdict([_sig(), _sig(xodr_sha256="c" * 64)])
    assert verdict == "NATURAL_RANDOMIZATION"


def test_compute_overall_verdict_topology_mismatch_is_nondeterministic():
    verdict = _compute_overall_verdict([_sig(), _sig(xodr_sha256="c" * 64, road_count=999)])
    assert verdict == "NONDETERMINISTIC"


def test_compute_overall_verdict_comparison_is_deterministic_false_overrides_identical_hashes():
    # Even if the hashes all match, an external comparison_is_deterministic=False must NOT
    # be silently overridden to DETERMINISTIC.
    verdict = _compute_overall_verdict([_sig(), _sig()], comparison_is_deterministic=False)
    assert verdict != "DETERMINISTIC"


# ---------------------------------------------------------------------------
# _required_successful_runs_for_request / _classify_verdict / _count_timed_out_runs
# ---------------------------------------------------------------------------

def test_required_successful_runs_single_request_needs_one():
    assert _required_successful_runs_for_request(1) == 1
    assert _required_successful_runs_for_request(0) == 1


def test_required_successful_runs_multi_request_needs_two():
    assert _required_successful_runs_for_request(2) == 2
    assert _required_successful_runs_for_request(5) == 2


def test_count_timed_out_runs_counts_return_code_124():
    results = [{"return_code": 124}, {"return_code": 0}, {"return_code": 124}]
    assert _count_timed_out_runs(results) == 2


def test_count_timed_out_runs_handles_malformed_entries():
    results = [{"return_code": "not_an_int"}, {}, {"return_code": 124}]
    assert _count_timed_out_runs(results) == 1


def test_classify_verdict_insufficient_runs_undetermined():
    verdict, n_hashes, reason = _classify_verdict(
        runs_successful=1, topology_hashes=["a"], runs_timed_out=0
    )
    assert verdict == "VERDICT_UNDETERMINED"
    assert reason == "insufficient_successful_runs"


def test_classify_verdict_insufficient_runs_due_to_timeouts():
    verdict, n_hashes, reason = _classify_verdict(
        runs_successful=1, topology_hashes=["a"], runs_timed_out=1
    )
    assert verdict == "VERDICT_UNDETERMINED"
    assert reason == "timeouts"


def test_classify_verdict_insufficient_hashes_is_inconclusive():
    verdict, n_hashes, reason = _classify_verdict(
        runs_successful=2, topology_hashes=["a"], runs_timed_out=0
    )
    assert verdict == "INCONCLUSIVE"
    assert reason == "insufficient_hashes"


def test_classify_verdict_matching_hashes_is_deterministic():
    verdict, n_hashes, reason = _classify_verdict(
        runs_successful=2, topology_hashes=["same", "same"], runs_timed_out=0
    )
    assert verdict == "DETERMINISTIC"
    assert n_hashes == 2
    assert reason is None


def test_classify_verdict_differing_hashes_is_nondeterministic():
    verdict, n_hashes, reason = _classify_verdict(
        runs_successful=2, topology_hashes=["hash_a", "hash_b"], runs_timed_out=0
    )
    assert verdict == "NONDETERMINISTIC"


def test_classify_verdict_blank_hashes_filtered_before_counting():
    verdict, n_hashes, reason = _classify_verdict(
        runs_successful=2, topology_hashes=["same", "", "  ", "same"], runs_timed_out=0
    )
    assert n_hashes == 2  # blanks stripped, not counted


# ---------------------------------------------------------------------------
# _coeff_of_variation / _compute_topology_cv
# ---------------------------------------------------------------------------

def test_coeff_of_variation_identical_values_is_zero():
    assert _coeff_of_variation([5.0, 5.0, 5.0]) == 0.0


def test_coeff_of_variation_needs_at_least_two_values():
    assert _coeff_of_variation([5.0]) is None
    assert _coeff_of_variation([]) is None


def test_coeff_of_variation_zero_mean_returns_none():
    assert _coeff_of_variation([0.0, 0.0]) is None


def test_coeff_of_variation_none_values_filtered_out():
    assert _coeff_of_variation([5.0, None, 5.0]) == 0.0


def test_coeff_of_variation_known_value():
    # mean=3, population variance=2/3, std=sqrt(2/3), cv=std/mean
    import math
    cv = _coeff_of_variation([2.0, 3.0, 4.0])
    expected = math.sqrt(2.0 / 3.0) / 3.0
    assert abs(cv - expected) < 1e-9


def test_compute_topology_cv_returns_all_three_keys():
    result = _compute_topology_cv([_sig(), _sig()])
    assert set(result.keys()) == {"tile_count", "road_count", "junction_count"}
    assert result["tile_count"] == 0.0  # identical signatures -> zero variation


# ---------------------------------------------------------------------------
# _all_required_artifacts_exist
# ---------------------------------------------------------------------------

def test_all_required_artifacts_exist_true_when_all_present(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("x", encoding="utf-8")
    b.write_text("y", encoding="utf-8")
    assert _all_required_artifacts_exist([a, b]) is True


def test_all_required_artifacts_exist_false_when_one_missing(tmp_path: Path):
    a = tmp_path / "a.txt"
    a.write_text("x", encoding="utf-8")
    assert _all_required_artifacts_exist([a, tmp_path / "missing.txt"]) is False


def test_all_required_artifacts_exist_empty_list_is_true():
    assert _all_required_artifacts_exist([]) is True


# ---------------------------------------------------------------------------
# _compare_manifests / _compare_all_manifests
# ---------------------------------------------------------------------------

def test_compare_manifests_identical_reports_nothing():
    only_a, only_b, changed = _compare_manifests({"f1": "h1"}, {"f1": "h1"})
    assert only_a == [] and only_b == [] and changed == []


def test_compare_manifests_reports_files_only_in_each_side():
    only_a, only_b, changed = _compare_manifests({"f1": "h1", "f2": "h2"}, {"f1": "h1", "f3": "h3"})
    assert only_a == ["f2"]
    assert only_b == ["f3"]
    assert changed == []


def test_compare_manifests_reports_changed_hash_for_shared_file():
    only_a, only_b, changed = _compare_manifests({"f1": "h1"}, {"f1": "h_different"})
    assert changed == ["f1"]


def test_compare_all_manifests_needs_at_least_two():
    result = _compare_all_manifests([{"f1": "h1"}])
    assert "error" in result


def test_compare_all_manifests_all_identical_is_deterministic():
    result = _compare_all_manifests([{"f1": "h1"}, {"f1": "h1"}, {"f1": "h1"}])
    assert result["is_deterministic"] is True
    assert result["changed_files"] == []


def test_compare_all_manifests_detects_drift_across_any_run():
    result = _compare_all_manifests([{"f1": "h1"}, {"f1": "h1"}, {"f1": "h_drifted"}])
    assert result["is_deterministic"] is False
    assert "f1" in result["changed_files"]


# ---------------------------------------------------------------------------
# File/xodr discovery helpers
# ---------------------------------------------------------------------------

def test_find_final_xodr_prefers_newest_08_final_variant(tmp_path: Path):
    import os
    older = tmp_path / "08_final_v1.xodr"
    newer = tmp_path / "08_final_v2.xodr"
    older.write_text("<OpenDRIVE/>", encoding="utf-8")
    os.utime(older, (1000, 1000))
    newer.write_text("<OpenDRIVE/>", encoding="utf-8")
    os.utime(newer, (2000, 2000))
    assert _find_final_xodr(tmp_path) == newer


def test_find_final_xodr_falls_back_to_plain_name(tmp_path: Path):
    plain = tmp_path / "08_final.xodr"
    plain.write_text("<OpenDRIVE/>", encoding="utf-8")
    assert _find_final_xodr(tmp_path) == plain


def test_find_final_xodr_none_found(tmp_path: Path):
    assert _find_final_xodr(tmp_path) is None


def test_find_tile_metadata_prefers_run_root(tmp_path: Path):
    root_meta = tmp_path / "tile_metadata.json"
    root_meta.write_text("{}", encoding="utf-8")
    (tmp_path / "tiles").mkdir()
    (tmp_path / "tiles" / "tile_metadata.json").write_text("{}", encoding="utf-8")
    assert _find_tile_metadata(tmp_path) == root_meta


def test_find_tile_metadata_falls_back_to_tiles_subdir(tmp_path: Path):
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir()
    nested = tiles_dir / "tile_metadata.json"
    nested.write_text("{}", encoding="utf-8")
    assert _find_tile_metadata(tmp_path) == nested


def test_count_tiles_from_metadata_dict_keys(tmp_path: Path):
    meta = tmp_path / "tile_metadata.json"
    meta.write_text('{"tile_0_0": {"a": 1}, "tile_0_1": {"b": 2}, "_meta": {"c": 3}}', encoding="utf-8")
    assert _count_tiles(meta, None) == 2  # "_meta" excluded (starts with underscore)


def test_count_tiles_falls_back_to_glob_when_no_metadata(tmp_path: Path):
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir()
    (tiles_dir / "tile_0_0.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")
    (tiles_dir / "tile_0_1.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")
    assert _count_tiles(None, tiles_dir) == 2


def test_count_tiles_none_found_returns_none(tmp_path: Path):
    assert _count_tiles(None, None) is None


def test_count_roads_and_junctions_parses_xodr(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "road", id="1")
    ET.SubElement(root, "road", id="2")
    junction = ET.SubElement(root, "junction", id="j1")
    ET.ElementTree(root).write(str(xodr))
    assert _count_roads_and_junctions(xodr) == (2, 1)


def test_count_roads_and_junctions_missing_file_returns_none_none(tmp_path: Path):
    assert _count_roads_and_junctions(tmp_path / "nope.xodr") == (None, None)


def test_count_roads_and_junctions_none_path_returns_none_none():
    assert _count_roads_and_junctions(None) == (None, None)


def test_safe_sha256_missing_path_returns_empty_string(tmp_path: Path):
    assert _safe_sha256(None) == ""
    assert _safe_sha256(tmp_path / "nope.bin") == ""


def test_safe_sha256_existing_file_returns_real_digest(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"content")
    import hashlib
    assert _safe_sha256(p) == hashlib.sha256(b"content").hexdigest()
