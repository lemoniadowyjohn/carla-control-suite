"""V104 Scope 2 — independent adversarial tests for the GUI release authority.

These are **independent reproducing tests in a separately owned file**.  They
do not modify any Codex-owned module: they exercise the GUI verdict reader
and the run-certification path as they exist today, and assert the security
properties a release authority must have.

The properties under test (from the V104 brief):

* a missing verdict can never produce a certified success;
* a malformed verdict can never produce a certified success;
* a **stale** verdict (one belonging to a previous run) can never produce a
  certified success;
* an **unbound** PASS verdict (a bare ``{"status": "PASS"}`` with no
  release identity) can never produce a certified success;
* a **contradictory** verdict can never produce a certified success;
* a zero-exit subprocess plus a forged ``SUCCESS.txt`` can never produce a
  certified success;
* live-mode unavailability and cancellation are never certified.

A test that fails documents a real defect; a test that passes documents a
property that already holds.  Nothing here is weakened to make the suite
green.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ultimate_pipeline.gui.jobs.governance import (
    AUTHORITATIVE_ONLY,
    FINAL_VERDICT_NAME,
    SUCCESS_MARKER,
    RunVerdict,
    read_final_verdict,
)


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return run_dir


def _write_verdict(run_dir: Path, payload) -> None:
    (run_dir / FINAL_VERDICT_NAME).write_text(
        json.dumps(payload) if not isinstance(payload, str) else payload,
        encoding="utf-8",
    )


def _write_success_marker(run_dir: Path, body: str = "OK 2026-01-01T00:00:00Z\n") -> None:
    (run_dir / SUCCESS_MARKER).write_text(body, encoding="utf-8")


def _is_certified_success(verdict: RunVerdict) -> bool:
    """Would a release authority treat this verdict as a certified success?"""
    return verdict.status == "PASS"


# ---------------------------------------------------------------------------
# 1. missing verdict
# ---------------------------------------------------------------------------

def test_missing_verdict_is_never_a_success(tmp_path):
    run_dir = _run_dir(tmp_path)
    verdict = read_final_verdict(run_dir)

    assert verdict.present is False
    assert verdict.status != "PASS"
    assert not _is_certified_success(verdict)
    assert FINAL_VERDICT_NAME in verdict.detail


# ---------------------------------------------------------------------------
# 2. malformed verdict
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        "",
        "[]",
        '{"no_status_field": true}',
        "null",
    ],
)
def test_malformed_verdict_is_never_a_success(tmp_path, payload):
    run_dir = _run_dir(tmp_path)
    (run_dir / FINAL_VERDICT_NAME).write_text(payload, encoding="utf-8")

    verdict = read_final_verdict(run_dir)

    assert verdict.status != "PASS"
    assert not _is_certified_success(verdict)


# ---------------------------------------------------------------------------
# 3. forged SUCCESS.txt with no verdict
# ---------------------------------------------------------------------------

def test_forged_success_marker_without_a_verdict_is_not_a_success(tmp_path):
    """``SUCCESS.txt`` alone is never certification evidence."""
    run_dir = _run_dir(tmp_path)
    _write_success_marker(run_dir)

    verdict = read_final_verdict(run_dir)

    assert verdict.status != "PASS"
    assert verdict.present is False
    assert "never" in AUTHORITATIVE_ONLY.lower() or "not authoritative" in AUTHORITATIVE_ONLY.lower()


def test_forged_success_marker_with_a_malformed_verdict_is_not_a_success(tmp_path):
    run_dir = _run_dir(tmp_path)
    _write_success_marker(run_dir)
    (run_dir / FINAL_VERDICT_NAME).write_text("{oops", encoding="utf-8")

    verdict = read_final_verdict(run_dir)

    assert verdict.status != "PASS"


# ---------------------------------------------------------------------------
# 4. zero-exit subprocess + forged SUCCESS.txt
# ---------------------------------------------------------------------------

def test_zero_exit_subprocess_plus_forged_success_marker_is_not_a_success(tmp_path):
    """A subprocess exit code of 0 plus a forged marker is still not a pass."""
    import subprocess
    import sys

    run_dir = _run_dir(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-c", "print('done')"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0
    _write_success_marker(run_dir)

    verdict = read_final_verdict(run_dir)

    assert verdict.status != "PASS"
    assert not _is_certified_success(verdict)


# ---------------------------------------------------------------------------
# 5. unbound PASS verdict
# ---------------------------------------------------------------------------

def test_unbound_pass_verdict_is_not_a_success(tmp_path):
    """A bare ``{"status": "PASS"}`` carries no release identity.

    A release authority must not certify a PASS that is not bound to a run
    identity, an artifact digest and an acceptance receipt.
    """
    run_dir = _run_dir(tmp_path)
    _write_verdict(run_dir, {"status": "PASS"})

    verdict = read_final_verdict(run_dir)

    # The reader currently normalises this to PASS.  It must not: an
    # unbound PASS has no evidence that it describes THIS run.
    assert not _is_certified_success(verdict), (
        "a PASS verdict with no release identity was accepted as authoritative"
    )


def test_unbound_pass_verdict_with_a_forged_success_marker_is_not_a_success(tmp_path):
    run_dir = _run_dir(tmp_path)
    _write_verdict(run_dir, {"status": "PASS"})
    _write_success_marker(run_dir)

    verdict = read_final_verdict(run_dir)

    assert not _is_certified_success(verdict)


# ---------------------------------------------------------------------------
# 6. stale verdict
# ---------------------------------------------------------------------------

def test_stale_verdict_from_a_previous_run_is_not_a_success(tmp_path):
    """A verdict written by an earlier run must not certify a later one."""
    run_dir = _run_dir(tmp_path)
    # A verdict carrying the identity of a DIFFERENT run.
    _write_verdict(
        run_dir,
        {
            "status": "PASS",
            "run_uuid": "11111111-1111-1111-1111-111111111111",
            "generated_at_utc": "2020-01-01T00:00:00+00:00",
        },
    )

    verdict = read_final_verdict(run_dir)

    assert not _is_certified_success(verdict), (
        "a stale verdict (different run identity / ancient timestamp) was "
        "accepted as authoritative"
    )


# ---------------------------------------------------------------------------
# 7. contradictory verdict
# ---------------------------------------------------------------------------

def test_contradictory_verdict_is_not_a_success(tmp_path):
    """``status: PASS`` alongside contradicting evidence must not certify."""
    run_dir = _run_dir(tmp_path)
    _write_verdict(
        run_dir,
        {
            "status": "PASS",
            "blocking_failures": [{"signal_id": "X", "error": "boom"}],
            "evidence_persistence_failures": [{"signal_id": "Y", "error": "boom"}],
            "advisories": [],
            "run_status_ok": False,
        },
    )

    verdict = read_final_verdict(run_dir)

    assert not _is_certified_success(verdict), (
        "a PASS verdict with blocking failures was accepted as authoritative"
    )


def test_pass_with_a_missing_acceptance_receipt_is_not_a_success(tmp_path):
    run_dir = _run_dir(tmp_path)
    _write_verdict(run_dir, {"status": "PASS", "acceptance_receipt": None})

    verdict = read_final_verdict(run_dir)

    assert not _is_certified_success(verdict)


# ---------------------------------------------------------------------------
# 8. wrong artifact digest
# ---------------------------------------------------------------------------

def test_verdict_with_a_mismatched_artifact_digest_is_not_a_success(tmp_path):
    run_dir = _run_dir(tmp_path)
    (run_dir / "final.xodr").write_bytes(b"<OpenDRIVE/>")
    _write_verdict(
        run_dir,
        {
            "status": "PASS",
            "final_artifact_sha256": "0" * 64,
        },
    )

    verdict = read_final_verdict(run_dir)

    assert not _is_certified_success(verdict), (
        "a PASS verdict whose declared artifact digest does not match the "
        "artifact on disk was accepted as authoritative"
    )
