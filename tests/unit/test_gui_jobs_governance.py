"""Task 09 acceptance tests: experiments, job governance, evidence, diagnostics.

Covers T-EXP-01..06, T-EXP-CANCEL-01..06, T-JOB-01..06, T-DIAG-01..04 plus the
re-uses of T-FRESH-* and T-AUDIT-*.

Offline. No experiment is submitted and no scheduler is contacted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.jobs.governance import (
    ALLOWED_EXPORT_OPERATIONS,
    FINAL_VERDICT_NAME,
    LockAuthority,
    Job,
    JobState,
    JobSupervisor,
    CrashClass,
    EvidenceBrowser,
    classify_crash,
    exception_chain,
    observe_all_locks,
    observe_lock,
    read_final_verdict,
    scrub_sensitive_paths,
)


# ================================================================= T-EXP
def _run_dir(tmp_path: Path, *, verdict=None, marker=None, raw: str | None = None,
             name: str = "run_01") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (d / FINAL_VERDICT_NAME).write_text(raw, encoding="utf-8")
    elif verdict is not None:
        (d / FINAL_VERDICT_NAME).write_text(json.dumps({"status": verdict}), encoding="utf-8")
    if marker:
        (d / "SUCCESS.txt").write_text(marker, encoding="utf-8")
    return d


def test_T_EXP_01_only_final_run_verdict_is_authoritative(tmp_path):
    assert read_final_verdict(_run_dir(tmp_path, verdict="PASS")).status == "PASS"
    # SUCCESS.txt alone is never authoritative
    assert read_final_verdict(_run_dir(tmp_path, marker="ok", name="marker_only")).status == "NOT_EVALUATED"
    # neither present
    assert read_final_verdict(tmp_path / "empty").present is False


def test_T_EXP_02_missing_verdict_is_not_evaluated_never_pass(tmp_path):
    verdict = read_final_verdict(_run_dir(tmp_path))
    assert verdict.status == "NOT_EVALUATED"
    assert verdict.present is False
    assert "absent" in verdict.detail


def test_T_EXP_03_malformed_verdict_is_reported_not_inferred(tmp_path):
    verdict = read_final_verdict(_run_dir(tmp_path, raw="{not json"))
    assert verdict.malformed is True
    assert verdict.status == "NOT_EVALUATED"

    no_status = read_final_verdict(_run_dir(tmp_path, raw=json.dumps({"x": 1})))
    assert no_status.status == "NOT_EVALUATED"
    assert "no status" in no_status.detail


def test_T_EXP_04_stale_and_blocked_verdicts_normalise_honestly(tmp_path):
    assert read_final_verdict(_run_dir(tmp_path, verdict="BLOCKED_EXTERNAL")).status \
        == "BLOCKED_EXTERNAL"
    assert read_final_verdict(_run_dir(tmp_path, verdict="NOT_EVALUATED")).status \
        == "NOT_EVALUATED"
    assert read_final_verdict(_run_dir(tmp_path, verdict="FAIL")).status == "FAIL"


def test_T_EXP_05_jobs_are_not_submitted_by_default():
    supervisor = JobSupervisor(allow_scheduling=False)
    job = supervisor.submit("j1", "exp_baseline")
    assert job.state == JobState.NOT_SUBMITTED.value
    assert job.blocked_stage == "submission"
    assert job.as_dict()["verdict"] is None


def test_T_EXP_06_resume_is_never_claimed_without_a_checkpoint():
    job = Job("j", "exp")
    assert job.resume_supported is False
    job.state = JobState.FAILED.value
    assert job.resume_supported is False
    job.checkpointable = True
    assert job.resume_supported is True


# =========================================================== T-EXP-CANCEL
def test_T_EXP_CANCEL_01_cancellation_is_cooperative_and_recorded():
    supervisor = JobSupervisor()
    job = supervisor.submit("j", "exp")
    token = CancellationToken()
    token.cancel("operator stop")

    def work(_t):
        return "should not run"

    out = supervisor.run(job, work, token=token)
    assert out.state == JobState.CANCELLED.value
    assert out.timeline.crash_class == CrashClass.CANCELLED.value
    assert out.blocked_stage


def test_T_EXP_CANCEL_02_timeout_is_classified_and_recorded():
    supervisor = JobSupervisor()
    job = supervisor.submit("j", "exp")

    def boom(_t):
        raise TimeoutError("deadline exceeded")

    out = supervisor.run(job, boom)
    assert out.state == JobState.FAILED.value
    assert out.timeline.crash_class == CrashClass.TIMEOUT.value


def test_T_EXP_CANCEL_03_worker_crash_classification():
    assert classify_crash(ValueError("bad")) == CrashClass.EXCEPTION.value
    assert classify_crash(ImportError("no module")) == CrashClass.DEPENDENCY_MISSING.value
    assert classify_crash(MemoryError()) == CrashClass.OOM.value
    assert classify_crash(OperationCancelled("x")) == CrashClass.CANCELLED.value
    assert classify_crash(None) == CrashClass.NONE.value


def test_T_EXP_CANCEL_04_exception_chain_is_unwound_for_the_operator():
    try:
        try:
            raise ValueError("root cause")
        except ValueError as inner:
            raise RuntimeError("wrapper") from inner
    except RuntimeError as exc:
        chain = exception_chain(exc)
    assert len(chain) == 2
    assert "RuntimeError" in chain[0] and "ValueError" in chain[1]


def test_T_EXP_CANCEL_05_blocked_stage_is_the_exact_stage():
    supervisor = JobSupervisor()
    job = supervisor.submit("j", "exp")

    def boom(_t):
        raise RuntimeError("failure during execute")

    out = supervisor.run(job, boom)
    assert out.blocked_stage == "execute"
    assert out.timeline.events[-1].message == CrashClass.EXCEPTION.value


def test_T_EXP_CANCEL_06_dead_watchdog_does_not_produce_success():
    supervisor = JobSupervisor()
    job = supervisor.submit("j", "exp")

    def returns_after_cancel(_t):
        raise OperationCancelled("watchdog fired")

    out = supervisor.run(job, returns_after_cancel)
    assert out.state == JobState.CANCELLED.value
    assert out.state != JobState.SUCCEEDED.value


# ================================================================= T-JOB
def test_T_JOB_01_three_lock_authorities_are_reported_separately(tmp_path):
    locks = tmp_path / ".agent_locks"
    (locks / "worktree_leases").mkdir(parents=True)
    (locks / "writer.lock").write_text(json.dumps({
        "status": "active", "owner": "agent-a", "pid": 1,
        "expires_at": "2099-01-01T00:00:00+00:00"}), encoding="utf-8")
    (locks / "machine.lock").write_text(json.dumps({
        "status": "released", "owner": "agent-b"}), encoding="utf-8")

    observed = observe_all_locks(tmp_path)
    assert set(observed) == {"REPO_WRITER", "WORKTREE_LEASE", "MACHINE_LEASE"}
    assert observed["REPO_WRITER"].blocking is True
    assert observed["REPO_WRITER"].owner == "agent-a"
    assert observed["MACHINE_LEASE"].blocking is False
    assert observed["WORKTREE_LEASE"].state == "absent"


def test_T_JOB_02_lock_conflict_is_visible_per_authority():
    a = observe_lock(Path("/nope/writer.lock"), LockAuthority.REPO_WRITER)
    assert a.state == "absent"
    assert a.blocking is False
    assert a.as_dict()["authority"] == "REPO_WRITER"


def test_T_JOB_03_expired_lock_is_marked_stale_not_active(tmp_path):
    path = tmp_path / "writer.lock"
    path.write_text(json.dumps({
        "status": "active", "owner": "x", "expires_at": "2000-01-01T00:00:00+00:00"}),
        encoding="utf-8")
    observation = observe_lock(path, LockAuthority.REPO_WRITER)
    assert observation.stale is True
    assert observation.blocking is False
    assert "expired" in observation.detail


def test_T_JOB_04_malformed_lock_is_reported_not_repaired(tmp_path):
    path = tmp_path / "writer.lock"
    path.write_text("{malformed json", encoding="utf-8")
    observation = observe_lock(path, LockAuthority.REPO_WRITER)
    assert observation.malformed is True
    assert observation.state == "malformed"
    assert path.read_text(encoding="utf-8") == "{malformed json"  # untouched


def test_T_JOB_05_scheduled_submission_is_not_claimed():
    assert "submit_slurm" not in ALLOWED_EXPORT_OPERATIONS
    supervisor = JobSupervisor(allow_scheduling=False)
    assert supervisor.submit("j", "e").state == JobState.NOT_SUBMITTED.value


def test_T_JOB_06_job_control_defaults_read_only():
    supervisor = JobSupervisor()
    job = supervisor.submit("j", "exp")
    assert job.state == JobState.NOT_SUBMITTED.value
    # even with scheduling allowed, the run still needs real work
    allowed = JobSupervisor(allow_scheduling=True)
    assert allowed.submit("j", "exp").state == JobState.PENDING.value


# ================================================================ T-DIAG
def test_T_DIAG_01_missing_artifact_is_reported(tmp_path):
    browser = EvidenceBrowser(current_sha="abc123")
    record = browser.inspect("map", tmp_path / "nope.json")
    assert record.trustworthy is False
    assert "missing" in record.detail


def test_T_DIAG_02_revision_drift_is_surfaced_not_hidden(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"git_sha": "old"}), encoding="utf-8")
    browser = EvidenceBrowser(current_sha="new")
    record = browser.inspect("r", path)
    assert record.revision_ok is False
    assert record.trustworthy is False
    assert "revision" in record.detail


def test_T_DIAG_03_compare_labels_provenance_prominently(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"git_sha": "new"}), encoding="utf-8")
    b.write_text(json.dumps({"git_sha": "new"}), encoding="utf-8")
    browser = EvidenceBrowser(current_sha="new")
    payload = browser.compare(browser.inspect("a", a), browser.inspect("b", b))
    assert payload["historical"]["label"] == "HISTORICAL"
    assert payload["current"]["label"] == "CURRENT"
    assert payload["comparable"] is True


def test_T_DIAG_04_export_scrubs_private_paths_and_contains_no_secrets(tmp_path):
    path = tmp_path / "e.json"
    path.write_text(json.dumps({"git_sha": "new",
                                "p": r"C:\Users\michal\secret\run.json"}), encoding="utf-8")
    browser = EvidenceBrowser(current_sha="new")
    result = browser.export([browser.inspect("e", path)])
    assert result.ok is True
    blob = json.dumps(result.unwrap())
    # the payload is never exported at all, so no secret can leak
    assert "michal" not in blob
    assert r"C:\Users\michal\secret" not in blob
    assert "[PRIVATE]" in blob          # the record path itself is scrubbed
    assert scrub_sensitive_paths(r"see D:\Users\admin\x").endswith("[PRIVATE]\\x")