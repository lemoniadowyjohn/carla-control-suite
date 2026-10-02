"""
RQ5 negative-control battery test (protocol v2 section 17).

This is the executable form of ``RQ5_NEGATIVE_CONTROLS.json``: it runs the
battery and asserts that *every* control was rejected. A control that stops
rejecting its defect is a regression in the authority, not a flaky test.

All fixtures are synthetic and carry ``claim_scope = TEST_FIXTURE_ONLY``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.rq5_negative_controls import (  # noqa: E402
    CONTROL_NAMES,
    NEGATIVE_CONTROLS_SCHEMA,
    run_all_controls,
)


@pytest.fixture(scope="module")
def battery(tmp_path_factory) -> dict:
    return run_all_controls(tmp_path_factory.mktemp("rq5_negative_controls"))


def test_every_required_negative_control_is_executed(battery):
    assert battery["controls_missing"] == []
    assert battery["unexpected_controls"] == []
    assert sorted(battery["controls_executed"]) == sorted(CONTROL_NAMES)
    assert battery["total"] == len(CONTROL_NAMES)


def test_every_negative_control_rejects_its_defect(battery):
    missed = [row for row in battery["rows"] if not row["rejected"]]
    assert missed == [], "these negative controls stopped rejecting their defect: " + ", ".join(
        f"{row['control']} ({row['detail']})" for row in missed
    )
    assert battery["status"] == "PASS"
    assert battery["rejected"] == len(CONTROL_NAMES)


def test_battery_is_not_presented_as_rq5_evidence(battery):
    assert battery["is_rq5_evidence"] is False
    assert battery["claim_scope"] == "TEST_FIXTURE_ONLY"
    assert "not RQ5 evidence" in battery["claim_boundary"]


def test_battery_payload_is_self_describing_and_hashed(battery):
    assert battery["schema"] == NEGATIVE_CONTROLS_SCHEMA
    assert battery["protocol_sha256"]
    assert battery["report_sha256"]
    for row in battery["rows"]:
        assert row["expected"] == "REJECTED"
        assert row["status"] in ("PASS", "MISS")
        assert row["detail"]


def test_control_names_cover_the_frozen_requirement_list():
    """The battery must not silently shrink."""
    assert CONTROL_NAMES == (
        "missing_explicit_dataset_research_strict",
        "fallback_to_latest_dataset",
        "partial_dataset_identity",
        "copied_duplicate_across_train_test",
        "adjacent_group_leakage",
        "manual_frame_in_train",
        "manual_frame_in_validation",
        "manual_class_statistics_in_class_weights",
        "missing_seed",
        "wrong_checkpoint_sha256",
        "wrong_dataset_sha256",
        "nan_training_loss",
        "single_class_collapsed_model",
        "checkpoint_missing_parameters",
    )