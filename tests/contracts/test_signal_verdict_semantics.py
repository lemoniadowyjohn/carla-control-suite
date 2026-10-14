# Verdict / signal-index semantics for the sole run authority (NEW-334/337/343).
#
# ``final_run_verdict.json`` decides whether ``SUCCESS.txt`` may exist, so its
# vocabulary, its blocking rules and its cross-checks are contract, not
# implementation detail.  These tests exercise them directly -- no pipeline,
# no CARLA.
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.signals.index import (  # noqa: E402
    STATUS_BLOCKED_EXTERNAL,
    STATUS_FAIL,
    STATUS_INCOMPLETE,
    STATUS_MISSING,
    STATUS_NOT_APPLICABLE,
    STATUS_PASS,
    STATUS_SKIP,
    build_signal_index,
    normalize_signal_status,
)
from ultimate_pipeline.signals.registry import SIGNAL_REGISTRY  # noqa: E402
from ultimate_pipeline.signals.verdict import (  # noqa: E402
    VERDICT_BLOCKED_EXTERNAL,
    VERDICT_FAIL,
    VERDICT_PASS,
    _blocking_status_for,
    compute_final_run_verdict,
)
from ultimate_pipeline.signals.writer import (  # noqa: E402
    clear_persistence_failures,
    record_persistence_failure,
)

#: Artifacts an always-evaluated signal set needs before a debug-profile run
#: can be healthy.  Written into an otherwise empty directory.
_DEBUG_PASS_ARTIFACTS = {
    "map_acceptance.json": {"schema": "map_acceptance_v1", "valid_for_experiments": True},
    "gate_failures.json": {},
    "pipeline_health_summary.json": {"schema": "pipeline_health_summary/v1", "overall_ok": True},
    "run_summary.json": {"schema": "run_summary/v1", "signals": {}},
    "cumulative_gate_report.json": {"schema": "cumulative_gate_report/v1", "failed": 0, "total": 3},
    "08h5_g6_lane_coverage_repair_report.json": {
        "schema": "08h5_g6_lane_coverage_repair_report/v1",
        "ok": True,
        "status": "PASS",
    },
    "environment_snapshot.json": {"schema": "environment_snapshot/v1"},
    "logs/validation_report_full.json": {"schema": "validation_report_full/v1", "summary": {}},
    "determinism_fingerprint.json": {"schema": "determinism_fingerprint/v1", "final_xodr": "final.xodr"},
    "final_artifact_receipt.json": {
        "schema": "final_artifact_receipt/v1",
        "final_artifact_sha256": "0" * 64,
        "structure_fingerprint": {"sha256": "1" * 64},
    },
}


def _write_debug_fixture(out_dir: Path) -> None:
    for rel, payload in _DEBUG_PASS_ARTIFACTS.items():
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@pytest.fixture()
def clean_env(monkeypatch):
    for name in (
        "UP_RUN_PREFLIGHT",
        "UP_ENABLE_SCENARIORUNNER",
        "UP_ENABLE_RQ1_DETERMINISM",
        "UP_ENABLE_THESIS_PERCEPTION_CAPTURE",
        "UP_ENABLE_DOMAIN_GAP",
        "UP_ENABLE_G6_LANE_COVERAGE_REPAIR",
    ):
        monkeypatch.delenv(name, raising=False)
    clear_persistence_failures()
    yield {}
    clear_persistence_failures()


def _verdict(out_dir: Path, profile: str, env, *, final_xodr: str | None = None):
    return compute_final_run_verdict(
        str(out_dir),
        profile=profile,
        settings=None,
        env=env,
        final_xodr=final_xodr,
    )


# --- blocking rules ---------------------------------------------------------

@pytest.mark.parametrize(
    "signal_id,status,required,expected",
    [
        ("TILE_QA", STATUS_PASS, True, None),
        ("TILE_QA", STATUS_SKIP, True, None),          # skip_policy RECORD_IF_DISABLED
        ("TILE_QA", STATUS_MISSING, True, VERDICT_FAIL),
        ("TILE_QA", STATUS_FAIL, True, VERDICT_FAIL),
        ("TILE_QA", STATUS_BLOCKED_EXTERNAL, True, VERDICT_BLOCKED_EXTERNAL),
        ("TILE_QA", STATUS_BLOCKED_EXTERNAL, False, None),
        ("TILE_QA", STATUS_INCOMPLETE, True, VERDICT_FAIL),
        ("TILE_QA", STATUS_NOT_APPLICABLE, True, None),
        ("CARLA_PREFLIGHT", STATUS_SKIP, True, VERDICT_BLOCKED_EXTERNAL),  # BLOCKED_EXTERNAL_* skip
        ("DOMAIN_GAP", STATUS_MISSING, True, VERDICT_BLOCKED_EXTERNAL),    # BLOCKED_EXTERNAL_IF_* missing
        ("LOCAL_PERCEPTION", STATUS_FAIL, True, None),                     # advisory class
        ("MAP_ACCEPTANCE", STATUS_FAIL, True, VERDICT_FAIL),
        ("MAP_ACCEPTANCE", STATUS_MISSING, False, None),                   # not required for profile
    ],
)
def test_blocking_status_rules(signal_id, status, required, expected):
    assert (
        _blocking_status_for(signal_id, status, enabled=True, required=required)
        == expected
    ), (signal_id, status, required)


def test_disabled_signal_never_blocks():
    assert _blocking_status_for("MAP_ACCEPTANCE", STATUS_MISSING, enabled=False, required=True) is None


# --- normalization vocabulary ----------------------------------------------

@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"status": "PASS"}, STATUS_PASS),
        ({"status": "OK"}, STATUS_PASS),
        ({"status": "FAIL"}, STATUS_FAIL),
        ({"status": "SKIPPED"}, STATUS_SKIP),
        ({"status": "BLOCKED_EXTERNAL"}, STATUS_BLOCKED_EXTERNAL),
        ({"status": "INCOMPLETE"}, STATUS_INCOMPLETE),
        ({"ok": True}, STATUS_PASS),
        ({"ok": False}, STATUS_FAIL),
        ({"schema": "whatever"}, STATUS_INCOMPLETE),   # no verdict field at all
        ({"summary": {"ok": False}}, STATUS_FAIL),     # nested summary
        (None, STATUS_MISSING),
    ],
)
def test_generic_status_normalization(payload, expected):
    # TILE_QA has no signal-specific rule, so this exercises the shared path.
    assert normalize_signal_status("TILE_QA", payload) == expected


def test_unreadable_artifact_is_worse_than_absent():
    assert normalize_signal_status("TILE_QA", None, error="ValueError: boom") == STATUS_FAIL


def test_domain_gap_blocked_status_normalizes_to_blocked_external():
    payload = {"schema": "domain_gap_stage_status/v1", "status": "BLOCKED_EXTERNAL", "ok": False}
    assert normalize_signal_status("DOMAIN_GAP", payload) == STATUS_BLOCKED_EXTERNAL


def test_map_acceptance_without_validity_flag_is_incomplete():
    assert normalize_signal_status("MAP_ACCEPTANCE", {"schema": "map_acceptance_v1"}) == STATUS_INCOMPLETE


# --- verdict against a healthy and a mutated run ----------------------------

def test_debug_profile_with_complete_evidence_passes(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    verdict = _verdict(tmp_path, "debug", clean_env)
    assert verdict["status"] == VERDICT_PASS, json.dumps(verdict["blocking_failures"], indent=2)
    assert verdict["run_status_ok"] is True
    assert verdict["blocking_failures"] == []
    assert verdict["blocked_external"] == []
    assert verdict["registry_sha256"]


def test_flipped_map_acceptance_blocks_the_verdict(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    (tmp_path / "map_acceptance.json").write_text(
        json.dumps({"schema": "map_acceptance_v1", "valid_for_experiments": False}),
        encoding="utf-8",
    )
    verdict = _verdict(tmp_path, "debug", clean_env)
    assert verdict["status"] == VERDICT_FAIL
    blocked = [f["signal_id"] for f in verdict["blocking_failures"]]
    assert "MAP_ACCEPTANCE" in blocked, blocked
    assert verdict["run_status_ok"] is False


def test_missing_health_summary_blocks_the_verdict(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    (tmp_path / "pipeline_health_summary.json").unlink()
    verdict = _verdict(tmp_path, "debug", clean_env)
    assert verdict["status"] == VERDICT_FAIL
    assert any(
        f["signal_id"] == "PIPELINE_HEALTH" for f in verdict["blocking_failures"]
    ), verdict["blocking_failures"]


def test_health_summary_reporting_failure_blocks_the_verdict(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    (tmp_path / "pipeline_health_summary.json").write_text(
        json.dumps({"schema": "pipeline_health_summary/v1", "overall_ok": False, "failures": ["x"]}),
        encoding="utf-8",
    )
    verdict = _verdict(tmp_path, "debug", clean_env)
    assert verdict["status"] == VERDICT_FAIL
    assert verdict["pipeline_health_status"] == STATUS_FAIL


def test_empty_run_dir_can_never_pass(tmp_path, clean_env):
    verdict = _verdict(tmp_path, "structural_release", clean_env)
    assert verdict["status"] == VERDICT_FAIL
    assert verdict["blocking_failures"], "an empty run must name its failures"
    assert verdict["run_status_ok"] is False


def test_missing_artifact_that_is_readable_as_null_is_not_a_pass(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    (tmp_path / "gate_failures.json").write_text("null", encoding="utf-8")
    verdict = _verdict(tmp_path, "debug", clean_env)
    # A bare JSON null parses to None -> payload is None -> MISSING -> FAIL.
    assert verdict["status"] == VERDICT_FAIL


def test_persistence_failure_blocks_the_verdict(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    record_persistence_failure("RUN_SUMMARY", str(tmp_path / "run_summary.json"), "simulated IO error")
    verdict = _verdict(tmp_path, "debug", clean_env)
    assert verdict["status"] == VERDICT_FAIL
    assert verdict["evidence_persistence_failures"], verdict["evidence_persistence_failures"]
    assert any(
        f["class"] == "EVIDENCE_PERSISTENCE_FAILURE" for f in verdict["blocking_failures"]
    )


# --- NEW-343 identity cross-checks -----------------------------------------

def test_receipt_digest_mismatch_is_reported_as_identity_failure(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    final_xodr = tmp_path / "final.xodr"
    final_xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    (tmp_path / "final_artifact_receipt.json").write_text(
        json.dumps(
            {
                "schema": "final_artifact_receipt/v1",
                "final_artifact_sha256": "f" * 64,
                "structure_fingerprint": {"sha256": "1" * 64},
            }
        ),
        encoding="utf-8",
    )
    verdict = _verdict(tmp_path, "debug", clean_env, final_xodr=str(final_xodr))
    assert verdict["final_artifact_identity_valid"] is False
    problems = verdict["identity_detail"]["problems"]
    assert any("final_artifact_sha256 does not match" in p for p in problems), problems
    # debug does not require the receipt, so the cross-check surfaces as an
    # advisory instead of a silent pass; the identity verdict itself stays
    # False, which is what any consumer must key off.
    assert any(
        f.get("cross_check") == "identity" for f in verdict["advisories"]
    ), verdict["advisories"]
    assert verdict["status"] == VERDICT_PASS


def test_readiness_never_hides_behind_structural_validity(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    (tmp_path / "map_acceptance.json").write_text(
        json.dumps({"schema": "map_acceptance_v1", "valid_for_experiments": True}),
        encoding="utf-8",
    )
    verdict = _verdict(tmp_path, "debug", clean_env)
    assert verdict["experiment_readiness_valid"] is True
    assert verdict["readiness_detail"]["valid_for_experiments"] is True


# --- signal index -----------------------------------------------------------

def test_signal_index_reports_enablement_and_missing_evidence(tmp_path, clean_env):
    index = build_signal_index(str(tmp_path), profile="debug", settings=None, env=clean_env)
    assert index["schema"] == "signal_index/v1"
    signals = index["signals"]
    assert "MAP_ACCEPTANCE" in signals
    assert signals["MAP_ACCEPTANCE"]["enabled"] is True
    assert signals["MAP_ACCEPTANCE"]["status"] == STATUS_MISSING
    # settings-gated signal with no settings object -> not applicable, not "missing"
    assert signals["TILE_QA"]["enabled"] is False
    assert signals["TILE_QA"]["status"] == STATUS_NOT_APPLICABLE
    assert index["counts"]["missing"] >= 1


def test_signal_index_publishes_digests_for_present_artifacts(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    index = build_signal_index(str(tmp_path), profile="debug", settings=None, env=clean_env)
    entry = index["signals"]["MAP_ACCEPTANCE"]
    assert entry["present"] is True
    assert entry["status"] == STATUS_PASS
    assert entry["sha256"] and len(entry["sha256"]) == 64
    assert index["counts"]["pass"] >= 1


def test_signal_index_is_json_serialisable_and_covers_every_signal(tmp_path, clean_env):
    _write_debug_fixture(tmp_path)
    index = build_signal_index(str(tmp_path), profile="debug", settings=None, env=clean_env)
    assert set(index["signals"]) == set(SIGNAL_REGISTRY)
    json.loads(json.dumps(index))
