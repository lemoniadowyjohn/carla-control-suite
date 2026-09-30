"""Runtime world/map state machine for governed CARLA capture.

Single authority for the invariant required by NEW-248 / NEW-249:

    once MAP_ESTABLISHED is entered, no additional map-changing operation
    (load_world / reload_world / generate_opendrive_world) may be issued
    until the capture ends.

The state machine is deliberately dependency-free (stdlib only) so it can be
imported from tools, tests and the capture subprocess alike, and so it can be
exercised without a CARLA installation.

Canonical states
----------------
UNRESOLVED        no target world identity yet
MAP_LOADING       a governed map-changing call is in flight
MAP_ESTABLISHED   target world identity proven (name + structure for manual Grid)
CAPTURE_PREPARING ego/sensor bring-up staged against the established world
CAPTURE_ACTIVE    governed frames are being recorded
FINALIZING        capture stopped; flush + evidence finalization only
COMPLETE          terminal success
FAILED            terminal failure (map may be reloaded by a *new* session)
"""

from __future__ import annotations

import json
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


class WorldPipelineState(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    MAP_LOADING = "MAP_LOADING"
    MAP_ESTABLISHED = "MAP_ESTABLISHED"
    CAPTURE_PREPARING = "CAPTURE_PREPARING"
    CAPTURE_ACTIVE = "CAPTURE_ACTIVE"
    FINALIZING = "FINALIZING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


#: Operations that change which map the server has loaded.
MAP_CHANGING_OPERATIONS = frozenset(
    {
        "load_world",
        "reload_world",
        "generate_opendrive_world",
        "load_opendrive_world",
        "load_builtin_world",
        "safe_reload_world",
        "stream_flush_reload",
    }
)

#: States in which any map-changing operation is forbidden.
_MAP_CHANGE_FORBIDDEN_STATES = frozenset(
    {
        WorldPipelineState.MAP_ESTABLISHED,
        WorldPipelineState.CAPTURE_PREPARING,
        WorldPipelineState.CAPTURE_ACTIVE,
        WorldPipelineState.FINALIZING,
        WorldPipelineState.COMPLETE,
    }
)

_ALLOWED_TRANSITIONS: Dict[WorldPipelineState, frozenset] = {
    WorldPipelineState.UNRESOLVED: frozenset(
        {
            WorldPipelineState.MAP_LOADING,
            WorldPipelineState.MAP_ESTABLISHED,  # --use-current-world: no load issued
            WorldPipelineState.FAILED,
            WorldPipelineState.COMPLETE,
        }
    ),
    WorldPipelineState.MAP_LOADING: frozenset(
        {
            WorldPipelineState.MAP_ESTABLISHED,
            WorldPipelineState.MAP_LOADING,  # nested/duplicate load attempt (rejected by guard)
            WorldPipelineState.FAILED,
        }
    ),
    WorldPipelineState.MAP_ESTABLISHED: frozenset(
        {
            WorldPipelineState.CAPTURE_PREPARING,
            WorldPipelineState.FAILED,
            WorldPipelineState.FINALIZING,
        }
    ),
    WorldPipelineState.CAPTURE_PREPARING: frozenset(
        {
            WorldPipelineState.CAPTURE_ACTIVE,
            WorldPipelineState.FINALIZING,
            WorldPipelineState.FAILED,
        }
    ),
    WorldPipelineState.CAPTURE_ACTIVE: frozenset(
        {
            WorldPipelineState.FINALIZING,
            WorldPipelineState.FAILED,
        }
    ),
    WorldPipelineState.FINALIZING: frozenset(
        {
            WorldPipelineState.COMPLETE,
            WorldPipelineState.FAILED,
        }
    ),
    WorldPipelineState.COMPLETE: frozenset(),
    WorldPipelineState.FAILED: frozenset(),
}


class MapTravelForbidden(RuntimeError):
    """Raised when a map-changing operation is attempted after establishment."""

    def __init__(self, operation: str, state: str, detail: str = "") -> None:
        self.operation = str(operation)
        self.state = str(state)
        self.detail = str(detail)
        message = (
            f"map_travel_forbidden: operation={self.operation!r} is not allowed in "
            f"state {self.state}"
        )
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class InvalidStateTransition(RuntimeError):
    pass


class WorldStateMachine:
    """Thread-safe world state machine.

    A single instance is meant to live for exactly one governed capture
    session.  ``mark_session_consumed()`` / ``SESSION_RESTART_REQUIRED`` live in
    :mod:`ultimate_pipeline.perception.session_contract`.
    """

    def __init__(
        self,
        *,
        initial: WorldPipelineState = WorldPipelineState.UNRESOLVED,
        journal: Any = None,
    ) -> None:
        self._lock = threading.RLock()
        self._state: WorldPipelineState = WorldPipelineState(initial)
        self._history: List[Dict[str, Any]] = []
        self._map_operation_attempts: List[Dict[str, Any]] = []
        self._journal_sink = journal
        self._record("INITIAL", {"state": self._state.value})

    # -- introspection -------------------------------------------------
    @property
    def state(self) -> WorldPipelineState:
        with self._lock:
            return self._state

    @property
    def history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history)

    @property
    def map_operation_attempts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._map_operation_attempts)

    def established(self) -> bool:
        return self.state in _MAP_CHANGE_FORBIDDEN_STATES

    # -- transitions ---------------------------------------------------
    def _record(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        entry = {
            "event": str(event),
            "state": self._state.value,
            "t": time.time(),
            "t_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if payload:
            entry.update(payload)
        self._history.append(entry)
        sink = self._journal_sink
        if sink is not None:
            try:
                sink(entry)
            except Exception:
                pass

    def transition(self, new_state: WorldPipelineState, *, reason: str = "") -> WorldPipelineState:
        new_state = WorldPipelineState(new_state)
        with self._lock:
            old = self._state
            if new_state == old:
                return old
            allowed = _ALLOWED_TRANSITIONS.get(old, frozenset())
            if new_state not in allowed:
                raise InvalidStateTransition(
                    f"invalid_world_state_transition:{old.value}->{new_state.value}"
                    f"{':' + reason if reason else ''}"
                )
            self._state = new_state
            self._record("TRANSITION", {"from": old.value, "to": new_state.value, "reason": reason})
            return new_state

    def try_transition(self, new_state: WorldPipelineState, *, reason: str = "") -> bool:
        try:
            self.transition(new_state, reason=reason)
            return True
        except InvalidStateTransition:
            return False

    # -- the core guard ------------------------------------------------
    def guard_map_change(self, operation: str, *, detail: str = "") -> None:
        """Raise :class:`MapTravelForbidden` if ``operation`` may not run now."""
        operation = str(operation)
        with self._lock:
            entry = {
                "operation": operation,
                "state": self._state.value,
                "t": time.time(),
                "detail": str(detail),
                "permitted": self._state not in _MAP_CHANGE_FORBIDDEN_STATES,
            }
            self._map_operation_attempts.append(entry)
            self._record("MAP_OPERATION_GUARD", entry)
            if self._state in _MAP_CHANGE_FORBIDDEN_STATES:
                raise MapTravelForbidden(operation, self._state.value, detail)

    def begin_map_load(self, operation: str = "load_world", *, detail: str = "") -> None:
        self.guard_map_change(operation, detail=detail)
        with self._lock:
            self.transition(WorldPipelineState.MAP_LOADING, reason=operation)

    def mark_established(self, *, reason: str = "world_identity_proven") -> None:
        with self._lock:
            if self._state in (
                WorldPipelineState.MAP_ESTABLISHED,
                WorldPipelineState.CAPTURE_PREPARING,
                WorldPipelineState.CAPTURE_ACTIVE,
                WorldPipelineState.FINALIZING,
                # Terminal states must not be resurrected by a late "we did
                # establish the map after all" teardown call.
                WorldPipelineState.COMPLETE,
                WorldPipelineState.FAILED,
            ):
                return
            self.transition(WorldPipelineState.MAP_ESTABLISHED, reason=reason)

    def mark_failed(self, *, reason: str = "") -> None:
        with self._lock:
            if self._state in (WorldPipelineState.COMPLETE, WorldPipelineState.FAILED):
                return
            self._state = WorldPipelineState.FAILED
            self._record("TERMINAL", {"reason": reason})

    def mark_complete(self, *, reason: str = "") -> None:
        with self._lock:
            # Both terminal states are sticky.  A run that already failed must
            # never be rewritten as COMPLETE by a late teardown path, or the
            # evidence would report success for a dead capture.
            if self._state in (WorldPipelineState.COMPLETE, WorldPipelineState.FAILED):
                return
            self._state = WorldPipelineState.COMPLETE
            self._record("TERMINAL", {"reason": reason})

    # -- reporting -----------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "schema": "WORLD_STATE_MACHINE_SNAPSHOT/v1",
                "state": self._state.value,
                "established": self._state in _MAP_CHANGE_FORBIDDEN_STATES,
                "map_changing_operations_permitted": self._state not in _MAP_CHANGE_FORBIDDEN_STATES,
                "history": list(self._history),
                "map_operation_attempts": list(self._map_operation_attempts),
            }

    def write_snapshot(self, path: Any) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(target)


# ---------------------------------------------------------------------------
# Process-wide default instance (optional convenience)
# ---------------------------------------------------------------------------

_DEFAULT: Optional[WorldStateMachine] = None
_DEFAULT_LOCK = threading.Lock()


def get_default_state_machine() -> WorldStateMachine:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = WorldStateMachine()
        return _DEFAULT


def reset_default_state_machine() -> WorldStateMachine:
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = WorldStateMachine()
        return _DEFAULT


def is_map_changing(operation: str) -> bool:
    return str(operation) in MAP_CHANGING_OPERATIONS


def guarded_load_world(client: Any, map_name: str, *, state_machine: WorldStateMachine, **kwargs: Any) -> Any:
    """``client.load_world`` that respects the state machine."""
    state_machine.begin_map_load("load_world", detail=str(map_name))
    try:
        return client.load_world(map_name, **kwargs)
    except Exception:
        state_machine.mark_failed(reason="load_world_exception")
        raise


def guarded_reload_world(world: Any, *, state_machine: WorldStateMachine, **kwargs: Any) -> Any:
    state_machine.begin_map_load("reload_world")
    try:
        return world.reload_world(**kwargs)
    except Exception:
        state_machine.mark_failed(reason="reload_world_exception")
        raise


def guarded_generate_opendrive_world(client: Any, xodr: str, *, state_machine: WorldStateMachine, **kwargs: Any) -> Any:
    state_machine.begin_map_load("generate_opendrive_world")
    try:
        return client.generate_opendrive_world(xodr, **kwargs)
    except Exception:
        state_machine.mark_failed(reason="generate_opendrive_world_exception")
        raise


def assert_no_map_change_after_established(
    attempts: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return the list of forbidden map-change attempts recorded so far."""
    violations: List[Dict[str, Any]] = []
    for entry in attempts or ():
        if isinstance(entry, dict) and entry.get("permitted") is False:
            violations.append(dict(entry))
    return violations
