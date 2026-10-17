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

3. Interrupts had no linearisation contract. A SIGINT landing after the child
   had already completed could rewrite a success into INTERRUPTED, the POSIX
   child-death code ``-SIGINT`` was classified as a plain nonzero exit, the
   interrupt path left the child running, and a Popen failure produced no
   receipt at all. :func:`run_supervised` now latches the first interrupt at a
   single linearisation point (child ``poll()`` on latch entry), reaps an
   interrupted child with terminate -> bounded wait -> kill escalation, lets a
   completion that was observed first stand as-is (recording the late
   interrupt), and always writes a receipt with the event ordering.

Design constraints:
  * The interactive editor must never be treated as the import child. Role is
    detected from the executable name: UE4Editor-Cmd.exe and UE4Editor.exe
    launched with ``-run=`` are commandlet invocations; a plain UE4Editor.exe is
    interactive.
  * No sleep-based synchronisation and no polling loops in this module; it only
    classifies and records. The interrupt-reap path uses bounded waits that are
    escalation budgets for one dying child, never coordination between parties.
  * Pure stdlib, no Unreal dependency, so it is unit testable on any host.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
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


def _posix_signal_table() -> dict[int, tuple[str, str, str]]:
    """Map negative return codes (POSIX signal deaths) to a classification.

    Built at import time from whatever the platform defines, so the table is
    inert on Windows (which never reports negative return codes) without
    pretending signals it does not have. SIGINT/SIGTERM are external
    interruptions; the fatal fault signals are crashes; everything else stays a
    plain nonzero exit rather than being promoted without evidence.
    """
    wanted = [
        ("SIGINT", "interrupt", "terminated by SIGINT"),
        ("SIGTERM", "interrupt", "terminated by SIGTERM"),
        ("SIGSEGV", "crash", "fatal SIGSEGV"),
        ("SIGABRT", "crash", "fatal SIGABRT"),
        ("SIGBUS", "crash", "fatal SIGBUS"),
        ("SIGFPE", "crash", "fatal SIGFPE"),
        ("SIGILL", "crash", "fatal SIGILL"),
    ]
    table: dict[int, tuple[str, str, str]] = {}
    for name, kind, detail in wanted:
        num = getattr(signal, name, None)
        if isinstance(num, int) and num > 0:
            table[-num] = (name, detail, kind)
    return table


POSIX_SIGNALS = _posix_signal_table()


def classify_exit_status(returncode: int | None) -> dict[str, Any]:
    """Classify a child return code.

    A control-event exit is reported as EXTERNALLY_INTERRUPTED and explicitly
    NOT as a crash, and NOT as success. This is the classification the previous
    run required and did not have. The same rule holds for POSIX signal deaths:
    ``-SIGINT`` and ``-SIGTERM`` are interruptions, fatal fault signals are
    crashes, and any other negative code is a nonzero exit -- never an
    unrecognised NTSTATUS.
    """
    if returncode is None:
        return {"returncode": None, "classification": "UNKNOWN_NO_RETURN_CODE",
                "ntstatus_name": None, "detail": "child produced no return code",
                "is_crash": False, "is_success": False, "is_interrupted": False}

    if returncode < 0:
        posix = POSIX_SIGNALS.get(returncode)
        if posix is not None:
            sig_name, sig_detail, kind = posix
            interrupted = kind == "interrupt"
            return {
                "returncode": returncode,
                "signal_name": sig_name,
                "classification": EXTERNALLY_INTERRUPTED if interrupted else CRASH,
                "ntstatus_name": None,
                "detail": sig_detail,
                "is_crash": not interrupted,
                "is_success": False,
                "is_interrupted": interrupted,
            }
        return {"returncode": returncode, "classification": NONZERO_EXIT,
                "ntstatus_name": None,
                "detail": "killed by unlisted signal %d" % -returncode,
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

    @staticmethod
    def _volume_root(key) -> str:
        """Resolve a threshold key to a filesystem root that can be measured.

        A single-letter key names a Windows drive (``C`` -> ``C:\\``), which is
        the historical contract and is preserved unchanged on Windows. Any other
        key -- a POSIX mount point, a temporary directory anchor, an absolute
        path -- is used verbatim so the gate measures real filesystems on every
        platform instead of assuming drive letters exist.
        """
        key = str(key).strip()
        if len(key) == 1 and key.isalpha():
            return key.upper() + ":\\" if os.name == "nt" else key
        return key

    def measure(self) -> dict:
        rows = {}
        for key in sorted({str(v).strip() for v in self.minimum_free_gb}):
            root = self._volume_root(key)
            if not os.path.isdir(root):
                rows[key] = {"error": "volume not present"}
                continue
            u = shutil.disk_usage(root)
            rows[key] = {"total_gb": round(u.total / 1024 ** 3, 2),
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
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)
    os.replace(tmp, path)      # atomic: a reader never sees a half receipt
    return path


# Escalation budgets for reaping one interrupted child: bounded waits on a
# dying process, not synchronisation between cooperating parties.
_REAP_TERMINATE_GRACE_S = 2.0
_REAP_KILL_GRACE_S = 5.0


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reap_interrupted_child(proc, events: list) -> dict:
    """Reap an interrupt-path child: terminate -> bounded wait -> kill escalation.

    Every outcome is returned for honest recording, including a child that
    survives escalation (unkillable / foreign-owned). A ``None`` proc means the
    interrupt latched before the child existed, which is also an outcome, not
    an omission.
    """
    if proc is None:
        return {"outcome": "no_child", "returncode": None}
    rc = proc.poll()
    if rc is not None:
        events.append({"event": "child_already_exited", "utc": _utc_stamp(),
                       "returncode": rc})
        return {"outcome": "already_exited", "returncode": rc}
    try:
        proc.terminate()
        events.append({"event": "terminate_sent", "utc": _utc_stamp()})
    except OSError as exc:
        events.append({"event": "terminate_failed", "utc": _utc_stamp(),
                       "error": repr(exc)})
    try:
        rc = proc.wait(timeout=_REAP_TERMINATE_GRACE_S)
        events.append({"event": "child_reaped", "utc": _utc_stamp(),
                       "returncode": rc, "escalation": "terminate"})
        return {"outcome": "reaped_after_terminate", "returncode": rc}
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
        events.append({"event": "kill_sent", "utc": _utc_stamp()})
    except OSError as exc:
        events.append({"event": "kill_failed", "utc": _utc_stamp(),
                       "error": repr(exc)})
    try:
        rc = proc.wait(timeout=_REAP_KILL_GRACE_S)
        events.append({"event": "child_reaped", "utc": _utc_stamp(),
                       "returncode": rc, "escalation": "kill"})
        return {"outcome": "reaped_after_kill", "returncode": rc}
    except subprocess.TimeoutExpired:
        events.append({"event": "child_survived_escalation", "utc": _utc_stamp()})
        return {"outcome": "survived_escalation", "returncode": None}


def run_supervised(command: list[str], *, state: ImportState,
                   cwd: str | None = None, timeout_sec: int | None = None,
                   stdout_path: str | None = None,
                   stderr_path: str | None = None) -> dict:
    """Run one child, recording role, exit classification and a terminal receipt.

    Always produces a receipt, including on KeyboardInterrupt. Never kills
    unrelated UE4Editor sessions: it only manages the process it started.

    Interrupt contract (linearised, no sleep-based synchronisation):

    * **T_int** is the first interrupt observation (SIGINT handler entry or the
      first caught KeyboardInterrupt); its first action is ``poll()`` of the
      child. Child alive at T_int -> INTERRUPTED is latched and the child is
      reaped. Repeated interrupts change nothing: the first latch wins, later
      ones are recorded as events.
    * **T_done** is the return of ``communicate()`` (terminal child state
      observed). An interrupt seen only after T_done never rewrites the
      outcome; it is recorded as ``interrupt_after_completion`` (and
      ``late_keyboard_interrupt`` for a KeyboardInterrupt).
    * A startup (Popen) failure writes a receipt and a terminal state;
      RUNNING is only entered once the child exists, so it can never dangle.
    """
    role = detect_process_role(command[0], command[1:])
    started = _utc_stamp()
    t0 = time.time()
    events: list = []

    def _event(name: str, **fields: Any) -> None:
        events.append({"event": name, "utc": _utc_stamp(), **fields})

    latch: dict[str, Any] = {"interrupted": False, "via": None,
                             "alive_at_t_int": None, "utc": None, "repeats": 0}
    proc_holder: dict[str, Any] = {"proc": None}
    completion: dict[str, Any] = {"observed": False, "rc": None}
    _event("supervision_start")

    def _request_interrupt(via: str, signum: int | None = None) -> None:
        if latch["interrupted"]:
            latch["repeats"] += 1
            _event("interrupt_repeated", via=via, signum=signum)
            return
        latch["interrupted"] = True
        latch["via"] = via
        latch["utc"] = _utc_stamp()
        proc = proc_holder["proc"]
        if proc is None:
            latch["alive_at_t_int"] = None
            _event("interrupt_latched", via=via, signum=signum,
                   phase="pre_spawn", alive_at_t_int=None)
            return
        alive = proc.poll() is None
        latch["alive_at_t_int"] = alive
        _event("interrupt_latched", via=via, signum=signum,
               phase="post_spawn", alive_at_t_int=alive)
        if alive:
            try:
                proc.terminate()
                _event("terminate_sent", reason="interrupt_latch")
            except OSError as exc:
                _event("terminate_failed", reason="interrupt_latch",
                       error=repr(exc))

    def _sig_handler(signum: int, frame: Any) -> None:
        _request_interrupt("signal", signum=signum)

    previous_sigint = None
    try:
        previous_sigint = signal.signal(signal.SIGINT, _sig_handler)
    except (ValueError, OSError) as exc:
        # Non-main thread: the exception path below still honours the contract.
        _event("sigint_latch_unavailable", error=repr(exc))

    try:
        out_fh = None
        err_fh = None
        proc = None
        classification: dict | None = None
        detail = ""
        stdout_text = stderr_text = None
        spawn_error: OSError | None = None
        ki_raised = False
        timed_out = False

        if state.state != "STARTING":
            state.flush()

        try:
            if stdout_path:
                out_fh = open(stdout_path, "w", encoding="utf-8")
            if stderr_path:
                err_fh = open(stderr_path, "w", encoding="utf-8")

            if not latch["interrupted"]:
                proc = subprocess.Popen(
                    command, cwd=cwd,
                    stdout=out_fh or subprocess.PIPE,
                    stderr=err_fh or subprocess.PIPE)
                proc_holder["proc"] = proc
                _event("spawned", child_pid=proc.pid)
                state.child_pid = proc.pid
                if state.state == "STARTING":
                    state.transition("RUNNING", executable=command[0])
                else:
                    state.flush()
            else:
                _event("spawn_skipped", reason="interrupt_latched_pre_spawn")

            if proc is not None and not latch["interrupted"]:
                stdout_text, stderr_text = proc.communicate(timeout=timeout_sec)
                completion["observed"] = True
                completion["rc"] = proc.returncode
                _event("completion_observed", returncode=proc.returncode)
                classification = classify_exit_status(proc.returncode)
                if isinstance(stdout_text, bytes):
                    stdout_text = stdout_text.decode("utf-8", "replace")
                if isinstance(stderr_text, bytes):
                    stderr_text = stderr_text.decode("utf-8", "replace")
                detail = stderr_text[-4000:] if stderr_text else ""
        except KeyboardInterrupt:
            ki_raised = True
            if completion["observed"]:
                _event("late_keyboard_interrupt", phase="supervised_block")
            else:
                _request_interrupt("keyboard_interrupt")
        except subprocess.TimeoutExpired:
            timed_out = True
            _event("timeout_expired", timeout_sec=timeout_sec)
        except OSError as exc:
            spawn_error = exc
            _event("spawn_failed", error=repr(exc))
        finally:
            if out_fh:
                out_fh.close()
            if err_fh:
                err_fh.close()

        # ---- outcome linearisation ------------------------------------
        if completion["observed"] and classification is None:
            # Classification was interrupted after T_done; recompute it: the
            # child's terminal state, not the interrupt, decides the outcome.
            classification = classify_exit_status(completion["rc"])

        cleanup = None
        interrupted_outcome = False
        interrupt_after_completion = False
        late_keyboard_interrupt = False

        if ki_raised and completion["observed"]:
            # Case E: T_done precedes the KeyboardInterrupt; the outcome stands.
            late_keyboard_interrupt = True
            interrupt_after_completion = True
            _event("outcome_stood_after_completion", via="keyboard_interrupt")
        elif (latch["interrupted"] and completion["observed"]
              and latch["alive_at_t_int"] is False):
            # Case D: the child had already exited when T_int observed it.
            interrupt_after_completion = True
            _event("outcome_stood_after_completion", via=latch["via"])
        elif latch["interrupted"] or ki_raised:
            # Cases B/C: child alive (or not yet existing) at T_int.
            interrupted_outcome = True
            cleanup = _reap_interrupted_child(proc, events)
            classification = {
                "returncode": proc.returncode if proc is not None else None,
                "classification": EXTERNALLY_INTERRUPTED,
                "ntstatus_name": ("PYTHON_KEYBOARDINTERRUPT"
                                  if latch["via"] == "keyboard_interrupt"
                                  else "SUPERVISOR_SIGINT"),
                "detail": ("interrupt latched at T_int (via=%s, "
                           "alive_at_t_int=%s); cleanup=%s; repeats=%d"
                           % (latch["via"], latch["alive_at_t_int"],
                              cleanup.get("outcome"), latch["repeats"])),
                "is_crash": False,
                "is_success": False,
                "is_interrupted": True,
            }
            detail = classification["detail"]
        elif spawn_error is not None:
            classification = {
                "returncode": None,
                "classification": "SPAWN_FAILURE",
                "ntstatus_name": None,
                "detail": "%s: %s" % (type(spawn_error).__name__, spawn_error),
                "is_crash": False, "is_success": False, "is_interrupted": False,
            }
            detail = classification["detail"]
        elif timed_out:
            classification = {
                "returncode": None, "classification": "CHILD_TIMEOUT",
                "ntstatus_name": None,
                "detail": "timeout after %ss" % timeout_sec,
                "is_crash": False, "is_success": False, "is_interrupted": False,
            }

        if classification is None:      # defensive: receipts are always complete
            classification = classify_exit_status(completion["rc"]
                                                  if completion["observed"]
                                                  else None)

        ended = _utc_stamp()
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
            "terminal_reason": classification["classification"],
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "stderr_tail": detail,
            "interrupted": interrupted_outcome,
            "interrupt_after_completion": interrupt_after_completion,
            "late_keyboard_interrupt": late_keyboard_interrupt,
            "child_alive_at_interrupt": (latch["alive_at_t_int"]
                                         if latch["interrupted"] else None),
            "interrupt_latched_via": latch["via"],
            "interrupt_repeats": latch["repeats"],
            "completion_observed": completion["observed"],
            "cleanup": cleanup,
            "event_order": list(events),
        }

        def _record_terminal_state() -> None:
            if interrupted_outcome:
                state.transition("INTERRUPTED",
                                 terminal_reason=classification["classification"],
                                 return_code=classification.get("returncode"))
            elif classification.get("is_success"):
                state.transition("VALIDATING_OUTPUT",
                                 terminal_reason="child exited 0")
            else:
                state.transition("CHILD_FAILED",
                                 terminal_reason=classification["classification"],
                                 return_code=classification.get("returncode"))

        receipt_path = os.path.join(
            os.path.dirname(os.path.abspath(state.state_path)),
            "COMMANDLET_EXECUTION_RECEIPT.json")
        try:
            write_receipt(receipt_path, receipt)
        except KeyboardInterrupt:
            # A second Ctrl+C during recording must not cost the receipt.
            receipt["event_order"].append(
                {"event": "interrupt_during_recording", "utc": _utc_stamp(),
                 "attempted": "receipt_retry"})
            write_receipt(receipt_path, receipt)
        try:
            _record_terminal_state()
        except KeyboardInterrupt:
            if state.is_terminal():
                state.flush()
            else:
                _record_terminal_state()
        return receipt
    finally:
        if previous_sigint is not None:
            try:
                signal.signal(signal.SIGINT, previous_sigint)
            except (ValueError, OSError):
                pass