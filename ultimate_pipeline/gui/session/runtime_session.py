"""Shared runtime session: single owner of client/world identity (Stage B1).

Before this service every panel kept its own ``world`` reference, so a map
load, disconnect or failed binding left stale references alive in panels
that never heard about it. ``RuntimeSession`` is the one place a binding
lives:

* every binding change bumps a monotonic **generation** and publishes a
  structured :class:`WorldChangedEvent` to subscribers;
* invalidation is explicit: map change (``MAP_LOAD`` / ``MAP_MISMATCH``),
  binding failure (``LOAD_FAILURE`` / ``BINDING_FAILURE``) and disconnect
  (``DISCONNECT``) all publish, so map/weather/sensor caches drop stale
  references deterministically;
* subscribers run synchronously on the caller thread, outside the state
  lock (re-entrant calls are safe), and a raising subscriber is recorded
  in ``subscriber_errors`` instead of breaking publication or the other
  subscribers.

The service never mutates the simulator. A Git writer lease is not a
CARLA runtime lease: nothing here grants tick or world authority -- the
``authority`` field only *records* what the binding session holds
(``SHARED_READONLY`` unless a caller explicitly binds otherwise).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from ultimate_pipeline.gui.health import SessionAuthority

__all__ = [
    "WorldChangedEvent", "RuntimeSession",
    "INITIAL", "MAP_LOAD", "MAP_MISMATCH", "LOAD_FAILURE",
    "BINDING_FAILURE", "DISCONNECT", "REASONS",
]

#: Initial adoption of an already-existing binding.
INITIAL = "INITIAL"
#: A map load completed and its identity was verified.
MAP_LOAD = "MAP_LOAD"
#: The server active map differs from the requested one.
MAP_MISMATCH = "MAP_MISMATCH"
#: A load RPC failed or left the server state unverified.
LOAD_FAILURE = "LOAD_FAILURE"
#: The caller could not bind a world reference at all.
BINDING_FAILURE = "BINDING_FAILURE"
#: The connection went away; client and world are both dropped.
DISCONNECT = "DISCONNECT"

REASONS = frozenset({
    INITIAL, MAP_LOAD, MAP_MISMATCH, LOAD_FAILURE, BINDING_FAILURE, DISCONNECT,
})

#: Reasons permitted when the resulting state is unbound (``world is None``).
_UNBOUND_REASONS = frozenset({LOAD_FAILURE, BINDING_FAILURE, DISCONNECT})
#: Reasons permitted when a world is actually bound.
_BOUND_REASONS = frozenset({INITIAL, MAP_LOAD, MAP_MISMATCH, LOAD_FAILURE})

#: Sentinel meaning "keep the previously recorded client".
_KEEP: Any = object()

_UNBOUND_MAP = "UNBOUND"
#: Identity when a failure left the server state unverified.
_UNKNOWN_IDENTITY = "UNKNOWN"


@dataclass(frozen=True)
class WorldChangedEvent:
    """One published binding change. Immutable, JSON-able, generation-stamped."""

    generation: int
    reason: str
    map_identity: str
    source: str
    world_bound: bool
    client_bound: bool

    def as_dict(self) -> dict:
        return {
            "generation": self.generation,
            "reason": self.reason,
            "map_identity": self.map_identity,
            "source": self.source,
            "world_bound": self.world_bound,
            "client_bound": self.client_bound,
        }


class RuntimeSession:
    """Shared client/world binding with generation-stamped change events."""

    def __init__(
        self,
        *,
        authority: SessionAuthority = SessionAuthority.SHARED_READONLY,
        client: Any = None,
        world: Any = None,
        map_identity: str = _UNBOUND_MAP,
    ) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self._authority = authority
        self._client = client
        self._world = world
        self._map_identity = _require_identity(map_identity)
        self._subscribers: list[Callable[[WorldChangedEvent], None]] = []
        self._subscriber_errors: deque[str] = deque(maxlen=32)
        self._last_event: WorldChangedEvent | None = None

    # -- read-only state ---------------------------------------------------
    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def authority(self) -> SessionAuthority:
        return self._authority

    @property
    def map_identity(self) -> str:
        with self._lock:
            return self._map_identity

    @property
    def world(self) -> Any:
        with self._lock:
            return self._world

    @property
    def client(self) -> Any:
        with self._lock:
            return self._client

    @property
    def has_world(self) -> bool:
        return self.world is not None

    @property
    def has_client(self) -> bool:
        return self.client is not None

    @property
    def last_event(self) -> WorldChangedEvent | None:
        with self._lock:
            return self._last_event

    @property
    def subscriber_errors(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._subscriber_errors)

    def snapshot(self) -> dict:
        """Consistent status dict for badges, tests and evidence records."""
        with self._lock:
            return {
                "generation": self._generation,
                "map_identity": self._map_identity,
                "world_bound": self._world is not None,
                "client_bound": self._client is not None,
                "authority": str(getattr(self._authority, "value", self._authority)),
                "subscriber_count": len(self._subscribers),
                "subscriber_errors": list(self._subscriber_errors),
                "last_event": (self._last_event.as_dict()
                               if self._last_event is not None else None),
            }

    # -- subscription ------------------------------------------------------
    def subscribe(self, callback: Callable[[WorldChangedEvent], None]):
        """Register ``callback`` for future events; returns an unsubscribe fn."""
        if not callable(callback):
            raise TypeError("subscriber must be callable")
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                for index, item in enumerate(self._subscribers):
                    if item is callback:
                        del self._subscribers[index]
                        return

        return unsubscribe

    # -- mutation of the binding (the only event sources) ------------------
    def bind_world(
        self,
        world: Any,
        *,
        map_identity: str,
        reason: str,
        source: str = "",
        client: Any = _KEEP,
    ) -> WorldChangedEvent:
        """Record a bound world; publish with ``world_bound=True``.

        ``client`` defaults to keeping the previously recorded client.
        """
        if world is None:
            raise ValueError(
                "bind_world requires a world; use clear_binding()/disconnect() "
                "to publish an unbound state")
        _require_reason(reason)
        if reason not in _BOUND_REASONS:
            raise ValueError(f"reason {reason!r} cannot be published for a bound world")
        return self._publish(reason=reason, world=world, map_identity=map_identity,
                             source=source, client=client, drop_client=False)

    def clear_binding(
        self,
        *,
        reason: str,
        source: str,
        map_identity: str = _UNBOUND_MAP,
        drop_client: bool = False,
    ) -> WorldChangedEvent:
        """Record an unbound world; publish with ``world_bound=False``.

        The client is kept by default (a failed load does not undo an
        established connection); ``drop_client=True`` is for disconnect.
        Inputs are validated before the DISCONNECT normalization, so a
        malformed identity is rejected loudly instead of being papered over.
        """
        _require_reason(reason)
        if reason not in _UNBOUND_REASONS:
            raise ValueError(f"reason {reason!r} cannot be published for an unbound world")
        _require_identity(map_identity)
        if reason == DISCONNECT:
            drop_client = True
            map_identity = _UNBOUND_MAP
        return self._publish(reason=reason, world=None, map_identity=map_identity,
                             source=source, client=_KEEP, drop_client=drop_client)

    def binding_failure(
        self,
        *,
        source: str,
        map_identity: str = _UNKNOWN_IDENTITY,
    ) -> WorldChangedEvent:
        """Convenience: an unbound state caused by a failed binding."""
        return self.clear_binding(reason=BINDING_FAILURE, source=source,
                                  map_identity=map_identity, drop_client=False)

    def disconnect(self, *, source: str) -> WorldChangedEvent:
        """Convenience: drop world and client; identity returns to UNBOUND."""
        return self.clear_binding(reason=DISCONNECT, source=source,
                                  map_identity=_UNBOUND_MAP, drop_client=True)

    # -- internals ---------------------------------------------------------
    def _publish(
        self,
        *,
        reason: str,
        world: Any,
        map_identity: str,
        source: str,
        client: Any,
        drop_client: bool,
    ) -> WorldChangedEvent:
        identity = _require_identity(map_identity)
        if not isinstance(source, str):
            raise TypeError("source must be a string")
        with self._lock:
            self._generation += 1
            self._world = world
            self._map_identity = identity
            if drop_client:
                self._client = None
            elif client is not _KEEP:
                self._client = client
            event = WorldChangedEvent(
                generation=self._generation,
                reason=reason,
                map_identity=identity,
                source=source,
                world_bound=world is not None,
                client_bound=self._client is not None,
            )
            self._last_event = event
            subscribers = list(self._subscribers)
        # Notify outside the lock: subscribers may call back into the
        # session (re-entrant RLock would be fine, but long user work must
        # not serialize behind the state lock).
        for callback in subscribers:
            try:
                callback(event)
            except Exception as exc:  # noqa: BLE001 -- publication must survive
                note = f"{type(callback).__name__}: {type(exc).__name__}: {exc}"
                with self._lock:
                    self._subscriber_errors.append(note)
        return event


def _require_reason(reason: str) -> None:
    if not isinstance(reason, str) or reason not in REASONS:
        raise ValueError(f"unknown event reason: {reason!r}")


def _require_identity(map_identity: str) -> str:
    if not isinstance(map_identity, str) or not map_identity.strip():
        raise ValueError(f"map_identity must be a non-empty string, got {map_identity!r}")
    return map_identity
