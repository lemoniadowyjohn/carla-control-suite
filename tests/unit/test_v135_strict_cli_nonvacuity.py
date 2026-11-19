"""F19 strict RQ3 CLI non-vacuity (test-only).

Proves the strict CLI cannot fabricate a completed capture or runtime receipt
without a wired real executor: it must fail closed as NOT_RUN/authoritative=false
and must not emit capture receipts or success verdicts.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ultimate_pipeline.perception.record_route_fixed import (
    STRICT_EXIT_SETUP_FAILURE,
    _main_impl_strict,
)


def _status_files(out_dir: Path) -> list[Path]:
    return sorted(out_dir.rglob("STRICT_RQ3_EXECUTION_STATUS.json"))


def test_strict_cli_fails_closed_without_executor(tmp_path):
    out_dir = tmp_path / "rq3_strict_output"
    args = SimpleNamespace(
        out_dir=str(out_dir),
        execution_mode="LIVE_CAPTURE",
        route_manifest_path="/tmp/fake_route_manifest.json",
        route_manifest_sha256="a" * 64,
    )
    rc = _main_impl_strict(args)
    assert rc == STRICT_EXIT_SETUP_FAILURE == 4

    statuses = _status_files(out_dir)
    assert len(statuses) == 1
    status = json.loads(statuses[0].read_text(encoding="utf-8"))

    assert status["schema"] == "STRICT_RQ3_EXECUTION_STATUS/v1"
    assert status["status"] == "NOT_RUN"
    assert status["completion_status"] == "NOT_RUN"
    assert status["terminal_status"] == "NOT_RUN"
    assert status["authoritative"] is False
    assert status["failure_reason"] == "STRICT_CLI_RUNTIME_EXECUTOR_UNAVAILABLE"
    assert status["execution_mode"] == "LIVE_CAPTURE"
    assert status["route_manifest_path"] == "/tmp/fake_route_manifest.json"
    assert status["route_manifest_sha256"] == "a" * 64
    assert status["dataset_content_sha256"] is None
    assert status["capture_completion_receipt_sha256"] is None
    assert status["attempt_id"]

    # No capture receipt or success verdict artifacts may be fabricated.
    all_files = [p.name for p in out_dir.rglob("*") if p.is_file()]
    forbidden_tokens = ("CAPTURE_COMPLETION_RECEIPT", "SUCCESS", "RQ3_VERDICT", "PAIR_VERDICT")
    for name in all_files:
        upper = name.upper()
        assert not any(tok in upper for tok in forbidden_tokens), name
    # Exactly the NOT_RUN status file was produced.
    assert all_files == ["STRICT_RQ3_EXECUTION_STATUS.json"] or len(all_files) == 1


def test_strict_cli_creates_unique_attempt_dir_and_never_claims_pass(tmp_path):
    out_dir = tmp_path / "out"
    args = SimpleNamespace(out_dir=str(out_dir), execution_mode="UNSPECIFIED")
    rc = _main_impl_strict(args)
    assert rc != 0
    statuses = _status_files(out_dir)
    assert len(statuses) == 1
    status = json.loads(statuses[0].read_text(encoding="utf-8"))
    attempt_dir = out_dir / "strict_attempts" / status["attempt_id"]
    assert statuses[0] == attempt_dir / "STRICT_RQ3_EXECUTION_STATUS.json"
    # Authoritative/capture claims must remain absent.
    assert status["authoritative"] is False
    assert status.get("capture_completion_receipt_sha256") is None
    assert status.get("dataset_content_sha256") is None
