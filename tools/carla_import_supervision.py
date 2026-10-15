"""CARLA import process supervision: exit-status classification, state machine,
receipts, and a storage capacity gate.

This module exists because the previous 16.76 h import ended with the wrapper
still resident at 0.015 s CPU and no terminal record, which made a dead run look
alive. Two specific defects are addressed:

1. Windows console control-event exit statuses were unclassified. The prior run
   exited with 3221225786 == 0xC000013A == STATUS_CONTROL_C_EXIT and was
   indistinguishable from a crash or a plain failure. :func:`classify_exit_status`
   maps it to EXTERNALLY_INTERRUPTED.

2. There was no durable terminal receipt. :class:`ImportState` writes state
   atomically, and :func:`write_receipt` always emits a receipt, including on the
   interrupt path.

Design constraints:
  * The interactive editor must never be treated as the import child. Role is
    detected from the executable name: UE4Editor-Cmd.exe and UE4Editor.exe
    launched with ``-run=`` are commandlet invocations; a plain UE4Editor.exe is
    interactive.
  * No sleep-based synchronisation and no polling loops in this module; it only
    classifies and records.
  * Pure stdlib, no Unreal dependency, so it is unit testable on any host.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Exit status classification
# ---------------------------------------------------------------------------
# Windows NTSTATUS values that a child process can return.
NTSTATUS = {
    0xC000013A: ("STATUS_CONTROL_C_EXIT",
                 "terminated by console control event (Ctrl+C / Ctrl+Break)"),
    0xC000003A: ("STATUS_CONTROL_C_BREAK",
                 "terminated by Ctrl+Break"),
    0xC0000005: ("STATUS_ACCESS_VIOLATION", "access violation (crash)"),
    0xC0000135: ("STATUS_DLL_NOT_FOUND", "DLL not found"),
    0xC0000139: ("STATUS_ENTRYPOINT_NOT_FOUND", "entry point not found"),
    0xC0000142: ("STATUS_DLL_INIT_FAILED", "DLL initialization failed"),
    0xC0000006: ("STATUS_IN_PAGE_ERROR", "in-page error"),
    0xC0000374: ("STATUS_HEAP_CORRUPTION", "heap corruption (crash)"),
    0xC0000409: ("STATUS_STACK_BUFFER_OVERRUN", "stack buffer overrun"),
    0x80000003: ("STATUS_BREAKPOINT", "breakpoint"),
}

# Terminal classifications.
EXTERNALLY_INTERRUPTED = "EXTERNALLY_INTERRUPTED"
CRASH = "CRASH"
NONZERO_EXIT = "COMMANDLET_NONZERO_EXIT"
CLEAN_EXIT = "CLEAN_EXIT"


# Single source of truth. The crash set is derived from NTSTATUS rather than
# re-listed, because an earlier version kept two lists and they silently drifted:
# DLL_NOT_FOUND / ENTRYPOINT_NOT_FOUND / DLL_INIT_FAILED were documented as
# faults but not classified as crashes.
INTERRUPT_STATUSES = frozenset({0xC000013A, 0xC000003A})
CRASH_STATUSES = frozenset(
    code for code in NTSTATUS
    if code not in INTERRUPT_STATUSES and NTSTATUS[code][0] != "STATUS_BREAKPOINT"
)


def classify_exit_status(returncode: int | None) -> dict[str, Any]:
    """Classify a child return code.

    A control-event exit is reported as EXTERNALLY_INTERRUPTED and explicitly
    NOT as a crash, and NOT as success. This is the classification the previous
    run required and did not have.
    """
    if returncode is None:
        return {"returncode": None, "classification": "UNKNOWN_NO_RETURN_CODE",
                "ntstatus_name": None, "detail": "child produced no return code",
                "is_crash": False, "is_success": False, "is_interrupted": False}

    code = returncode & 0xFFFFFFFF
    # POSIX-style small codes from CreateProcess through Python
    if 0 <= returncode < 0x80000000:
        if returncode == 0:
            return {"returncode": 0, "classification": CLEAN_EXIT, "ntstatus_name": None,
                    "detail": "clean exit", "is_crash": False, "is_success": True,
                    "is_interrupted": False}
        return {"returncode": returncode, "classification": NONZERO_EXIT,
                "ntstatus_name": None,
                "detail": "nonzero exit code %d" % returncode,
                "is_crash": False, "is_success": False, "is_interrupted": False}

    name, detail = NTSTATUS.get(code, ("UNKNOWN_NTSTATUS", "unrecognised NTSTATUS"))
    interrupted = code in INTERRUPT_STATUSES
    is_crash = code in CRASH_STATUSES
    return {
        "returncode": returncode,
        "returncode_hex": "0x%08X" % code,
        "classification": EXTERNALLY_INTERRUPTED if interrupted
        else (CRASH if is_crash else NONZERO_EXIT),
        "ntstatus_name": name,
        "detail": detail,
        "is_crash": is_crash,
        "is_success": False,
        "is_interrupted": interrupted,
    }


# ---------------------------------------------------------------------------
# Process role detection
# ---------------------------------------------------------------------------
INTERACTIVE_EXE = "UE4Editor.exe"
COMMANDLET_EXE = "UE4Editor-Cmd.exe"


def detect_process_role(executable: str, args: list[str] | None = None) -> dict:
    """Decide whether an invocation is a commandlet or the interactive editor.

    The prior wrapper invoked ``UE4Editor.exe -run=ImportAssets``, so the absence
    of a UE4Editor-Cmd.exe child was never evidence of anything. Role must be
    decided from the executable plus the presence of ``-run=``.
    """
    args = args or []
    exe_name = os.path.basename(executable)
    has_run = any(a.startswith("-run=") for a in args)
    is_cmd_exe = exe_name.lower() == COMMANDLET_EXE.lower()
    is_editor_exe = exe_name.lower() == INTERACTIVE_EXE.lower()
    if has_run or is_cmd_exe:
        role = "COMMANDLET"
    elif is_editor_exe:
        role = "INTERACTIVE_EDITOR"
    else:
        role = "UNKNOWN"
    return {
        "executable": executable,
        "executable_name": exe_name,
        "args": list(args),
        "has_run_switch": has_run,
        "role": role,
        "is_commandlet": role == "COMMANDLET",
        "rationale": ("-run= present -> commandlet" if has_run else
                      "UE4Editor-Cmd.exe -> commandlet" if is_cmd_exe else
                      "plain UE4Editor.exe -> interactive editor"),
        "never_use_interactive_as_import_evidence": role == "INTERACTIVE_EDITOR",
    }


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
STATES = ("NOT_STARTED", "STARTING", "RUNNING", "INTERRUPTED", "CHILD_FAILED",
          "VALIDATING_OUTPUT", "PASS", "FAIL")

# State-name constants, exported so callers compare against symbols rather than
# re-typing string literals (which is how the `is not 'tiles'` class of defect
# arises in the first place).
NOT_STARTED = "NOT_STARTED"
STARTING = "STARTING"
RUNNING = "RUNNING"
INTERRUPTED = "INTERRUPTED"
CHILD_FAILED = "CHILD_FAILED"
VALIDATING_OUTPUT = "VALIDATING_OUTPUT"
PASS = "PASS"
FAIL = "FAIL"

_ALLOWED = {
    "NOT_STARTED": {"STARTING"},
    "STARTING": {"RUNNING", "FAIL", "INTERRUPTED", "CHILD_FAILED"},
    "RUNNING": {"INTERRUPTED", "CHILD_FAILED", "VALIDATING_OUTPUT", "PASS", "FAIL"},
    "INTERRUPTED": set(),          # terminal
    "CHILD_FAILED": set(),         # terminal
    "VALIDATING_OUTPUT": {"PASS", "FAIL"},
    "PASS": set(),
    "FAIL": set(),
}


class IllegalTransition(ValueError):
    pass


def validate_transition(current: str, nxt: str) -> None:
    if nxt not in STATES:
        raise IllegalTransition("unknown state %r" % nxt)
    if nxt not in _ALLOWED.get(current, set()):
        raise IllegalTransition("illegal transition %s -> %s" % (current, nxt))


@dataclass
class ImportState:
    """Durable import state. Writes are atomic so a reader never sees a partial file."""
    state_path: str
    run_id: str = ""
    parent_pid: int | None = None
    child_pid: int | None = None
    executable: str = ""
    current_stage: str = ""
    current_tile: str = ""
    last_progress_utc: str = ""
    return_code: int | None = None
    terminal_reason: str = ""
    log_path: str = ""
    stderr_path: str = ""
    state: str = "NOT_STARTED"
    history: list = field(default_factory=list)

    def _utc(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def transition(self, nxt: str, **fields: Any) -> "ImportState":
        validate_transition(self.state, nxt)
        self.history.append({"from": self.state, "to": nxt, "utc": self._utc()})
        self.state = nxt
        self.last_progress_utc = self._utc()
        for k, v in fields.items():
            setattr(self, k, v)
        self.flush()
        return self

    def flush(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)) or ".",
                    exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2, sort_keys=True)
        os.replace(tmp, self.state_path)      # atomic on NTFS

    def is_terminal(self) -> bool:
        return self.state in ("INTERRUPTED", "CHILD_FAILED", "PASS", "FAIL")


# ---------------------------------------------------------------------------
# Storage capacity gate
# ---------------------------------------------------------------------------
@dataclass
class StorageGate:
    """Fail before expensive work if free space is insufficient.

    Thresholds are data, not magic numbers: they must be supplied by the caller
    from measured prior-run output sizes. No default is invented here.
    """
    minimum_free_gb: dict = field(default_factory=dict)
    volumes: dict = field(default_factory=dict)

    def measure(self) -> dict:
        rows = {}
        for letter in sorted({v[0].upper() for v in self.minimum_free_gb}):
            root = letter + ":\\"
            if not os.path.isdir(root):
                rows[letter] = {"error": "volume not present"}
                continue
            u = shutil.disk_usage(root)
            rows[letter] = {"total_gb": round(u.total / 1024 ** 3, 2),
                            "free_gb": round(u.free / 1024 ** 3, 2)}
        self.volumes = rows
        return rows

    def evaluate(self) -> dict:
        self.measure()
        failures, ok = [], {}
        for letter, need in self.minimum_free_gb.items():
            v = self.volumes.get(letter, {})
            free = v.get("free_gb")
            if free is None:
                failures.append({"volume": letter, "reason": "unmeasurable",
                                 "required_gb": need})
                continue
            if free < need:
                failures.append({"volume": letter, "required_gb": need,
                                 "actual_free_gb": free,
                                 "shortfall_gb": round(need - free, 2)})
            else:
                ok[letter] = {"required_gb": need, "actual_free_gb": free}
        return {"pass": not failures, "satisfied": ok, "failures": failures,
                "thresholds_supplied_by_caller": True,
                "policy": ("No default thresholds are invented. The caller must "
                           "derive them from measured prior output, DDC and temp "
                           "usage, or the gate refuses to invent a number.")}


# ---------------------------------------------------------------------------
# Supervised invocation
# ---------------------------------------------------------------------------
def write_receipt(path: str, payload: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)
    return path


def run_supervised(command: list[str], *, state: ImportState,
                   cwd: str | None = None, timeout_sec: int | None = None,
                   stdout_path: str | None = None,
                   stderr_path: str | None = None) -> dict:
    """Run one child, recording role, exit classification and a terminal receipt.

    Always produces a receipt, including on KeyboardInterrupt. Never kills
    unrelated UE4Editor sessions: it only manages the process it started.
    """
    role = detect_process_role(command[0], command[1:])
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    t0 = time.time()
    if state.state == "STARTING":
        state.transition("RUNNING", executable=command[0])
    else:
        state.flush()

    out_fh = open(stdout_path, "w", encoding="utf-8") if stdout_path else None
    err_fh = open(stderr_path, "w", encoding="utf-8") if stderr_path else None
    proc = None
    classification = None
    detail = ""
    try:
        proc = subprocess.Popen(command, cwd=cwd, stdout=out_fh or subprocess.PIPE,
                                stderr=err_fh or subprocess.PIPE)
        state.child_pid = proc.pid
        state.flush()
        stdout, stderr = proc.communicate(timeout=timeout_sec)
        rc = proc.returncode
        classification = classify_exit_status(rc)
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        detail = stderr[-4000:] if stderr else ""
    except KeyboardInterrupt:
        classification = {
            "returncode": None, "classification": EXTERNALLY_INTERRUPTED,
            "ntstatus_name": "PYTHON_KEYBOARDINTERRUPT",
            "detail": "KeyboardInterrupt in the supervising wrapper",
            "is_crash": False, "is_success": False, "is_interrupted": True}
        detail = "KeyboardInterrupt: child left running; state recorded INTERRUPTED"
    except subprocess.TimeoutExpired:
        classification = {
            "returncode": None, "classification": "CHILD_TIMEOUT",
            "ntstatus_name": None, "detail": "timeout after %ss" % timeout_sec,
            "is_crash": False, "is_success": False, "is_interrupted": False}
    finally:
        if out_fh:
            out_fh.close()
        if err_fh:
            err_fh.close()

    ended = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    receipt = {
        "schema": "commandlet_execution_receipt/v1",
        "run_id": state.run_id,
        "command": command,
        "process_role": role,
        "parent_pid": state.parent_pid,
        "child_pid": proc.pid if proc else None,
        "start_utc": started,
        "end_utc": ended,
        "duration_seconds": round(time.time() - t0, 3),
        "child_return_code": proc.returncode if proc else None,
        "termination_classification": classification,
        "terminal_reason": classification["classification"] if classification else "UNKNOWN",
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "stderr_tail": detail,
    }
    write_receipt(os.path.join(os.path.dirname(os.path.abspath(state.state_path)),
                               "COMMANDLET_EXECUTION_RECEIPT.json"), receipt)

    if classification and classification.get("is_interrupted"):
        state.transition("INTERRUPTED", terminal_reason=classification["classification"],
                         return_code=classification.get("returncode"))
    elif classification and classification.get("is_success"):
        state.transition("VALIDATING_OUTPUT", terminal_reason="child exited 0")
    elif classification:
        state.transition("CHILD_FAILED",
                         terminal_reason=classification["classification"],
                         return_code=classification.get("returncode"))
    return receipt