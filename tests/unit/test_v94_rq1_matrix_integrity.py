"""RQ1 matrix identity gap regression: compare measured child keys, not None."""
from __future__ import annotations

from copy import deepcopy

from research.rq1_determinism_matrix import build_determinism_matrix

SHA_INPUT = "a" * 64
SHA_RAW = "b" * 64
SHA_NORM = "c" * 64
SHA_STRUCT = "d" * 64


def _run(index):
    return {
        "run_index": index,
        "run_id": f"cold_{index:02d}",
        "return_code": 0,
        "timed_out": False,
        "child_receipt": {
            "schema": "rq1_run_receipt/v2",
            "status": "ok",
            "input_xodr": "source/auto.xodr",
            "input_sha256": SHA_INPUT,
            "xodr_sha256": SHA_RAW,
            "normalized_xodr_sha256": SHA_NORM,
            "structural_signature": SHA_STRUCT,
            "tileset_digest": "e" * 64,
            "map_acceptance_digest": "f" * 64,
            "final_receipt_digest": "1" * 64,
            "settings_digest": "2" * 64,
            "inputs_record": {
                "OSM": {"sha256": "3"*64},
                "BUILDINGS": {"sha256": "4"*64},
            },
            "effective_env": {"governed": {"UP_OFFLINE_ONLY": "1"}},
        },
    }


def test_identical_five_children_do_not_generate_spurious_null_gaps():
    runs = [_run(i) for i in range(5)]
    result = build_determinism_matrix(runs, valid_run_count=5)
    assert result["valid_run_count"] == 5
    assert result["divergence_classification"] == "NO_DIFFERENCE"
    assert result["identity_gaps"] == []
    assert result["all_raw_equal"]
    assert result["all_normalized_equal"]
    assert result["all_structural_equal"]


def test_changed_tile_or_environment_identity_produces_real_gap():
    runs = [_run(i) for i in range(5)]
    runs[4]["child_receipt"]["tileset_digest"] = "9" * 64
    runs[3]["child_receipt"]["effective_env"]["governed"]["UP_OFFLINE_ONLY"] = "0"
    result = build_determinism_matrix(runs, valid_run_count=5)
    names = {g["identity"] for g in result["identity_gaps"]}
    assert names == {"tileset_digest", "input_identity"}
    assert all(g["distinct_count"] == 2 for g in result["identity_gaps"])


def test_changed_raw_artifact_is_not_suppressed_by_equal_normalized_sha():
    runs = [_run(i) for i in range(5)]
    runs[4]["child_receipt"]["xodr_sha256"] = "9" * 64
    result = build_determinism_matrix(runs, valid_run_count=5)
    assert not result["all_raw_equal"]
    assert result["all_normalized_equal"]
    assert result["all_structural_equal"]
    assert result["divergence_classification"] == "RAW_DIFFERENT_NORMALIZED_EQUAL"
    assert "raw_xodr_sha256" in {g["identity"] for g in result["identity_gaps"]}
