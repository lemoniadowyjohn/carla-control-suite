"""V95 offline adversarial tests: GUI status is never release authority.

No CARLA, PyQt, network, GPU or production files are needed. The same tests
must run on the patched GUI branch, CI and a Windows operator checkout.
"""
from __future__ import annotations

import hashlib
import json
import threading

import pytest

from ultimate_pipeline.gui.cancellation import CancellationToken
from ultimate_pipeline.gui.health import ConnectionState, probe_stages
from ultimate_pipeline.gui.jobs.governance import (
    EvidenceBrowser, JobSupervisor, LockAuthority, observe_all_locks,
    observe_lock, observe_worktree_leases, read_final_verdict, scrub_sensitive_paths,
)
from ultimate_pipeline.gui.operator_projection import (
    BackendRunSnapshot, RunProjection, SCHEMA,
    StaleSnapshot, UnverifiedSnapshot, verified_report_bytes,
)
from ultimate_pipeline.gui.results import Result, Tri

S40 = "a" * 40
S64 = "b" * 64
C64 = "c" * 64
D64 = "d" * 64


def snapshot_payload(**overrides):
    result = {
        "schema": SCHEMA,
        "identity": {"run_id": "run-001", "source_sha": S40,
                     "config_sha256": C64, "xodr_sha256": S64,
                     "purpose": "release", "lease_generation": 3},
        "backend_epoch": "node-epoch-1", "sequence": 1, "state": "RUNNING",
        "stage": "generation", "terminal_verdict": "NOT_EVALUATED",
        "last_verified_at": "", "published_artifact_sha256": None,
        "report_count": 0, "provenance_verified": False,
        "runtime_verified": False, "source_verified": False,
        "ci_source_sha": None, "ci_state": "NOT_RUN",
        "carla_runtime_state": "NOT_RUN", "gnn_feature_state": "UNKNOWN", "gates": [],
    }
    result.update(overrides)
    return result


def parse(data, trusted=True):
    return BackendRunSnapshot.from_payload(data, trusted_transport=trusted)


def test_untrusted_transport_cannot_manufacture_success():
    payload = snapshot_payload(state="PUBLISHED_RUNTIME_CERTIFIED", terminal_verdict="PASS",
        last_verified_at="2026-11-12T00:00:00Z", published_artifact_sha256=S64,
        provenance_verified=True, runtime_verified=True, source_verified=True,
        ci_source_sha=S40, ci_state="PASS", carla_runtime_state="PASS",
        gates=[{"gate_id": "MAP_ACCEPTANCE", "required": True, "status": "PASS",
                "artifact_sha256": S64, "verified_at": "2026-11-12T00:00:00Z"}])
    with pytest.raises(UnverifiedSnapshot, match="authenticated"):
        parse(payload, trusted=False)
    assert parse(payload).production_ready is True


@pytest.mark.parametrize("field,bad", [
    ("schema", "unknown-schema"), ("state", "SUCCESS"),
    ("sequence", True), ("sequence", -1), ("stage", ""),
    ("backend_epoch", ""), ("terminal_verdict", "SUCCEEDED"),
    ("report_count", 1.5),
])
def test_bad_snapshot_fields_rejected(field, bad):
    with pytest.raises(UnverifiedSnapshot):
        parse(snapshot_payload(**{field: bad}))


@pytest.mark.parametrize("field,bad", [
    ("run_id", "../escape"), ("source_sha", "short"),
    ("config_sha256", "E" * 64), ("lease_generation", True),
    ("lease_generation", 0), ("purpose", "unverified")
])
def test_invalid_identity_rejected(field, bad):
    payload = snapshot_payload()
    payload["identity"][field] = bad
    with pytest.raises(UnverifiedSnapshot):
        parse(payload)


def test_backend_claims_cannot_certify_diagnostic_run():
    payload = snapshot_payload(state="PUBLISHED_RUNTIME_CERTIFIED", terminal_verdict="PASS",
        last_verified_at="2026-11-12T00:00:00Z", published_artifact_sha256=S64,
        provenance_verified=True, runtime_verified=True, source_verified=True,
        ci_source_sha=S40)
    payload["identity"]["purpose"] = "diagnostic"
    with pytest.raises(UnverifiedSnapshot, match="runtime publication"):
        parse(payload)


def test_runtime_certification_requires_matching_map_hash_and_ci_source():
    payload = snapshot_payload(state="PUBLISHED_RUNTIME_CERTIFIED", terminal_verdict="PASS",
        last_verified_at="2026-11-12T00:00:00Z", published_artifact_sha256=D64,
        provenance_verified=True, runtime_verified=True, source_verified=True,
        ci_source_sha=S40)
    with pytest.raises(UnverifiedSnapshot):
        parse(payload)
    payload["published_artifact_sha256"] = S64
    payload["ci_source_sha"] = "f" * 40
    with pytest.raises(UnverifiedSnapshot):
        parse(payload)


def test_unverified_source_only_success_rejected():
    payload = snapshot_payload(state="SUCCEEDED_SOURCE_ONLY", terminal_verdict="PASS",
        source_verified=True, provenance_verified=True, ci_source_sha=None,
        ci_state="PASS", last_verified_at="2026-11-12T00:00:00Z")
    with pytest.raises(UnverifiedSnapshot):
        parse(payload)
    payload["ci_source_sha"] = S40
    assert parse(payload).state == "SUCCEEDED_SOURCE_ONLY"


def test_cancelled_and_failed_must_not_have_pass_verdict():
    for state in ("FAILED", "CANCELLED", "BLOCKED_EXTERNAL"):
        with pytest.raises(UnverifiedSnapshot):
            parse(snapshot_payload(state=state, terminal_verdict="PASS"))


def test_replayed_and_cross_run_events_rejected():
    initial = parse(snapshot_payload())
    store = RunProjection(initial)
    with pytest.raises(StaleSnapshot):
        store.accept(initial)
    newer = parse(snapshot_payload(sequence=2, state="CANCEL_REQUESTED"))
    store.accept(newer)
    with pytest.raises(StaleSnapshot):
        store.accept(parse(snapshot_payload(sequence=3, state="RUNNING")))
    cross = snapshot_payload(sequence=4)
    cross["identity"]["run_id"] = "other-run"
    with pytest.raises(StaleSnapshot):
        store.accept(parse(cross))
    with pytest.raises(StaleSnapshot):
        store.accept(parse(snapshot_payload(sequence=5, backend_epoch="server-restarted")))


def test_terminal_result_immutable_under_new_sequence():
    end = parse(snapshot_payload(state="FAILED", terminal_verdict="FAIL"))
    store = RunProjection(end)
    with pytest.raises(StaleSnapshot):
        store.accept(parse(snapshot_payload(sequence=2, state="QUEUED")))


def test_verified_report_bytes_rejects_traversal_wrong_hash_and_symlink(tmp_path):
    path = tmp_path / "safe" / "receipt.json"
    path.parent.mkdir()
    path.write_bytes(b"{}")
    digest = hashlib.sha256(b"{}").hexdigest()
    assert verified_report_bytes(tmp_path, "safe/receipt.json", digest) == b"{}"
    with pytest.raises(ValueError):
        verified_report_bytes(tmp_path, "../receipt.json", digest)
    with pytest.raises(ValueError):
        verified_report_bytes(tmp_path, "safe/receipt.json", S64)
    with pytest.raises(ValueError):
        verified_report_bytes(tmp_path, "safe/receipt.json", digest, max_bytes=1)
    link = tmp_path / "link.json"
    try:
        link.symlink_to(path)
    except (NotImplementedError, OSError):
        pass
    else:
        with pytest.raises(ValueError, match="symlink"):
            verified_report_bytes(tmp_path, "link.json", digest)


def test_verdict_pass_without_backend_validation_never_promoted(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "final_run_verdict.json").write_text(json.dumps({"status": "PASS"}))
    assert read_final_verdict(run).status == "NOT_EVALUATED"
    (run / "SUCCESS.txt").write_text("legacy marker")
    assert read_final_verdict(run).status == "NOT_EVALUATED"


def test_job_without_run_verdict_never_succeeds():
    supervisor = JobSupervisor(allow_scheduling=True)
    job = supervisor.submit("job-1", "experiment")
    final = supervisor.run(job, lambda token: "callback completed", run_dir=None)
    assert final.state != "SUCCEEDED"
    assert final.blocked_stage == "terminal_verification"


def test_job_with_unbound_pass_still_not_success(tmp_path):
    (tmp_path / "final_run_verdict.json").write_text(json.dumps({"status": "PASS"}))
    supervisor = JobSupervisor(allow_scheduling=True)
    job = supervisor.submit("job-2", "experiment")
    final = supervisor.run(job, lambda token: "completed", run_dir=tmp_path)
    assert final.state != "SUCCEEDED"
    assert final.verdict.status == "NOT_EVALUATED"


def test_evidence_without_digest_or_revision_never_trustworthy(tmp_path):
    target = tmp_path / "a.json"
    target.write_text(json.dumps({"value": "anything"}))
    browser = EvidenceBrowser(current_sha=S40)
    result = browser.inspect("a", target)
    assert result.sha_ok is False and result.revision_ok is False
    assert result.trustworthy is False
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    assert browser.inspect("a", target, expected_sha=digest, recorded_sha=S40).trustworthy


def test_lock_json_list_malformed_and_blocks(tmp_path):
    path = tmp_path / "lease.lock"
    path.write_text("[]")
    lock = observe_lock(path, LockAuthority.WORKTREE_LEASE)
    assert lock.malformed and lock.blocking


def test_all_leases_aggregated_not_only_first(tmp_path):
    leases = tmp_path / ".agent_locks" / "worktree_leases"
    leases.mkdir(parents=True)
    (leases / "first.lock").write_text(json.dumps({"status": "released"}))
    (leases / "second.lock").write_text(json.dumps({"status": "active", "owner": "operator",
                                                "expires_at": "2099-01-01T00:00:00Z"}))
    assert len(observe_worktree_leases(tmp_path)) == 2
    observation = observe_all_locks(tmp_path)["WORKTREE_LEASE"]
    assert observation.blocking and observation.state == "active"
    assert "2 leases" in observation.detail


def test_private_windows_username_redacted():
    text = scrub_sensitive_paths(r"C:\Users\alice\private\file.json")
    assert "alice" not in text
    assert "[PRIVATE]" in text


def test_cancellation_registration_during_event_publication_not_lost():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    class PausingEvent(threading.Event):
        def set(self):
            entered.set()
            assert release.wait(2)
            super().set()

    token = CancellationToken()
    token._event = PausingEvent()
    canceller = threading.Thread(target=lambda: token.cancel("reason"))
    canceller.start()
    assert entered.wait(2)
    registered = threading.Event()
    registrar = threading.Thread(target=lambda: (token.on_cancel(calls.append), registered.set()))
    registrar.start()
    registered.wait(0.1)
    release.set()
    canceller.join(2)
    registrar.join(2)
    assert not canceller.is_alive() and not registrar.is_alive()
    assert calls == ["reason"]


def test_connection_health_missing_world_and_exceptions_fail_closed(monkeypatch):
    from ultimate_pipeline.gui import health as health_module
    monkeypatch.setattr(health_module, "_tcp_probe", lambda *args: True)

    class Backend:
        def probe(self, **kwargs):
            return Result.success("ok")
        def server_version(self):
            return "0.9.16"
        def available_maps(self):
            return Tri.available_value(["Town01"])
        def read_settings(self):
            return object()  # missing explicit available=True

    health = probe_stages(Backend(), "127.0.0.1", 2000)
    assert not health.healthy and health.state is ConnectionState.UNHEALTHY
    class Broken(Backend):
        def available_maps(self):
            raise RuntimeError("RPC offline")
    health = probe_stages(Broken(), "127.0.0.1", 2000)
    assert not health.healthy and health.state is ConnectionState.UNHEALTHY
    assert health.first_failing_stage is not None


def test_tcp_false_does_not_count_as_open_port(monkeypatch):
    from ultimate_pipeline.gui import health as health_module
    monkeypatch.setattr(health_module, "_tcp_probe", lambda *args: False)
    health = probe_stages(object(), "127.0.0.1", 2000)
    assert health.state is ConnectionState.UNHEALTHY
    assert health.first_failing_stage is not None


def test_readonly_supervisor_does_not_execute_work():
    supervisor = JobSupervisor()
    job = supervisor.submit("job-ro", "experiment")
    calls = []
    outcome = supervisor.run(job, lambda token: calls.append("wrong"))
    assert calls == [] and outcome.state == "NOT_SUBMITTED"


def test_supervisor_prevents_duplicate_same_job_execution():
    supervisor = JobSupervisor(allow_scheduling=True)
    job = supervisor.submit("job-dupe", "experiment")
    calls = []
    supervisor.run(job, lambda token: calls.append("once"))
    supervisor.run(job, lambda token: calls.append("twice"))
    assert calls == ["once"]


def test_supervisor_invalid_deadline_refused_before_work():
    supervisor = JobSupervisor(allow_scheduling=True)
    job = supervisor.submit("job-deadline", "experiment")
    calls = []
    done = supervisor.run(job, lambda token: calls.append("wrong"), deadline_s=float("nan"))
    assert done.state == "FAILED" and calls == []
    assert done.timeline.crash_class == "TIMEOUT"


def test_cannot_publish_runtime_without_gate_or_real_ci_state():
    payload = snapshot_payload(state="PUBLISHED_RUNTIME_CERTIFIED", terminal_verdict="PASS",
        last_verified_at="2026-11-12T00:00:00Z", published_artifact_sha256=S64,
        provenance_verified=True, runtime_verified=True, source_verified=True,
        ci_source_sha=S40, ci_state="PASS", carla_runtime_state="PASS", gates=[])
    with pytest.raises(UnverifiedSnapshot):
        parse(payload)
    payload["gates"] = [{"gate_id": "MAP_ACCEPTANCE", "required": True,
                         "status": "PASS", "artifact_sha256": S64,
                         "verified_at": "2026-11-12T00:00:00Z"}]
    assert parse(payload).production_ready
    payload["ci_state"] = "NOT_RUN"
    with pytest.raises(UnverifiedSnapshot):
        parse(payload)
