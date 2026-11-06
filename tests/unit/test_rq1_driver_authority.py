from __future__ import annotations

from pathlib import Path

import pytest


def test_non_frozen_run_count_is_pilot_and_never_success():
    from tools.rq1b_five_run_driver import (
        PILOT_EXIT_CODE,
        RQ1_REQUIRED_VALID_RUNS,
        campaign_exit_code,
    )

    assert campaign_exit_code(requested_runs=1, valid_run_count=1, matrix={}) == PILOT_EXIT_CODE
    assert campaign_exit_code(requested_runs=2, valid_run_count=2, matrix={}) == PILOT_EXIT_CODE
    assert campaign_exit_code(requested_runs=4, valid_run_count=4, matrix={}) == PILOT_EXIT_CODE


def test_only_complete_bound_five_run_matrix_can_return_success():
    from tools.rq1b_five_run_driver import RQ1_REQUIRED_VALID_RUNS, campaign_exit_code

    matrix = {
        "schema": "rq1_full_determinism_matrix/v2",
        "valid_run_count": RQ1_REQUIRED_VALID_RUNS,
        "all_raw_equal": True,
        "all_normalized_equal": True,
        "all_structural_equal": True,
        "divergence_classification": "NO_DIFFERENCE",
        "per_run": [
            {"run": index, "run_id": f"run-{index}", "valid": True}
            for index in range(RQ1_REQUIRED_VALID_RUNS)
        ],
    }
    assert (
        campaign_exit_code(
            requested_runs=RQ1_REQUIRED_VALID_RUNS,
            valid_run_count=RQ1_REQUIRED_VALID_RUNS,
            matrix=matrix,
        )
        == 0
    )
    matrix["per_run"].pop()
    assert (
        campaign_exit_code(
            requested_runs=RQ1_REQUIRED_VALID_RUNS,
            valid_run_count=RQ1_REQUIRED_VALID_RUNS,
            matrix=matrix,
        )
        != 0
    )


def test_driver_main_non_frozen_run_count_does_not_start_or_create_output(tmp_path, monkeypatch):
    from tools import rq1b_five_run_driver as driver

    output = tmp_path / "pilot-output"
    monkeypatch.setattr(
        "sys.argv",
        ["rq1b_five_run_driver.py", "--runs", "1", "--output-base", str(output)],
    )
    assert driver.main() == driver.PILOT_EXIT_CODE
    assert not output.exists()


def test_existing_run_directory_and_stale_child_binding_are_refused(tmp_path: Path):
    from tools.rq1b_five_run_driver import ensure_fresh_campaign_root, validate_child_binding

    run_root = tmp_path / "campaign"
    (run_root / "run_02").mkdir(parents=True)
    (run_root / "run_02" / "old.json").write_text("stale", encoding="utf-8")
    with pytest.raises(RuntimeError, match="non-empty run directory"):
        ensure_fresh_campaign_root(run_root)

    child = {
        "schema": "rq1_run_receipt/v2",
        "status": "ok",
        "run": 1,
        "input_sha256": "a" * 64,
        "git_sha": "b" * 40,
        "out_dir": str(tmp_path / "run_01" / "rq1b_full"),
        "output_path": str(tmp_path / "run_01" / "rq1b_full"),
        "xodr_sha256": "c" * 64,
    }
    problem = validate_child_binding(
        child,
        run_idx=2,
        run_dir=tmp_path / "run_02",
        source_sha="b" * 40,
        input_sha="a" * 64,
    )
    assert problem == "child_run_index_mismatch"

    child["run"] = 2
    child["out_dir"] = str(tmp_path / "outside-run")
    child["xodr_sha256"] = "c" * 64
    problem = validate_child_binding(
        child,
        run_idx=2,
        run_dir=tmp_path / "run_02",
        source_sha="b" * 40,
        input_sha="a" * 64,
    )
    assert problem == "child_output_directory_outside_run"


def test_empty_campaign_root_can_be_created_but_nonempty_is_refused(tmp_path: Path):
    from tools.rq1b_five_run_driver import ensure_fresh_campaign_root

    root = tmp_path / "fresh"
    assert ensure_fresh_campaign_root(root) == root
    (root / "run_00").mkdir()
    with pytest.raises(RuntimeError, match="non-empty run directory"):
        ensure_fresh_campaign_root(root)
