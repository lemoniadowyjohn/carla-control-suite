"""Grid process-lifetime contract (NEW-258 / NEW-259).

``UP_SKIP_DESTROY=1`` prevents one crash class but leaves stale actors behind.
A CARLA session that has served one governed Grid capture must not be reused
indefinitely.

Preferred governed strategy: **one Grid capture per CARLA process/session.**

Flow::

    connect to manually loaded Grid -> capture -> stop listeners -> flush disk
    -> finalize evidence -> mark session consumed
    -> terminate/restart CARLA before the next governed capture

If automatic termination is not permitted (CARLA was manually launched), the
session writes ``SESSION_RESTART_REQUIRED`` and refuses another governed
capture in the same session.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

SESSION_RESTART_REQUIRED = "SESSION_RESTART_REQUIRED"
SESSION_ACTIVE = "SESSION_ACTIVE"
SESSION_CONSUMED = "SESSION_CONSUMED"

STATE_FILENAME = "carla_session_contract.json"

_KNOWN_UNSTABLE = frozenset({"grid0821", "grid0828"})


def is_known_unstable_map(map_name: Optional[str]) -> bool:
    text = str(map_name or "").strip().lower()
    leaf = text.replace("\\", "/").split("/")[-1]
    return leaf in _KNOWN_UNSTABLE or text in _KNOWN_UNSTABLE


class CaptureSessionContract:
    """Tracks whether the current CARLA process may serve another capture."""

    def __init__(
        self,
        *,
        map_name: Optional[str] = None,
        carla_pid: Optional[int] = None,
        auto_restart_allowed: Optional[bool] = None,
        state_dir: Any = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.map_name = str(map_name) if map_name else None
        self.carla_pid = carla_pid
        self.session_id = str(session_id or f"sess_{int(time.time())}_{os.getpid()}")
        if auto_restart_allowed is None:
            auto_restart_allowed = os.environ.get("UP_ALLOW_CARLA_AUTO_RESTART", "0").strip() == "1"
        self.auto_restart_allowed = bool(auto_restart_allowed)
        self._state_dir = Path(str(state_dir)) if state_dir else None
        self.consumed = False
        self.consumed_reason: Optional[str] = None
        self.status = SESSION_ACTIVE
        self.history: list = []
        self._record("CREATED", {"map_name": self.map_name, "carla_pid": self.carla_pid})

    # -- internals ------------------------------------------------------
    def _record(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        entry = {
            "event": event,
            "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": self.session_id,
        }
        if payload:
            entry.update(payload)
        self.history.append(entry)

    @property
    def needs_restart(self) -> bool:
        return self.status == SESSION_RESTART_REQUIRED

    def may_serve_governed_capture(self) -> bool:
        if self.consumed:
            return False
        return self.status == SESSION_ACTIVE

    # -- lifecycle ------------------------------------------------------
    def mark_consumed(self, *, reason: str = "governed_capture_complete") -> Dict[str, Any]:
        self.consumed = True
        self.consumed_reason = str(reason)
        if self.auto_restart_allowed:
            self.status = SESSION_ACTIVE
            self._record(
                "SESSION_CONSUMED",
                {"reason": reason, "next": "CARLA_RESTART_AUTOMATICALLY_PERMITTED"},
            )
        else:
            self.status = SESSION_RESTART_REQUIRED
            self._record(
                "SESSION_CONSUMED",
                {"reason": reason, "next": SESSION_RESTART_REQUIRED},
            )
        self.write(self._state_dir)
        return self.payload()

    def assert_may_capture(self) -> None:
        if not self.may_serve_governed_capture():
            raise RuntimeError(
                f"{SESSION_RESTART_REQUIRED}:session={self.session_id}:"
                f"status={self.status}:reason={self.consumed_reason}"
            )

    def mark_failed(self, *, reason: str = "capture_failed") -> Dict[str, Any]:
        # Failure cleanup must be at least as safe as success cleanup: a failed
        # Grid capture still consumes the session.
        if is_known_unstable_map(self.map_name):
            return self.mark_consumed(reason=f"failure:{reason}")
        self._record("FAILED", {"reason": reason})
        self.write(self._state_dir)
        return self.payload()

    # -- persistence ----------------------------------------------------
    def payload(self) -> Dict[str, Any]:
        return {
            "schema": "CAPTURE_SESSION_CONTRACT/v1",
            "session_id": self.session_id,
            "map_name": self.map_name,
            "carla_pid": self.carla_pid,
            "known_unstable_map": is_known_unstable_map(self.map_name),
            "status": self.status,
            "consumed": self.consumed,
            "consumed_reason": self.consumed_reason,
            "auto_restart_allowed": self.auto_restart_allowed,
            "may_serve_governed_capture": self.may_serve_governed_capture(),
            "one_capture_per_session_policy": True,
            "history": list(self.history),
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def write(self, directory: Any = None) -> Optional[Path]:
        target_dir = Path(str(directory)) if directory else self._state_dir
        if target_dir is None:
            return None
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / STATE_FILENAME
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path

    def restart_required_marker(self, directory: Any) -> Path:
        target_dir = Path(str(directory)) if directory else (self._state_dir or Path("."))
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "SESSION_RESTART_REQUIRED.txt"
        path.write_text(
            "SESSION_RESTART_REQUIRED\n"
            f"session_id={self.session_id}\n"
            f"map_name={self.map_name}\n"
            f"carla_pid={self.carla_pid}\n"
            "reason=one_governed_capture_per_carla_session\n"
            "action=terminate_and_restart_carla_before_the_next_governed_capture\n",
            encoding="utf-8",
        )
        return path


def load_contract(directory: Any) -> Optional[Dict[str, Any]]:
    path = Path(str(directory)) / STATE_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def session_blocks_next_capture(directory: Any) -> bool:
    payload = load_contract(directory)
    if not payload:
        return False
    if payload.get("consumed") and not payload.get("auto_restart_allowed"):
        return True
    return payload.get("status") == SESSION_RESTART_REQUIRED
