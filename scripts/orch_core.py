"""Orchestration hardening core: identity, termination receipts, atomic run
journal, and a machine-wide single-writer operation lease.

Design notes that matter:

* Process identity is (pid, creation_time, run_id). PID alone is unsafe because
  Windows recycles PIDs; a recycled PID must never be mistaken for the original
  owner of a lease or a receipt.

* Every write of a receipt or journal entry is atomic: temp file in the same
  directory, flush, fsync, then os.replace. os.replace is atomic on NTFS within
  a volume, so a reader never observes a partially written receipt.

* The lease is advisory-but-enforced: acquisition fails closed when a valid
  foreign lease exists, and a stale lease (owner demonstrably dead) must be
  explicitly reconciled rather than silently stolen.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import tempfile
import uuid

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# atomic IO
# ---------------------------------------------------------------------------
def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def atomic_write_bytes(path: str, data: bytes) -> None:
    """Write `data` to `path` atomically, durably."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: str, payload) -> str:
    blob = json.dumps(payload, indent=2, sort_keys=True, default=str)
    atomic_write_bytes(path, blob.encode("utf-8"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sha256_file(path: str):
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# process identity
# ---------------------------------------------------------------------------
def process_creation_time(pid: int):
    """Authoritative process creation time, or None if the PID is not live.

    Read from the OS rather than trusting a cached value so that a recycled PID
    produces a different (or absent) creation time.
    """
    script = (
        "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" "
        "-ErrorAction SilentlyContinue; "
        "if($p){([datetime]$p.CreationDate).ToUniversalTime().ToString('o')}"
        % pid
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, errors="replace",
                             timeout=120).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def process_identity(pid: int, run_id: str = None):
    """Return an identity record, or a record marked dead when PID is absent."""
    created = process_creation_time(pid)
    record = {
        "pid": int(pid),
        "creation_time_utc": created,
        "run_id": run_id,
        "identity_key": None if created is None else "%d|%s" % (pid, created),
        "alive": created is not None,
    }
    return record


# ---------------------------------------------------------------------------
# exit code / termination classification
# ---------------------------------------------------------------------------
TERMINATION_NORMAL = "NORMAL_EXIT"
TERMINATION_NONZERO = "EXPLICIT_NONZERO_EXIT"
TERMINATION_C_CONTROL = "STATUS_CONTROL_C_EXIT"
TERMINATION_ACCESS_VIOLATION = "ACCESS_VIOLATION"
TERMINATION_RESOURCE = "OOM_OR_RESOURCE_FAILURE"
TERMINATION_EXTERNAL = "EXTERNAL_TERMINATION"
TERMINATION_WORKER_LOST = "WORKER_DISAPPEARANCE"
TERMINATION_TIMEOUT = "TIMEOUT"
TERMINATION_SIGNALLED = "TERMINATED_BY_SIGNAL"
TERMINATION_UNKNOWN = "UNKNOWN"

# Windows NT status codes seen in practice for CARLA/UE workloads.
_NT_ACCESS_VIOLATION = 0xC0000005
_NT_STACK_BUFFER_OVERRUN = 0xC0000409
_NT_HEAP_CORRUPTION = 0xC0000374
_NT_STATUS_CONTROL_C_EXIT = 0xC000013A
_NT_IN_PAGE_ERROR = 0xC0000006
_NT_VM_DLL_INIT_FAILED = 0xC0000028
_NT_DLL_NOT_FOUND = 0xC0000135
_NT_NO_MEMORY = 0xC0000017
_NT_COMMITMENT_LIMIT = 0xC0000020


def classify_termination(exit_code, timed_out=False, worker_disappeared=False,
                         externally_terminated=False, exit_code_raw=None):
    """Classify an outcome WITHOUT collapsing every nonzero code into FAILED.

    `exit_code` is the signed decimal from Python. `exit_code_raw` is the
    unsigned 32-bit value when the caller can supply it (ctypes GetExitCodeProcess
    reports an unsigned DWORD), which is required to recognise NTSTATUS values
    above 0x7FFFFFFF.
    """
    if worker_disappeared:
        return TERMINATION_WORKER_LOST
    if timed_out:
        return TERMINATION_TIMEOUT
    if externally_terminated:
        return TERMINATION_EXTERNAL

    if exit_code is None:
        # No exit status at all: the child vanished without recording one.
        return TERMINATION_WORKER_LOST if worker_disappeared else TERMINATION_UNKNOWN

    raw = exit_code_raw if exit_code_raw is not None else (
        exit_code & 0xFFFFFFFF)

    if raw == 0 or exit_code == 0:
        return TERMINATION_NORMAL

    # 0xC000013A arrives as a signed -1073741510 or as 3221225786 unsigned.
    if raw == _NT_STATUS_CONTROL_C_EXIT or exit_code in (-1073741510, 3221225786):
        return TERMINATION_C_CONTROL

    if raw in (_NT_ACCESS_VIOLATION, _NT_STACK_BUFFER_OVERRUN,
               _NT_HEAP_CORRUPTION, _NT_IN_PAGE_ERROR):
        return TERMINATION_ACCESS_VIOLATION

    if raw in (_NT_NO_MEMORY, _NT_COMMITMENT_LIMIT):
        return TERMINATION_RESOURCE

    if raw in (_NT_VM_DLL_INIT_FAILED, _NT_DLL_NOT_FOUND):
        return TERMINATION_RESOURCE

    # NB: no POSIX "128 + signal" heuristic here. That convention is a shell
    # artefact and does not hold on Windows, where exit codes 1 and 2 are
    # ordinary program exits. Applying it misclassified the two most common
    # failure codes as "terminated by signal". Anything unrecognised is an
    # explicit nonzero exit.
    return TERMINATION_NONZERO


def termination_receipt(pid, command, exit_code, *, creation_time=None,
                        stdout_path=None, stderr_path=None,
                        started_utc=None, ended_utc=None, timed_out=False,
                        worker_disappeared=False, externally_terminated=False,
                        exit_code_raw=None, extra=None):
    """Canonical PROCESS_TERMINATION_RECEIPT/v1."""
    raw = exit_code_raw if exit_code_raw is not None else (
        None if exit_code is None else exit_code & 0xFFFFFFFF)
    receipt = {
        "schema": "PROCESS_TERMINATION_RECEIPT/v1",
        "schema_version": SCHEMA_VERSION,
        "pid": int(pid),
        "creation_time_utc": creation_time or process_creation_time(pid),
        "identity_key": None,
        "command": list(command) if isinstance(command, (list, tuple)) else command,
        "exit_code_decimal": exit_code,
        "exit_code_hex": None if raw is None else "0x%08X" % raw,
        "termination_class": classify_termination(
            exit_code, timed_out=timed_out,
            worker_disappeared=worker_disappeared,
            externally_terminated=externally_terminated,
            exit_code_raw=raw),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
        "start_utc": started_utc,
        "end_utc": ended_utc or utc_now(),
        "run_id": (extra or {}).get("run_id"),
        "labels": (extra or {}).get("labels", []),
    }
    if receipt["creation_time_utc"]:
        receipt["identity_key"] = "%d|%s" % (receipt["pid"],
                                             receipt["creation_time_utc"])
    return receipt


# ---------------------------------------------------------------------------
# transactional run journal
# ---------------------------------------------------------------------------
JOURNAL_STATES = (
    "PLANNED",
    "PREFLIGHT_PASS",
    "RUNNING",
    "PROGRESS",
    "COMPLETING",
    "COMPLETE",
    "FAILED",
    "INTERRUPTED",
    "UNKNOWN_RECOVERY_REQUIRED",
)

TERMINAL_JOURNAL_STATES = ("COMPLETE", "FAILED", "INTERRUPTED")
# Legal forward transitions. Anything else is a contract violation and is
# rejected rather than silently accepted, because a journal that can jump
# straight to COMPLETE cannot be trusted as evidence.
_JOURNAL_TRANSITIONS = {
    "PLANNED": {"PREFLIGHT_PASS", "FAILED", "INTERRUPTED"},
    "PREFLIGHT_PASS": {"RUNNING", "FAILED", "INTERRUPTED"},
    "RUNNING": {"PROGRESS", "COMPLETING", "FAILED", "INTERRUPTED",
                "UNKNOWN_RECOVERY_REQUIRED"},
    "PROGRESS": {"PROGRESS", "COMPLETING", "FAILED", "INTERRUPTED",
                 "UNKNOWN_RECOVERY_REQUIRED"},
    "COMPLETING": {"COMPLETE", "FAILED", "INTERRUPTED",
                   "UNKNOWN_RECOVERY_REQUIRED"},
    "COMPLETE": set(),
    "FAILED": {"UNKNOWN_RECOVERY_REQUIRED"},
    "INTERRUPTED": {"UNKNOWN_RECOVERY_REQUIRED", "PREFLIGHT_PASS"},
    "UNKNOWN_RECOVERY_REQUIRED": {"PREFLIGHT_PASS", "FAILED"},
}


class JournalTransitionError(RuntimeError):
    pass


class RunJournal:
    """Atomic, append-oriented journal for one expensive operation.

    Every mutation rewrites the whole record atomically, so the on-disk file is
    always a consistent snapshot and never a half-written one.
    """

    def __init__(self, path, run_id=None, operation=None, inputs=None):
        self.path = os.path.abspath(path)
        self.record = {
            "schema": "RUN_JOURNAL/v1",
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id or uuid.uuid4().hex,
            "operation": operation,
            "state": "PLANNED",
            "created_utc": utc_now(),
            "updated_utc": utc_now(),
            "history": [{"state": "PLANNED", "utc": utc_now()}],
            "inputs": inputs or {},
            "owner_identity": None,
            "receipts": [],
            "notes": [],
        }

    # -- persistence ------------------------------------------------------
    def flush(self):
        self.record["updated_utc"] = utc_now()
        return atomic_write_json(self.path, self.record)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        obj = cls.__new__(cls)
        obj.path = os.path.abspath(path)
        obj.record = data
        return obj

    # -- state machine ----------------------------------------------------
    def transition(self, new_state, **fields):
        current = self.record["state"]
        if new_state not in JOURNAL_STATES:
            raise JournalTransitionError("unknown journal state %r" % new_state)
        if new_state not in _JOURNAL_TRANSITIONS.get(current, set()):
            raise JournalTransitionError(
                "illegal journal transition %s -> %s" % (current, new_state))
        self.record["state"] = new_state
        self.record["history"].append({"state": new_state, "utc": utc_now()})
        for key, value in fields.items():
            self.record[key] = value
        self.flush()
        return self.record

    def attach_owner(self, pid, run_id=None):
        self.record["owner_identity"] = process_identity(
            pid, run_id or self.record["run_id"])
        self.flush()
        return self.record["owner_identity"]

    def add_receipt(self, receipt):
        self.record["receipts"].append(receipt)
        self.flush()
        return receipt

    def note(self, text):
        self.record["notes"].append({"utc": utc_now(), "note": text})
        self.flush()

    # -- restart handling -------------------------------------------------
    @staticmethod
    def classify_on_restart(record):
        """Decide what a found journal means at startup.

        A journal found in a non-terminal state means the previous owner died
        mid-flight. That is NOT a pass and NOT a safe resume: it is
        UNKNOWN_RECOVERY_REQUIRED until inputs are re-verified.
        """
        state = record.get("state")
        if state in TERMINAL_JOURNAL_STATES:
            return {"state": state, "resumable": False,
                    "action": "NONE_TERMINAL"}
        return {
            "state": state,
            "resumable": False,
            "action": "RECONCILE_THEN_DECIDE",
            "classification": "UNKNOWN_RECOVERY_REQUIRED",
            "reason": ("journal was found in a non-terminal state, so the owner "
                       "terminated mid-operation; resume safety must be proven "
                       "against the resume-integrity contract before any "
                       "-iterate style restart"),
        }


# ---------------------------------------------------------------------------
# single-writer operation lease
# ---------------------------------------------------------------------------
MUTATING_DOMAINS = (
    "Content", "Saved", "Intermediate", "cook_out", "AssetRegistry",
    "import_output", "DDC", "LibCarla_build", "UE_plugin_build",
)


class LeaseConflict(RuntimeError):
    def __init__(self, message, holder=None):
        super().__init__(message)
        self.holder = holder


class OperationLease:
    """Machine-wide single-writer lease over mutating pipeline domains.

    Acquisition is fail-closed:

    * a live foreign lease denies the request;
    * a lease whose owner PID no longer exists is STALE and must be explicitly
      reconciled by the caller -- it is never silently stolen, because a stale
      lease plus a recycled PID is exactly how two writers end up corrupting
      Content simultaneously.
    """

    def __init__(self, path, operation, domains=None, owner_pid=None,
                 repo=None, project_path=None, user=None):
        self.path = os.path.abspath(path)
        self.operation = operation
        self.domains = sorted(set(domains or MUTATING_DOMAINS))
        self.owner_pid = owner_pid or os.getpid()
        self.repo = repo
        self.project_path = project_path
        self.user = user or os.environ.get("USERNAME")
        self.run_id = uuid.uuid4().hex

    def _read(self):
        if not os.path.isfile(self.path):
            return None
        try:
            with open(self.path, encoding="utf-8") as fh:
                return json.load(fh)
        except (ValueError, OSError):
            # An unreadable lease is treated as present-and-blocking: we cannot
            # prove it is safe to proceed.
            return {"corrupt": True}

    @staticmethod
    def holder_state(holder):
        """Classify an existing lease as LIVE, STALE or UNKNOWN."""
        if not holder or holder.get("corrupt"):
            return "UNKNOWN"
        ident = holder.get("owner_identity") or {}
        pid = ident.get("pid")
        if not pid:
            return "UNKNOWN"
        created_now = process_creation_time(pid)
        if created_now is None:
            return "STALE"
        if ident.get("creation_time_utc") and created_now != ident["creation_time_utc"]:
            # Same PID, different creation time: the PID was recycled, so the
            # recorded owner is definitively gone.
            return "STALE"
        return "LIVE"

    def acquire(self, repo_sha=None, branch=None, heartbeat=None):
        existing = self._read()
        if existing:
            state = self.holder_state(existing)
            if state == "LIVE":
                raise LeaseConflict(
                    "a live operation lease is held: %s (run_id=%s owner=%s)" % (
                        existing.get("operation"), existing.get("run_id"),
                        (existing.get("owner_identity") or {}).get("identity_key")),
                    holder=existing)
            if state in ("STALE", "UNKNOWN"):
                raise LeaseConflict(
                    "a %s lease exists and must be reconciled before proceeding: "
                    "%s" % (state.lower(),
                            json.dumps(existing, default=str)[:400]),
                    holder=existing)

        record = {
            "schema": "CARLA_OPERATION_LEASE/v1",
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "operation": self.operation,
            "owner_identity": process_identity(self.owner_pid, self.run_id),
            "user": self.user,
            "repo": self.repo,
            "repo_sha": repo_sha,
            "branch": branch,
            "project_path": self.project_path,
            "mutating_domains": self.domains,
            "start_utc": utc_now(),
            "heartbeat_utc": heartbeat or utc_now(),
        }
        atomic_write_json(self.path, record)
        return record

    def heartbeat(self):
        record = self._read()
        if not record or record.get("run_id") != self.run_id:
            raise LeaseConflict("lease is no longer owned by this run_id")
        record["heartbeat_utc"] = utc_now()
        atomic_write_json(self.path, record)
        return record

    def release(self, outcome="COMPLETE"):
        record = self._read()
        if not record or record.get("run_id") != self.run_id:
            return None
        record["released_utc"] = utc_now()
        record["outcome"] = outcome
        atomic_write_json(self.path, record)
        os.unlink(self.path)
        return record

    @staticmethod
    def reconcile(path, acknowledged_by_run_id):
        """Explicitly clear a STALE lease. Deliberately a separate operation."""
        lease = OperationLease.__new__(OperationLease)
        lease.path = os.path.abspath(path)
        record = lease._read()
        if not record:
            return {"action": "NONE", "reason": "no lease present"}
        state = OperationLease.holder_state(record)
        if state == "LIVE":
            raise LeaseConflict(
                "refusing to reconcile a LIVE lease owned by %s" % (
                    (record.get("owner_identity") or {}).get("identity_key"),),
                holder=record)
        tomb = {
            "schema": "CARLA_OPERATION_LEASE_RECONCILIATION/v1",
            "schema_version": SCHEMA_VERSION,
            "reconciled_utc": utc_now(),
            "stale_record": record,
            "prior_state": state,
            "acknowledged_by_run_id": acknowledged_by_run_id,
        }
        atomic_write_json(path + ".reconciled.json", tomb)
        os.unlink(path)
        return {"action": "RECONCILED", "prior_state": state,
                "tombstone": path + ".reconciled.json"}
