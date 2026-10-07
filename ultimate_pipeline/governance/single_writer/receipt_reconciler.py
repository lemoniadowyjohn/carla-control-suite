"""Stale-RUNNING supervision receipt reconciliation (Batch 17, section 3).

Rule (permanent):
  RUNNING + live process            -> RUNNING (still in flight)
  RUNNING + dead process + success witness
                                    -> SUCCESS (consume witness)
  RUNNING + dead process + nonzero witness
                                    -> the witness's nonzero classification
  RUNNING + dead process + no witness
                                    -> UNKNOWN_TERMINATION_RECONCILIATION_REQUIRED
  witness PID/creation mismatch     -> witness does not match (ignore it)

Liveness and witness matching use PID + CREATION TIME, never PID alone.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import exit_codes as _exits
from . import lease_store as _leases


def reconcile_supervision_receipt(receipt: Dict[str, Any],
                                  witness: Optional[Dict[str, Any]] = None
                                  ) -> Dict[str, Any]:
    state = receipt.get("state")
    if state != "RUNNING":
        return {"verdict": state, "reason": "receipt already terminal"}
    pid = receipt.get("child_pid")
    creation = _leases.process_creation_time(pid) if pid else None
    if creation is not None:
        return {"verdict": "RUNNING", "reason": "owner process still alive",
                "pid": pid, "creation_time": creation}
    if witness is None:
        return {"verdict": "UNKNOWN_TERMINATION_RECONCILIATION_REQUIRED",
                "reason": "process dead and no kernel witness; explicit "
                          "reconciliation required",
                "pid": pid}
    if witness.get("pid") != pid:
        return {"verdict": "UNKNOWN_TERMINATION_RECONCILIATION_REQUIRED",
                "reason": "witness PID does not match receipt child",
                "pid": pid}
    w_creation = witness.get("creation_time", "")
    r_creation = receipt.get("process_creation_time", "") or ""
    if r_creation and w_creation != r_creation:
        return {"verdict": "UNKNOWN_TERMINATION_RECONCILIATION_REQUIRED",
                "reason": "witness creation time does not match: possible "
                          "PID reuse; refusing to consume",
                "pid": pid}
    code = witness.get("exit_code_dec")
    if code is None:
        return {"verdict": "UNKNOWN_TERMINATION_RECONCILIATION_REQUIRED",
                "reason": "witness has no exit code", "pid": pid}
    if code == 0:
        return {"verdict": "SUCCESS", "reason": "kernel witness proves "
                "exit 0; supersedes frozen RUNNING", "pid": pid,
                "exit_code_dec": 0, "exit_code_hex": "0x0"}
    cls = _exits.classify_exit(int(code))["class"]
    return {"verdict": cls, "reason": "kernel witness nonzero exit",
            "pid": pid, "exit_code_dec": int(code),
            "exit_code_hex": hex(int(code) & 0xFFFFFFFF)}
