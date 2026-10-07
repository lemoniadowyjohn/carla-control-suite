"""Machine-wide CARLA single-writer control plane.

Authority model
---------------
The OS-level primitive is the authority. The JSON lease is evidence only.

Concretely: a Windows named mutex in the Global namespace
(``Global\\CARLA_Mutating_Operation_Lock``) is acquired with
``WaitForSingleObject``. Because the mutex is owned by the *handle* and dies
with the process, a crashed owner releases it automatically and the next waiter
observes ``WAIT_ABANDONED`` rather than a permanent deadlock. A JSON file alone
cannot provide this: two processes can both read "no lease", both decide to
write, and both proceed.

The lease record deliberately lives OUTSIDE Temp, scratch, worktrees and
session directories, in ``%ProgramData%\\CARLA\\control_plane``, because the
whole point is that it is shared by every session on the machine.

Why a machine-wide single writer: the NoSig incident proved two autonomous
sessions could independently drive ``-run=ImportAssets`` against the same
Content tree, the same ``importsetting.json`` and the same DDC. Until UE4.26
DDC write concurrency is explicitly qualified, conservative exclusivity is the
only defensible default.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import atomic_write_json, utc_now  # noqa: E402

SCHEMA_VERSION = 1

# Durable, machine-wide, not session-local.
# Env overrides exist so that tests can exercise the real code paths in
# isolation instead of contending with the production Global mutex.
CONTROL_PLANE_DIR = os.environ.get(
    "CARLA_CONTROL_PLANE_DIR",
    os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "CARLA",
                 "control_plane"))
LEASE_PATH = os.path.join(CONTROL_PLANE_DIR, "mutation_lease.json")
LOG_PATH = os.path.join(CONTROL_PLANE_DIR, "acquisition_log.jsonl")
MUTEX_NAME = os.environ.get(
    "CARLA_MUTEX_NAME", r"Global\CARLA_Mutating_Operation_Lock")

# In-process lease registry.
#
# A Windows mutex is RECURSIVE: WaitForSingleObject from the thread that already
# owns it returns WAIT_OBJECT_0 and merely bumps the recursion count. Without
# this registry a single session could "acquire" several leases from one process
# and appear to be the exclusive owner of several domains at once. Acquisition
# is therefore refused outright when this process already holds a lease.
_PROCESS_HELD = {}

WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102

# ---------------------------------------------------------------------------
# mutation domains (batch section 3)
# ---------------------------------------------------------------------------
DOMAIN_UNREAL_CONTENT = "DOMAIN_UNREAL_CONTENT"
DOMAIN_IMPORT_SETTINGS = "DOMAIN_IMPORT_SETTINGS"
DOMAIN_DDC = "DOMAIN_DDC"
DOMAIN_COOK_OUTPUT = "DOMAIN_COOK_OUTPUT"
DOMAIN_SAVED_INTERMEDIATE = "DOMAIN_SAVED_INTERMEDIATE"
DOMAIN_UE_BUILD_OUTPUT = "DOMAIN_UE_BUILD_OUTPUT"
DOMAIN_CARLA_PLUGIN_BINARIES = "DOMAIN_CARLA_PLUGIN_BINARIES"
DOMAIN_SOURCE_WORKTREE = "DOMAIN_SOURCE_WORKTREE"

ALL_DOMAINS = (
    DOMAIN_UNREAL_CONTENT, DOMAIN_IMPORT_SETTINGS, DOMAIN_DDC,
    DOMAIN_COOK_OUTPUT, DOMAIN_SAVED_INTERMEDIATE, DOMAIN_UE_BUILD_OUTPUT,
    DOMAIN_CARLA_PLUGIN_BINARIES, DOMAIN_SOURCE_WORKTREE,
)

# Which domains each operation class writes. Safety is never inferred from the
# operation NAME: RUNTIME reads Content but writes Saved/logs and DDC.
OPERATION_DOMAINS = {
    "IMPORT": [DOMAIN_UNREAL_CONTENT, DOMAIN_IMPORT_SETTINGS, DOMAIN_DDC,
               DOMAIN_SAVED_INTERMEDIATE],
    "COOK": [DOMAIN_COOK_OUTPUT, DOMAIN_SAVED_INTERMEDIATE, DOMAIN_DDC],
    "PREPARE_ASSETS": [DOMAIN_UNREAL_CONTENT, DOMAIN_SAVED_INTERMEDIATE],
    "MOVE_ASSETS": [DOMAIN_UNREAL_CONTENT, DOMAIN_SAVED_INTERMEDIATE],
    "LOAD_MATERIALS": [DOMAIN_DDC, DOMAIN_SAVED_INTERMEDIATE],
    "RESAVE": [DOMAIN_UNREAL_CONTENT, DOMAIN_SAVED_INTERMEDIATE],
    "BUILD": [DOMAIN_UE_BUILD_OUTPUT, DOMAIN_CARLA_PLUGIN_BINARIES,
              DOMAIN_SAVED_INTERMEDIATE],
    "UE_BUILD": [DOMAIN_UE_BUILD_OUTPUT, DOMAIN_CARLA_PLUGIN_BINARIES,
                 DOMAIN_SAVED_INTERMEDIATE],
    "RUNTIME": [DOMAIN_SAVED_INTERMEDIATE, DOMAIN_DDC],
    "NAV_BUILD": [DOMAIN_UNREAL_CONTENT, DOMAIN_SAVED_INTERMEDIATE],
    "AUDIT": [],
    "UNKNOWN": list(ALL_DOMAINS),
}

# Pairs that are never safe to run concurrently on this machine.
EXCLUSIVE_OPERATION_PAIRS = {
    frozenset({"IMPORT", "IMPORT"}),
    frozenset({"IMPORT", "COOK"}),
    frozenset({"IMPORT", "BUILD"}),
    frozenset({"IMPORT", "UE_BUILD"}),
    frozenset({"COOK", "COOK"}),
    frozenset({"COOK", "BUILD"}),
    frozenset({"BUILD", "BUILD"}),
    frozenset({"BUILD", "UE_BUILD"}),
    frozenset({"RUNTIME", "BUILD"}),
    frozenset({"RUNTIME", "UE_BUILD"}),
}

# DDC concurrency is denied until qualified (batch section 10).
DDC_MUTATION_CONCURRENCY = "DENIED"
DDC_POLICY_REASON = ("UE4.26 DerivedDataBackendGraph write concurrency has not "
                     "been explicitly qualified on this machine, so two jobs "
                     "may not write the shared DDC simultaneously.")


# ---------------------------------------------------------------------------
# OS primitive
# ---------------------------------------------------------------------------
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
_kernel32.CreateMutexW.restype = wt.HANDLE
_kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_kernel32.WaitForSingleObject.restype = wt.DWORD
_kernel32.ReleaseMutex.argtypes = [wt.HANDLE]
_kernel32.ReleaseMutex.restype = wt.BOOL
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_kernel32.CloseHandle.restype = wt.BOOL


class MutexHandle:
    """OS-level exclusive primitive, held for the lifetime of the object."""

    def __init__(self):
        self.handle = None
        self.abandoned = False

    def try_acquire(self, name=MUTEX_NAME, timeout_ms=0):
        self.handle = _kernel32.CreateMutexW(None, False, name)
        if not self.handle:
            raise OSError("CreateMutexW failed: %d" % ctypes.get_last_error())
        result = _kernel32.WaitForSingleObject(self.handle, timeout_ms)
        if result == WAIT_OBJECT_0:
            return "ACQUIRED"
        if result == WAIT_ABANDONED:
            # The previous owner died while holding it. We now own it, but the
            # abandoned state is evidence of an unclean shutdown.
            self.abandoned = True
            return "ACQUIRED_ABANDONED"
        if result == WAIT_TIMEOUT:
            self.release()
            return "DENIED_CONFLICT"
        self.release()
        return "DENIED_ERROR_0x%08X" % result

    def release(self):
        if self.handle:
            try:
                _kernel32.ReleaseMutex(self.handle)
            finally:
                _kernel32.CloseHandle(self.handle)
                self.handle = None
        return True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------
def process_creation_time(pid):
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" "
         "-ErrorAction SilentlyContinue; "
         "if($p){([datetime]$p.CreationDate).ToUniversalTime().ToString('o')}" % pid],
        capture_output=True, text=True, timeout=120)
    return p.stdout.strip() or None


def identity_key(pid):
    created = process_creation_time(pid)
    return None if created is None else "%d|%s" % (pid, created)


# ---------------------------------------------------------------------------
# operation fingerprint (batch section 7)
# ---------------------------------------------------------------------------
def operation_fingerprint(operation, engine_root, project_root, content_root,
                          package_identity=None, import_settings=None,
                          output_root=None):
    """Normalized identity of an operation.

    Two sessions attempting the same import produce the same fingerprint, which
    is what makes the NoSig incident preventable.
    """
    def norm(p):
        return os.path.normcase(os.path.abspath(p)).replace("/", "\\") if p else None

    payload = {
        "operation": (operation or "").upper(),
        "engine_root": norm(engine_root),
        "project_root": norm(project_root),
        "content_root": norm(content_root),
        "package_identity": (package_identity or "").strip().lower(),
        "import_settings_sha256": _sha(import_settings),
        "output_root": norm(output_root),
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    payload["fingerprint"] = hashlib.sha256(blob).hexdigest()
    return payload


def _sha(path):
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# lease
# ---------------------------------------------------------------------------
class ArbitrationError(RuntimeError):
    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class SingleWriterLease:
    def __init__(self, operation, session_id, engine_root=None,
                 project_root=None, content_root=None, domains=None,
                 package_identity=None, import_settings=None, output_root=None,
                 root_pid=None, read_only=False):
        self.operation = (operation or "UNKNOWN").upper()
        self.session_id = session_id
        self.engine_root = engine_root
        self.project_root = project_root
        self.content_root = content_root
        self.domains = list(domains or OPERATION_DOMAINS.get(
            self.operation, OPERATION_DOMAINS["UNKNOWN"]))
        self.read_only = read_only
        self.root_pid = root_pid or os.getpid()
        self.run_id = uuid.uuid4().hex
        self.mutex = MutexHandle()
        self.fingerprint = operation_fingerprint(
            self.operation, engine_root, project_root, content_root,
            package_identity, import_settings, output_root)
        self.status = None

    # -- lease IO ---------------------------------------------------------
    @staticmethod
    def _read():
        if not os.path.isfile(LEASE_PATH):
            return None
        try:
            with open(LEASE_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except (ValueError, OSError):
            return {"corrupt": True}

    @staticmethod
    def holder_state(holder):
        """LIVE / STALE / UNKNOWN based on identity, never PID alone."""
        if not holder or holder.get("corrupt"):
            return "UNKNOWN"
        pid = holder.get("root_pid")
        if not pid:
            return "UNKNOWN"
        created = process_creation_time(pid)
        if created is None:
            return "STALE"
        recorded = holder.get("root_creation_time")
        if recorded and created != recorded:
            return "STALE"  # PID recycled: the recorded owner is gone
        if holder.get("status") in ("RELEASING", "STALE_RECONCILIATION_REQUIRED"):
            return "STALE"
        return "LIVE"

    @staticmethod
    def _log(event):
        os.makedirs(CONTROL_PLANE_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"utc": utc_now(), **event}) + "\n")

    # -- acquisition ------------------------------------------------------
    def acquire(self):
        if self.read_only:
            raise ArbitrationError(
                "READ_ONLY_SESSION_MODE_FORBIDS_MUTATION",
                {"session_id": self.session_id})
        if not self.domains:
            raise ArbitrationError("READ_ONLY_OPERATION_NO_DOMAINS",
                                   {"operation": self.operation})

        # Windows mutexes are recursive, so a same-process re-acquire would
        # silently succeed. Refuse it explicitly instead.
        held = _PROCESS_HELD.get(os.getpid())
        if held is not None:
            if held["fingerprint"] == self.fingerprint["fingerprint"]:
                raise ArbitrationError("DUPLICATE_OPERATION_ALREADY_RUNNING",
                                       {"held_by_this_process": held})
            raise ArbitrationError("PROCESS_ALREADY_HOLDS_LEASE",
                                   {"held": held, "requested": self.operation})

        verdict = self.mutex.try_acquire()
        if verdict.startswith("DENIED"):
            holder = self._read()
            self._log({"event": "DENIED_CONFLICT", "session_id": self.session_id,
                       "operation": self.operation,
                       "holder": holder})
            if holder:
                same = holder.get("operation_fingerprint", {}).get("fingerprint") \
                    == self.fingerprint["fingerprint"]
                if same:
                    raise ArbitrationError("DUPLICATE_OPERATION_ALREADY_RUNNING",
                                           {"holder": holder})
                if frozenset({holder.get("operation"), self.operation}) in \
                        EXCLUSIVE_OPERATION_PAIRS:
                    raise ArbitrationError(
                        "OPERATION_CLASS_CONFLICT",
                        {"holder_operation": holder.get("operation"),
                         "requested": self.operation})
            raise ArbitrationError("HELD_BY_LIVE_OWNER",
                                   {"holder": holder})

        # We hold the OS primitive. Now reconcile the JSON evidence.
        existing = self._read()
        prior_state = None
        if existing:
            prior_state = self.holder_state(existing)
            if prior_state == "LIVE":
                # Should be impossible while holding the mutex; treat as a hard
                # error rather than overwriting a live record.
                self.mutex.release()
                raise ArbitrationError("LEASE_RECORD_LIVE_BUT_MUTEX_FREE",
                                       {"holder": existing})
            if prior_state in ("STALE", "UNKNOWN"):
                atomic_write_json(LEASE_PATH + ".reconciled.json", {
                    "schema": "CARLA_LEASE_RECONCILIATION/v1",
                    "schema_version": SCHEMA_VERSION,
                    "reconciled_utc": utc_now(),
                    "prior_state": prior_state,
                    "prior_record": existing,
                })

        record = {
            "schema": "CARLA_MUTATION_LEASE/v1",
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "operation": self.operation,
            "root_pid": self.root_pid,
            "root_creation_time": process_creation_time(self.root_pid),
            "parent_pid": os.getppid(),
            "project_root": self.project_root,
            "engine_root": self.engine_root,
            "content_root": self.content_root,
            "domains": self.domains,
            "operation_fingerprint": self.fingerprint,
            "start_utc": utc_now(),
            "heartbeat_utc": utc_now(),
            "status": "ACQUIRED",
            "mutex_name": MUTEX_NAME,
            "mutex_verdict": verdict,
            "ddc_mutation_concurrency": DDC_MUTATION_CONCURRENCY,
            "prior_lease_state": prior_state,
        }
        atomic_write_json(LEASE_PATH, record)
        self.status = "ACQUIRED"
        _PROCESS_HELD[os.getpid()] = {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "operation": self.operation,
            "fingerprint": self.fingerprint["fingerprint"],
            "acquired_utc": record["start_utc"],
        }
        self._log({"event": "ACQUIRED", "run_id": self.run_id,
                   "session_id": self.session_id, "operation": self.operation,
                   "mutex_verdict": verdict, "abandoned": self.mutex.abandoned})
        return record

    def heartbeat(self):
        record = self._read()
        if not record or record.get("run_id") != self.run_id:
            raise ArbitrationError("LEASE_LOST", {"path": LEASE_PATH})
        record["heartbeat_utc"] = utc_now()
        record["status"] = "RUNNING"
        atomic_write_json(LEASE_PATH, record)
        return record

    def release(self, outcome="COMPLETE"):
        record = self._read()
        if record and record.get("run_id") == self.run_id:
            record["status"] = "RELEASED"
            record["released_utc"] = utc_now()
            record["outcome"] = outcome
            atomic_write_json(LEASE_PATH, record)
            os.unlink(LEASE_PATH)
        _PROCESS_HELD.pop(os.getpid(), None)
        self.mutex.release()
        self._log({"event": "RELEASED", "run_id": self.run_id,
                   "session_id": self.session_id, "outcome": outcome})
        return outcome

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release(outcome="CONTEXT_EXIT")
        return False

    @staticmethod
    def reconcile_stale(reason, acknowledged_by_session):
        """Explicit stale-lease reconciliation. Refuses a LIVE lease."""
        holder = SingleWriterLease._read()
        if not holder:
            return {"action": "NONE", "reason": "no lease present"}
        state = SingleWriterLease.holder_state(holder)
        if state == "LIVE":
            raise ArbitrationError("REFUSING_TO_RECONCILE_LIVE_LEASE",
                                   {"holder": holder})
        atomic_write_json(LEASE_PATH + ".reconciled.json", {
            "schema": "CARLA_LEASE_RECONCILIATION/v1",
            "schema_version": SCHEMA_VERSION,
            "reconciled_utc": utc_now(),
            "prior_state": state,
            "prior_record": holder,
            "reason": reason,
            "acknowledged_by_session": acknowledged_by_session,
        })
        os.unlink(LEASE_PATH)
        return {"action": "RECONCILED", "prior_state": state}


# ---------------------------------------------------------------------------
# run-scoped import settings (batch section 8)
# ---------------------------------------------------------------------------
def run_scoped_settings_path(staging_root, run_id, filename="importsetting.json"):
    """Per-run immutable ImportSettings path.

    The historical defect is a single shared ``importsetting.json`` that any
    second run can overwrite while the first run's command line still points at
    it. Scoping by run_id removes the race.
    """
    d = os.path.join(staging_root, run_id)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, filename)


def run_scoped_staging(staging_root, run_id):
    """Temporary generation workspace scoped to one run."""
    d = os.path.join(staging_root, "RUN_STAGING", run_id)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# mutation preflight (batch section 15)
# ---------------------------------------------------------------------------
GOVERNED_COMMANDS = (
    "Import.py", "UE4Editor-Cmd.exe", "UE4Editor.exe", "Build.bat",
    "UE4Editor-Cmd", "RecastStaticMeshGenerator", "CarlaUE4",
)


def mutation_preflight(command_line, session_id, read_only=False,
                       operation=None):
    """Gate a mutating command. Deny unless a lease is held.

    This is the enforcement point that makes the rule programmatic rather than
    something an agent has to remember.
    """
    exe = os.path.basename((command_line or "").split()[0]) if command_line else ""
    governed = any(g.lower() in (command_line or "").lower()
                   for g in ("Import.py", "UE4Editor-Cmd", "UE4Editor.exe",
                              "Build.bat", "-run=cook", "-run=ImportAssets",
                              "RecastStaticMeshGenerator"))
    result = {
        "schema": "MUTATION_PREFLIGHT/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "command_line": command_line,
        "session_id": session_id,
        "governed_command": governed,
        "read_only_session": read_only,
        "lease": None,
        "verdict": "ALLOW",
        "reason": "not a governed mutating command",
    }
    if not governed:
        return result

    if read_only:
        result.update({"verdict": "DENY", "reason": "READ_ONLY_SESSION_MODE",
                       "gate_effect": "DENY"})
        return result

    holder = SingleWriterLease._read()
    result["lease"] = holder
    state = SingleWriterLease.holder_state(holder)
    result["lease_state"] = state
    if not holder or state != "LIVE" or holder.get("session_id") != session_id:
        result.update({
            "verdict": "DENY",
            "reason": ("no live lease held by this session; a mutating command "
                       "may not run unguarded"),
            "gate_effect": "DENY",
        })
        return result

    result.update({"verdict": "ALLOW", "reason": "live lease held by this session",
                   "run_id": holder.get("run_id")})
    return result


# ---------------------------------------------------------------------------
# ungoverned mutator detection (batch section 16)
# ---------------------------------------------------------------------------
def detect_ungoverned_mutators(inventory, session_id):
    """A mutating process with no matching live lease is an ungoverned mutator."""
    holder = SingleWriterLease._read()
    state = SingleWriterLease.holder_state(holder)
    owned_pid = holder.get("root_pid") if state == "LIVE" else None

    ungoverned = []
    for p in inventory.get("mutators", []):
        if p.get("pid") == owned_pid:
            continue
        ungoverned.append({
            "identity_key": p.get("identity_key"),
            "pid": p.get("pid"),
            "name": p.get("name"),
            "operation_class": p.get("operation_class"),
            "command_line": p.get("command_line"),
        })

    return {
        "schema": "UNGOVERNED_MUTATOR_DETECTION/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "lease_state": state,
        "lease_owner_pid": owned_pid,
        "lease_owner_session": (holder or {}).get("session_id"),
        "mutator_count": len(inventory.get("mutators", [])),
        "ungoverned": ungoverned,
        "UNGOVERNED_MUTATOR_DETECTED": bool(ungoverned),
        "new_governed_mutation_allowed": not ungoverned and state != "LIVE",
        "action": "ALERT_AND_BLOCK_NEW_MUTATIONS__DO_NOT_KILL",
    }


# ---------------------------------------------------------------------------
# configuration snapshot (batch section 19)
# ---------------------------------------------------------------------------
# Paths under the CARLA source-probe checkout. These were previously
# hardcoded to a single machine's probe root, which made the published
# control plane unusable anywhere else and silently hashed nothing useful
# elsewhere. They are now resolved from CARLA_SOURCE_PROBE_ROOT; when
# that is unset the entries are reported as UNCONFIGURED instead of hashing
# a path that does not exist.
CARLA_SOURCE_PROBE_ROOT = os.environ.get("CARLA_SOURCE_PROBE_ROOT", "")


def _probe_path(relative):
    if not CARLA_SOURCE_PROBE_ROOT:
        return None
    return os.path.join(CARLA_SOURCE_PROBE_ROOT,
                        *relative.split("/"))


CONFIG_FILES = {
    "DefaultEngine.ini": _probe_path(
        "Unreal/CarlaUE4/Config/DefaultEngine.ini"),
    "DefaultGame.ini": _probe_path(
        "Unreal/CarlaUE4/Config/DefaultGame.ini"),
    "Import.py": _probe_path("Util/BuildTools/Import.py"),
}


def configuration_snapshot():
    files = {}
    for name, path in CONFIG_FILES.items():
        if path is None:
            files[name] = "UNCONFIGURED_SET_CARLA_SOURCE_PROBE_ROOT"
        elif not os.path.isfile(path):
            files[name] = "MISSING"
        else:
            files[name] = _sha(path)
    return {
        "schema": "OPERATION_CONFIGURATION_SNAPSHOT/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "carla_source_probe_root": CARLA_SOURCE_PROBE_ROOT or "UNSET",
        "files": files,
    }


def compare_configuration(before, after):
    changed = []
    for name, sha in (before or {}).get("files", {}).items():
        now = (after or {}).get("files", {}).get(name)
        if now != sha:
            changed.append({"file": name, "before": sha, "after": now})
    return {
        "CONFIGURATION_MUTATED_DURING_RUN": bool(changed),
        "changed": changed,
        "run_authoritative": not changed,
    }