# -*- coding: utf-8 -*-
"""Dataset promotion contract (sections 22/25/26), grid session contract
(NEW-258/259) and run-scoped capture namespaces (NEW-263).

Pinned invariants:

* No single boolean may promote a dataset -- every gate in ``gate_order``
  must PASS or the status is ``NOT_READY``.
* Existing data may be reused only when its immutable receipt matches the
  current request; old provenance is never rewritten to match.
* One governed capture per CARLA session, on success AND on failure.
* A fresh capture gets a new empty namespace and nothing is ever deleted.
"""
from __future__ import annotations

import json

import pytest

from ultimate_pipeline.perception.capture_namespace import (
    RunScopedFileTracker,
    allocate_capture_namespace,
    directory_contains_sensor_data,
    existing_sensor_file_count,
    run_id,
)
from ultimate_pipeline.perception.dataset_acceptance import (
    ACCEPTANCE_FILENAME,
    GATE_ORDER,
    NOT_READY,
    REUSE_AUTHORISED,
    TRAINING_DATASET_READY,
    authorise_reuse,
    build_reuse_receipt,
    compare_reuse_receipt,
    evaluate_acceptance,
    evaluate_label_quality,
    load_acceptance,
    write_acceptance,
    assert_dataset_ready,
)
from ultimate_pipeline.perception.session_contract import (
    SESSION_RESTART_REQUIRED,
    CaptureSessionContract,
    load_contract,
    session_blocks_next_capture,
)


def _all_pass(**overrides):
    gates = {name: "PASS" for name in GATE_ORDER}
    gates.update(overrides)
    return gates


# =========================================================================== #
# dataset acceptance (section 22 + 25)
# =========================================================================== #


def test_all_gates_passing_promotes_the_dataset():
    payload = evaluate_acceptance(_all_pass(), dataset_root="/data/run_001")
    assert payload["status"] == TRAINING_DATASET_READY
    assert payload["training_dataset_ready"] is True
    assert payload["failed_gates"] == []
    assert payload["not_run_gates"] == []
    assert payload["single_boolean_promotion_forbidden"] is True
    assert_dataset_ready(payload)  # must not raise


def test_a_single_failing_gate_blocks_promotion():
    payload = evaluate_acceptance(_all_pass(writer_integrity="FAIL"))
    assert payload["status"] == NOT_READY
    assert payload["training_dataset_ready"] is False
    assert payload["failed_gates"] == ["writer_integrity"]
    with pytest.raises(RuntimeError, match="dataset_not_promotable"):
        assert_dataset_ready(payload)


def test_an_unrun_gate_blocks_promotion():
    """Omitting a gate must never be treated as passing it."""
    gates = _all_pass()
    del gates["semantic_label_quality"]
    payload = evaluate_acceptance(gates)
    assert payload["status"] == NOT_READY
    assert payload["not_run_gates"] == ["semantic_label_quality"]


def test_every_required_gate_is_always_present_in_order():
    payload = evaluate_acceptance({})
    assert payload["gate_order"] == list(GATE_ORDER)
    assert [g["gate"] for g in payload["gates"]] == list(GATE_ORDER)
    assert payload["status"] == NOT_READY
    assert len(payload["not_run_gates"]) == len(GATE_ORDER)


def test_blocked_gate_alone_does_not_promote():
    payload = evaluate_acceptance(_all_pass(route_contract="BLOCKED"))
    assert payload["status"] == NOT_READY
    assert payload["blocked_gates"] == ["route_contract"]


def test_gate_sources_are_normalised():
    payload = evaluate_acceptance(
        _all_pass(
            map_identity=True,                       # bool
            runtime_stability={"status": "PASS"},    # mapping
            sensor_canary="PASS",                    # string
        )
    )
    assert payload["status"] == TRAINING_DATASET_READY
    by_name = {g["gate"]: g for g in payload["gates"]}
    assert by_name["map_identity"]["detail"]["bool_source"] is True
    assert by_name["runtime_stability"]["status"] == "PASS"


def test_unknown_gate_is_recorded_rather_than_dropped():
    payload = evaluate_acceptance({**_all_pass(), "made_up_gate": "PASS"})
    assert "made_up_gate" in [g["gate"] for g in payload["gates"]]

    with_extra = evaluate_acceptance(_all_pass(), extra={"novel": "detail"})
    assert with_extra["extra"] == {"novel": "detail"}


def test_authority_note_names_run_perception_safe():
    payload = evaluate_acceptance(_all_pass())
    assert "run_perception_safe" in payload["authority_note"]
    assert "every gate in gate_order must PASS" in payload["authority_note"]


def test_write_and_load_acceptance_roundtrip(tmp_path):
    payload = evaluate_acceptance(_all_pass(), dataset_root="/data/run_001")
    written = write_acceptance(payload, tmp_path)
    assert written.name == ACCEPTANCE_FILENAME
    assert not list(tmp_path.glob("*.tmp"))
    loaded = load_acceptance(tmp_path)
    assert loaded["status"] == TRAINING_DATASET_READY
    assert loaded["acceptance_digest"] == payload["acceptance_digest"]
    assert load_acceptance(tmp_path / "empty") is None


def test_assert_dataset_ready_rejects_missing_payload():
    with pytest.raises(RuntimeError, match="dataset_not_promotable"):
        assert_dataset_ready({})
    with pytest.raises(RuntimeError, match="dataset_not_promotable"):
        assert_dataset_ready(None)


# =========================================================================== #
# label quality (section 26)
# =========================================================================== #


def test_label_quality_separates_measurements_from_policy():
    report = evaluate_label_quality([0, 1, 1, 2, 255])
    assert report["measurements"]["n"] == 5
    assert report["measurements"]["labelled_pixels"] == 4
    assert report["policy_verdict"]["status"] == "PASS"
    assert report["policy_verdict"]["reject"] is False
    assert "raw measurements" in report["note"]
    assert "reported separately" in report["note"]


def test_all_unlabeled_pixels_fail_the_policy_verdict():
    report = evaluate_label_quality([255, 255, 255])
    assert "all_pixels_unlabeled" in report["policy_verdict"]["reasons"]
    assert report["policy_verdict"]["reject"] is True
    assert report["policy_verdict"]["status"] == "FAIL"


def test_rare_valid_scene_is_reported_but_not_auto_rejected():
    """A mostly-one-class frame is measured, not silently thrown away."""
    report = evaluate_label_quality([3] * 99 + [4])
    assert report["policy_verdict"]["reject"] is False
    assert report["policy_verdict"]["status"] == "PASS"
    assert any(
        r.startswith("dominant_class_fraction") for r in report["policy_verdict"]["reasons"]
    )
    assert report["measurements"]["dominant_class_fraction"] == pytest.approx(0.99)


def test_empty_label_input_is_reported_not_crashed():
    report = evaluate_label_quality([])
    assert report["measurements"]["n"] == 0
    assert "no_pixels" in report["policy_verdict"]["reasons"]


# =========================================================================== #
# immutable reuse receipt (NEW-225)
# =========================================================================== #


def test_reuse_receipt_digest_covers_every_identity_field():
    receipt = build_reuse_receipt(
        map_or_xodr_sha256="a" * 8,
        route_sha256="b" * 8,
        calibration_sha256="c" * 8,
    )
    assert receipt["schema"] == "IMMUTABLE_CAPTURE_RECEIPT/v1"
    assert receipt["receipt_digest"]
    # Fields not supplied are present as None, not omitted.
    assert receipt["dataset_sha256"] is None
    assert "built_utc" in receipt


def test_matching_receipt_authorises_reuse():
    receipt = build_reuse_receipt(map_or_xodr_sha256="a" * 8, route_sha256="b" * 8)
    outcome = authorise_reuse(stored_receipt=receipt, current_request=receipt)
    assert outcome["status"] == REUSE_AUTHORISED
    assert outcome["comparison"]["match"] is True


def test_receipt_mismatch_refuses_reuse_instead_of_rewriting_provenance():
    stored = build_reuse_receipt(map_or_xodr_sha256="a" * 8, route_sha256="b" * 8)
    current = build_reuse_receipt(map_or_xodr_sha256="z" * 8, route_sha256="b" * 8)
    stored_before = json.loads(json.dumps(stored))

    outcome = authorise_reuse(stored_receipt=stored, current_request=current)
    assert outcome["status"] == NOT_READY
    assert "receipt_mismatch" in outcome["reason"]
    assert "map_or_xodr_sha256" in outcome["reason"]
    # The stored receipt must be untouched: old provenance is never rewritten.
    assert stored == stored_before
    assert "Never rewrite old provenance" in outcome["comparison"]["policy"]


def test_missing_receipt_refuses_reuse():
    outcome = authorise_reuse(stored_receipt=None, current_request=build_reuse_receipt())
    assert outcome["status"] == NOT_READY
    assert outcome["reason"] == "no_immutable_receipt_present"
    assert outcome["comparison"] is None


def test_receipt_digest_difference_is_a_mismatch():
    stored = build_reuse_receipt(route_sha256="b" * 8)
    current = dict(stored, receipt_digest="deadbeef")
    comparison = compare_reuse_receipt(stored, current)
    assert comparison["match"] is False
    assert "receipt_digest" in comparison["mismatched_fields"]


# =========================================================================== #
# session contract (NEW-258 / NEW-259)
# =========================================================================== #


def test_fresh_session_may_serve_a_governed_capture():
    contract = CaptureSessionContract(map_name="Grid0828", auto_restart_allowed=False)
    assert contract.may_serve_governed_capture() is True
    assert contract.needs_restart is False
    contract.assert_may_capture()  # must not raise


def test_consumed_session_refuses_a_second_governed_capture():
    contract = CaptureSessionContract(map_name="Grid0828", auto_restart_allowed=False)
    contract.mark_consumed()
    assert contract.may_serve_governed_capture() is False
    assert contract.needs_restart is True
    assert contract.status == SESSION_RESTART_REQUIRED
    with pytest.raises(RuntimeError, match=SESSION_RESTART_REQUIRED):
        contract.assert_may_capture()


def test_consumed_session_without_auto_restart_requires_a_marker(tmp_path):
    contract = CaptureSessionContract(
        map_name="Grid0828", auto_restart_allowed=False, state_dir=tmp_path
    )
    contract.mark_consumed()
    marker = contract.restart_required_marker(tmp_path)
    assert marker.exists()
    assert "one_governed_capture_per_carla_session" in marker.read_text(encoding="utf-8")
    assert session_blocks_next_capture(tmp_path) is True


def test_auto_restart_allowed_keeps_the_session_active_but_consumed(tmp_path):
    contract = CaptureSessionContract(
        map_name="Grid0828", auto_restart_allowed=True, state_dir=tmp_path
    )
    contract.mark_consumed()
    assert contract.payload()["status"] == "SESSION_ACTIVE"
    assert contract.payload()["consumed"] is True
    assert contract.may_serve_governed_capture() is False
    assert session_blocks_next_capture(tmp_path) is False


def test_a_failed_unstable_map_capture_also_consumes_the_session():
    contract = CaptureSessionContract(map_name="Grid0821", auto_restart_allowed=False)
    contract.mark_failed(reason="engine_died")
    assert contract.consumed is True
    assert "failure:engine_died" in (contract.consumed_reason or "")
    assert contract.needs_restart is True


def test_a_failed_stable_map_capture_does_not_consume_the_session():
    contract = CaptureSessionContract(map_name="Town10HD", auto_restart_allowed=False)
    contract.mark_failed(reason="transient")
    assert contract.consumed is False
    assert contract.may_serve_governed_capture() is True


def test_session_contract_persists_and_reloads(tmp_path):
    contract = CaptureSessionContract(
        map_name="Grid0828", auto_restart_allowed=False, state_dir=tmp_path
    )
    contract.mark_consumed()
    path = contract.write()
    assert path is not None and path.exists()
    assert not list(tmp_path.glob("*.tmp"))

    reloaded = load_contract(tmp_path)
    assert reloaded["consumed"] is True
    assert reloaded["one_capture_per_session_policy"] is True
    assert session_blocks_next_capture(tmp_path) is True


def test_session_payload_records_map_and_pid():
    contract = CaptureSessionContract(
        map_name="Grid0828", carla_pid=4242, auto_restart_allowed=False
    )
    payload = contract.payload()
    assert payload["known_unstable_map"] is True
    assert payload["carla_pid"] == 4242
    assert payload["history"][0]["event"] == "CREATED"


def test_stable_map_is_not_flagged_unstable():
    contract = CaptureSessionContract(map_name="/Game/Maps/Town10HD")
    assert contract.payload()["known_unstable_map"] is False


# =========================================================================== #
# capture namespace (NEW-263)
# =========================================================================== #


def test_empty_directory_is_used_directly(tmp_path):
    target = tmp_path / "recording"
    result = allocate_capture_namespace(target, run_tag="run_a")
    assert result["mode"] == "FRESH_EMPTY"
    assert result["directory"] == str(target)
    assert result["created"] is True
    assert target.is_dir()


def test_directory_with_sensor_data_is_refused_and_never_deleted(tmp_path):
    target = tmp_path / "recording"
    (target / "rgb").mkdir(parents=True)
    (target / "rgb" / "00000001.png").write_bytes(b"prior evidence")

    result = allocate_capture_namespace(target, run_tag="run_b")

    assert result["mode"] == "FRESH_ALLOCATED_AVOIDING_EXISTING_DATA"
    assert result["refused"] is True
    assert result["deletion_performed"] is False
    assert result["directory"] != str(target)
    # The previous run's evidence is still there.
    assert (target / "rgb" / "00000001.png").read_bytes() == b"prior evidence"
    assert result["existing_sensor_files_in_refused_dir"] == 1


def test_reuse_is_only_authorised_with_a_matching_receipt(tmp_path):
    target = tmp_path / "recording"
    (target / "rgb").mkdir(parents=True)
    (target / "rgb" / "00000001.png").write_bytes(b"x")

    receipt = {"receipt_digest": "abc", "map_or_xodr_sha256": "a" * 8}
    authorised = allocate_capture_namespace(
        target, force_fresh=False, allow_reuse=True, reuse_receipt=receipt, run_tag="r"
    )
    assert authorised["mode"] == "REUSE_AUTHORISED"
    assert authorised["directory"] == str(target)
    assert authorised["created"] is False

    # Reuse requested but no receipt -> refuse and allocate a fresh namespace.
    unauthorised = allocate_capture_namespace(
        target, force_fresh=False, allow_reuse=True, run_tag="r2"
    )
    assert unauthorised["refused"] is True
    assert unauthorised["directory"] != str(target)


def test_force_fresh_wins_over_a_reuse_receipt(tmp_path):
    target = tmp_path / "recording"
    (target / "rgb").mkdir(parents=True)
    (target / "rgb" / "00000001.png").write_bytes(b"x")

    result = allocate_capture_namespace(
        target, force_fresh=True, allow_reuse=True, reuse_receipt={"receipt_digest": "a"}
    )
    assert result["mode"] == "FRESH_ALLOCATED_AVOIDING_EXISTING_DATA"


def test_run_ids_are_unique_and_timestamped():
    ids = {run_id() for _ in range(20)}
    assert len(ids) == 20
    assert all("_" in i and len(i) > 20 for i in ids)


def test_run_scoped_tracker_counts_only_this_runs_files():
    tracker = RunScopedFileTracker(run_id_value="r1", namespace="/ns")
    tracker.record("rgb_front", "/ns/rgb/00000001.png")
    tracker.record("rgb_front", "/ns/rgb/00000002.png")
    tracker.record("rgb_front", "/ns/rgb/00000001.png")  # duplicate write
    tracker.record("lidar", "/ns/lidar/00000001.npz")

    assert tracker.count("rgb_front") == 2  # never 3
    assert tracker.counts() == {"lidar": 1, "rgb_front": 2}

    payload = tracker.payload()
    assert payload["run_id"] == "r1"
    assert "pre-existing files are never counted" in payload["policy"]


def test_sensor_data_detection_and_counting(tmp_path):
    (tmp_path / "rgb").mkdir()
    (tmp_path / "rgb" / "00000001.png").write_bytes(b"x")
    (tmp_path / "rgb" / "notes.txt").write_bytes(b"x")

    assert directory_contains_sensor_data(tmp_path) is True
    assert existing_sensor_file_count(tmp_path) == 1
    assert directory_contains_sensor_data(tmp_path / "nothing_here") is False
    assert existing_sensor_file_count(tmp_path / "nothing_here") == 0
