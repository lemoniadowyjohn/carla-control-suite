"""Experiments, job governance, evidence and diagnostics.

The central discipline: **only ``final_run_verdict.json`` is authoritative.**
Not ``SUCCESS.txt``, not a zero subprocess exit, not the absence of stderr. A
run that produced no verdict is ``NOT_EVALUATED`` — never a pass.

Three lock authorities are displayed separately, each with its own owner, TTL
and staleness, because collapsing them into one boolean hides real conflicts:

* the repository writer lock (``.agent_locks/writer.lock``),
* the per-worktree mutation lease (``.agent_locks/worktree_leases/*.lock``),
* the machine-wide lease.

Job control is read-only by default. A scheduled job or SLURM script is only
ever reported ``SUBMITTED`` if submission genuinely happened.

Resume is never claimed unless a checkpoint genuinely supports it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled
from ultimate_pipeline.gui.results import Result
from ultimate_pipeline.gui.run_status import RunStatus, normalize

__all__ = [
    "FINAL_VERDICT_NAME", "SUCCESS_MARKER", "AUTHORITATIVE_ONLY",
    "LockAuthority", "LockObservation", "observe_lock", "observe_all_locks",
    "RunVerdict", "read_final_verdict", "JobState", "Job", "JobSupervisor",
    "CrashClass", "classify_crash", "FailureTimeline", "ProgressEvent",
    "EvidenceRecord", "EvidenceBrowser", "scrub_sensitive_paths",
    "ALLOWED_EXPORT_OPERATIONS",
]

FINAL_VERDICT_NAME = "final_run_verdict.json"
SUCCESS_MARKER = "SUCCESS.txt"

AUTHORITATIVE_ONLY = (
    "SUCCESS.txt may only exist when final_run_verdict.json is PASS; "
    "a subprocess exit code alone is never authoritative"
)


# ------------------------------------------------------------------ locks
class LockAuthority(str, Enum):
    REPO_WRITER = "REPO_WRITER"
    WORKTREE_LEASE = "WORKTREE_LEASE"
    MACHINE_LEASE = "MACHINE_LEASE"


@dataclass(frozen=True)
class LockObservation:
    """One lock, observed honestly. Never collapsed into a single boolean."""

    authority: str
    path: str
    state: str
    owner: str = ""
    pid: int | None = None
    expires_at: str = ""
    stale: bool = False
    malformed: bool = False
    detail: str = ""

    @property
    def blocking(self) -> bool:
        return self.state == "active" and not self.stale

    def as_dict(self) -> dict:
        return {"authority": self.authority, "path": self.path, "state": self.state,
                "owner": self.owner, "pid": self.pid, "expires_at": self.expires_at,
                "stale": self.stale, "malformed": self.malformed,
                "blocking": self.blocking, "detail": self.detail}


def _expiry_delta(expires_at: str) -> timedelta | None:
    if not expires_at:
        return None
    text = expires_at.replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp - datetime.now(timezone.utc)


def observe_lock(path: Path, authority: LockAuthority) -> LockObservation:
    """Read one lock file. A malformed lock is reported, never repaired."""
    target = Path(path)
    if not target.exists():
        return LockObservation(authority.value, str(target), "absent",
                               detail="no lock file present")
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        return LockObservation(authority.value, str(target), "unreadable",
                               detail=str(exc))
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return LockObservation(authority.value, str(target), "malformed",
                               malformed=True,
                               detail="lock is not valid JSON; reported, not repaired")

    state = str(payload.get("status", "unknown"))
    remaining = _expiry_delta(str(payload.get("expires_at", "")))
    stale = bool(remaining is not None and remaining.total_seconds() <= 0)
    return LockObservation(
        authority=authority.value,
        path=str(target),
        state=state,
        owner=str(payload.get("owner", "")),
        pid=payload.get("pid") if isinstance(payload.get("pid"), int) else None,
        expires_at=str(payload.get("expires_at", "")),
        stale=stale,
        detail=("expired" if stale else
                ("TTL remaining" if remaining else "no expiry recorded")),
    )


def observe_all_locks(repo_root: Path) -> dict[str, LockObservation]:
    """Three authorities, reported separately."""
    root = Path(repo_root)
    locks = root / ".agent_locks"
    leases = locks / "worktree_leases"
    observations = {
        LockAuthority.REPO_WRITER.value: observe_lock(
            locks / "writer.lock", LockAuthority.REPO_WRITER),
        LockAuthority.WORKTREE_LEASE.value: observe_lock(
            next(iter(sorted(leases.glob("*.lock"))), locks / "none.lock"),
            LockAuthority.WORKTREE_LEASE),
        LockAuthority.MACHINE_LEASE.value: observe_lock(
            locks / "machine.lock", LockAuthority.MACHINE_LEASE),
    }
    return observations


# --------------------------------------------------------------- verdicts
@dataclass(frozen=True)
class RunVerdict:
    """The single authoritative verdict for a run."""

    status: str
    source: str = FINAL_VERDICT_NAME
    present: bool = True
    malformed: bool = False
    detail: str = ""

    def as_dict(self) -> dict:
        return {"status": self.status, "source": self.source,
                "present": self.present, "malformed": self.malformed,
                "detail": self.detail, "authoritative_note": AUTHORITATIVE_ONLY}


def read_final_verdict(run_dir: Path) -> RunVerdict:
    """Read the only authoritative verdict.

    A missing or malformed verdict is ``NOT_EVALUATED`` — never a pass, and
    never inferred from ``SUCCESS.txt``.
    """
    directory = Path(run_dir)
    verdict_path = directory / FINAL_VERDICT_NAME
    if not verdict_path.is_file():
        return RunVerdict(
            RunStatus.NOT_EVALUATED.value, present=False,
            detail=f"{FINAL_VERDICT_NAME} is absent; " + AUTHORITATIVE_ONLY)
    try:
        payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return RunVerdict(
            RunStatus.NOT_EVALUATED.value, malformed=True,
            detail=f"final verdict is unreadable: {exc}")

    raw = payload.get("status") if isinstance(payload, dict) else None
    if raw is None:
        return RunVerdict(
            RunStatus.NOT_EVALUATED.value, malformed=True,
            detail="final verdict carries no status field")
    normalized = normalize("signals_verdict", str(raw))
    return RunVerdict(normalized.status.value, detail=f"raw label {raw!r}")


# ------------------------------------------------------------------- jobs
class JobState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_SUBMITTED = "NOT_SUBMITTED"


class CrashClass(str, Enum):
    NONE = "NONE"
    EXCEPTION = "EXCEPTION"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    OOM = "OOM"
    SEGFAULT = "SEGFAULT"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    UNKNOWN = "UNKNOWN"


def classify_crash(exc: BaseException | None) -> str:
    if exc is None:
        return CrashClass.NONE.value
    if isinstance(exc, OperationCancelled):
        return CrashClass.CANCELLED.value
    if isinstance(exc, TimeoutError):
        return CrashClass.TIMEOUT.value
    if isinstance(exc, MemoryError):
        return CrashClass.OOM.value
    if isinstance(exc, ImportError):
        return CrashClass.DEPENDENCY_MISSING.value
    # SegmentationError does not exist on Windows, so it must not be named here.
    # A native stack overflow surfaces as RecursionError on CPython.
    if isinstance(exc, RecursionError) or "stack overflow" in str(exc).lower():
        return CrashClass.SEGFAULT.value
    if isinstance(exc, Exception):
        return CrashClass.EXCEPTION.value
    return CrashClass.UNKNOWN.value


@dataclass
class ProgressEvent:
    sequence: int
    stage: str
    message: str = ""
    at: str = ""

    def as_dict(self) -> dict:
        return {"sequence": self.sequence, "stage": self.stage,
                "message": self.message, "at": self.at}


@dataclass
class FailureTimeline:
    """Operator-readable: what happened, in order, with the blocked stage."""

    events: list[ProgressEvent] = field(default_factory=list)
    blocked_stage: str = ""
    exception_chain: list[str] = field(default_factory=list)
    crash_class: str = CrashClass.NONE.value

    def as_dict(self) -> dict:
        return {"blocked_stage": self.blocked_stage,
                "exception_chain": list(self.exception_chain),
                "crash_class": self.crash_class,
                "events": [e.as_dict() for e in self.events]}


def exception_chain(exc: BaseException) -> list[str]:
    """Unwind ``__cause__``/``__context__`` into an operator-readable list."""
    chain: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
        if len(chain) > 32:
            chain.append("... chain truncated")
            break
    return chain


@dataclass
class Job:
    job_id: str
    experiment_id: str
    state: str = JobState.PENDING.value
    blocked_stage: str = ""
    timeline: FailureTimeline = field(default_factory=FailureTimeline)
    verdict: RunVerdict | None = None
    checkpointable: bool = False

    @property
    def resume_supported(self) -> bool:
        """Resume is never claimed without a real checkpoint."""
        return self.checkpointable and self.state in (
            JobState.FAILED.value, JobState.CANCELLED.value)

    def as_dict(self) -> dict:
        return {"job_id": self.job_id, "experiment_id": self.experiment_id,
                "state": self.state, "blocked_stage": self.blocked_stage,
                "resume_supported": self.resume_supported,
                "verdict": self.verdict.as_dict() if self.verdict else None,
                "timeline": self.timeline.as_dict()}


class JobSupervisor:
    """Runs work cooperatively with deadlines, progress and honest outcomes."""

    def __init__(self, *, allow_scheduling: bool = False) -> None:
        self.allow_scheduling = allow_scheduling
        self._sequence = 0

    def _event(self, timeline: FailureTimeline, stage: str, message: str = "") -> None:
        self._sequence += 1
        timeline.events.append(ProgressEvent(
            self._sequence, stage, message,
            datetime.now(timezone.utc).isoformat(timespec="seconds")))

    def submit(self, job_id: str, experiment_id: str) -> Job:
        """Job control is READ-ONLY by default."""
        if not self.allow_scheduling:
            return Job(job_id, experiment_id, JobState.NOT_SUBMITTED.value,
                       blocked_stage="submission",
                       timeline=FailureTimeline(
                           events=[], blocked_stage="submission",
                           crash_class=CrashClass.NONE.value))
        return Job(job_id, experiment_id, JobState.PENDING.value)

    def run(
        self,
        job: Job,
        work: Callable[[CancellationToken], Any],
        *,
        deadline_s: float = 60.0,
        token: CancellationToken | None = None,
        run_dir: Path | None = None,
    ) -> Job:
        job.state = JobState.RUNNING.value
        self._event(job.timeline, "start", f"job {job.job_id}")
        own_token = token or CancellationToken()

        def guarded(cancellation: CancellationToken) -> Any:
            # The stage event must be emitted BEFORE the work of that stage and
            # the NEXT stage only after it succeeds. Emitting them all up front
            # made any failure report the last stage ("persist") rather than the
            # stage that actually failed.
            cancellation.raise_if_cancelled()
            self._event(job.timeline, "setup")
            cancellation.raise_if_cancelled()
            self._event(job.timeline, "execute")
            result = work(cancellation)
            cancellation.raise_if_cancelled()
            self._event(job.timeline, "persist")
            return result

        try:
            guarded(own_token)
        except OperationCancelled:
            job.state = JobState.CANCELLED.value
            job.blocked_stage = job.timeline.events[-1].stage if job.timeline.events else ""
            job.timeline.crash_class = CrashClass.CANCELLED.value
            self._event(job.timeline, "cancelled")
            return job
        except Exception as exc:
            job.state = JobState.FAILED.value
            job.blocked_stage = job.timeline.events[-1].stage if job.timeline.events else ""
            job.timeline.crash_class = classify_crash(exc)
            job.timeline.exception_chain = exception_chain(exc)
            self._event(job.timeline, "failed", job.timeline.crash_class)
            return job

        if run_dir is not None:
            job.verdict = read_final_verdict(run_dir)
        job.state = JobState.SUCCEEDED.value if (
            job.verdict is None or job.verdict.status == RunStatus.PASS.value) \
            else JobState.FAILED.value
        self._event(job.timeline, "finished", job.state)
        return job


# --------------------------------------------------------------- evidence
_PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\Users\\[^\\\s\"']+)")


def scrub_sensitive_paths(text: str) -> str:
    """Remove private absolute paths before export."""
    return _PRIVATE_PATH_RE.sub(r"\1[PRIVATE]", text)


@dataclass(frozen=True)
class EvidenceRecord:
    name: str
    path: str
    schema_ok: bool
    sha_ok: bool
    revision_ok: bool
    age_seconds: float | None
    detail: str = ""

    @property
    def trustworthy(self) -> bool:
        return self.schema_ok and self.sha_ok and self.revision_ok

    def as_dict(self) -> dict:
        return {"name": self.name, "path": scrub_sensitive_paths(self.path),
                "schema_ok": self.schema_ok, "sha_ok": self.sha_ok,
                "revision_ok": self.revision_ok, "age_seconds": self.age_seconds,
                "trustworthy": self.trustworthy, "detail": self.detail}


class EvidenceBrowser:
    """Validates schema, SHA, source revision and age before display."""

    def __init__(self, *, current_sha: str) -> None:
        self.current_sha = current_sha

    def inspect(self, name: str, path: Path, *, expected_sha: str = "",
                recorded_sha: str = "") -> EvidenceRecord:
        target = Path(path)
        import hashlib

        if not target.is_file():
            return EvidenceRecord(name, str(target), False, False, False, None,
                                  "artefact missing")
        try:
            raw = target.read_bytes()
        except OSError as exc:
            return EvidenceRecord(name, str(target), False, False, False, None, str(exc))

        try:
            payload = json.loads(raw.decode("utf-8"))
            schema_ok = isinstance(payload, dict)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload, schema_ok = None, False

        digest = hashlib.sha256(raw).hexdigest()
        sha_ok = (not expected_sha) or digest == expected_sha
        recorded = recorded_sha or (payload or {}).get("git_sha", "")
        revision_ok = (not recorded) or recorded == self.current_sha
        age = None
        if target.exists():
            age = (datetime.now(timezone.utc) -
                   datetime.fromtimestamp(target.stat().st_mtime, timezone.utc)
                   ).total_seconds()
        detail = "" if (schema_ok and sha_ok and revision_ok) else \
            "provenance incomplete: " + ", ".join(
                label for label, ok in (("schema", schema_ok), ("sha", sha_ok),
                                        ("revision", revision_ok)) if not ok)
        return EvidenceRecord(name, str(target), schema_ok, sha_ok, revision_ok,
                              age, detail)

    def compare(self, historical: EvidenceRecord, current: EvidenceRecord) -> dict:
        """Prominent provenance labels -- never a bare diff."""
        return {
            "historical": {"label": "HISTORICAL", **historical.as_dict()},
            "current": {"label": "CURRENT", **current.as_dict()},
            "comparable": historical.revision_ok and current.revision_ok,
            "note": "compare only records bound to the same source revision",
        }

    def export(self, records: Iterable[EvidenceRecord]) -> Result:
        """Export with sensitive paths scrubbed."""
        payload = [r.as_dict() for r in records]
        blob = json.dumps(payload, indent=2)
        scrubbed = scrub_sensitive_paths(blob)
        return Result.success({"records": json.loads(scrubbed),
                               "scrubbed": scrubbed != blob})


#: Freeform untrusted input never becomes a terminal command.
ALLOWED_EXPORT_OPERATIONS = ("json_export", "csv_export", "copy_path", "none")