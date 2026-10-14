"""Explicit lease handoff between sessions.

Handoff is a mutex-protected transfer record, never an implicit assumption:
the releasing session marks its lease HANDOFF_OFFERED with the designated
successor session id; the acquiring session presents the matching
HANDOFF_ACCEPT. Any mismatch: DENY.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import lease_store as _leases
from .os_lock import NamedMutex


def offer_handoff(lease: _leases.Lease, successor_session_id: str,
                  mutex: NamedMutex) -> Dict[str, Any]:
    cur = _leases.read_current()
    if cur is None or cur.run_id != lease.run_id:
        return {"ok": False, "code": "HANDOFF_NO_LIVE_LEASE"}
    cur.state = "RELEASING"
    _leases._write_current(cur)
    _leases._archive(cur)
    transfer = {
        "schema": "carla_ops_handoff/v1",
        "from_run_id": cur.run_id,
        "from_session": cur.session_id,
        "to_session": successor_session_id,
        "operation": cur.operation,
        "fingerprint": cur.operation_fingerprint,
        "state": "HANDOFF_OFFERED",
        "offered_utc": _leases._utcnow(),
    }
    path = _leases._lease_dir() / f"handoff_{cur.run_id}.json"
    import json

    path.write_text(json.dumps(transfer, indent=2), encoding="utf-8")
    try:
        _leases.CURRENT_LEASE_FILE.unlink()
    except OSError:
        pass
    return {"ok": True, "code": "HANDOFF_OFFERED",
            "transfer": str(path)}


def accept_handoff(successor_session_id: str, run_id: str,
                   mutex: NamedMutex) -> Dict[str, Any]:
    import json

    path = _leases._lease_dir() / f"handoff_{run_id}.json"
    try:
        transfer = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {"ok": False, "code": "HANDOFF_NOT_FOUND"}
    if transfer.get("to_session") != successor_session_id:
        return {"ok": False, "code": "HANDOFF_SESSION_MISMATCH"}
    if transfer.get("state") != "HANDOFF_OFFERED":
        return {"ok": False, "code": "HANDOFF_BAD_STATE"}
    transfer["state"] = "HANDOFF_ACCEPTED"
    transfer["accepted_utc"] = _leases._utcnow()
    path.write_text(json.dumps(transfer, indent=2), encoding="utf-8")
    return {"ok": True, "code": "HANDOFF_ACCEPTED", "transfer": transfer}
