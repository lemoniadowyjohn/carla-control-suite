"""Connection health: an explicit five-stage probe plus the application state
machine.

The probe is staged so a UI can say *where* a connection failed instead of only
saying "disconnected".  It is strictly read-only: it opens a socket, performs
the RPC handshake, reads the server version and enumerates maps.  It never
loads a world, never sets weather, never claims the Traffic Manager and never
touches a shared world.

The state machine follows ``07_GUI_SPEC/GLOBAL_STATES.md`` section 1.  OFFLINE
is the default and every mutating control is disabled in it.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ultimate_pipeline.gui.cancellation import CancellationToken
from ultimate_pipeline.gui.results import Result, Tri, TriState

__all__ = [
    "ConnectionState", "SessionAuthority", "HealthStage", "StageOutcome",
    "ConnectionHealth", "probe_stages", "BACKEND_LIVE", "BACKEND_MOCK",
]


class ConnectionState(str, Enum):
    NOT_INSTALLED = "NOT_INSTALLED"
    OFFLINE = "OFFLINE"
    CONNECTING = "CONNECTING"
    UNHEALTHY = "UNHEALTHY"
    HEALTHY = "HEALTHY"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DISCONNECTING = "DISCONNECTING"
    STOPPED = "STOPPED"


class SessionAuthority(str, Enum):
    """Orthogonal to connection state. ``SHARED_READONLY`` is the default."""

    SHARED_READONLY = "SHARED_READONLY"
    EXCLUSIVE_TICK = "EXCLUSIVE_TICK"
    EXCLUSIVE_WORLD = "EXCLUSIVE_WORLD"
    EXCLUSIVE_TM_PORT = "EXCLUSIVE_TM_PORT"


class HealthStage(str, Enum):
    """The five explicit stages of a connection health probe."""

    PORT_OPEN = "PORT_OPEN"
    RPC_HANDSHAKE = "RPC_HANDSHAKE"
    SERVER_VERSION = "SERVER_VERSION"
    MAP_ENUMERATION = "MAP_ENUMERATION"
    WORLD_READY = "WORLD_READY"


@dataclass(frozen=True)
class StageOutcome:
    """The result of one probe stage."""

    stage: HealthStage
    ok: bool
    detail: str = ""
    value: Any = None
    duration_ms: int = 0
    #: ``True`` when the backend simply cannot perform this stage. That is not
    #: a failure and must never be displayed as a green check.
    unsupported: bool = False

    def as_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "ok": self.ok,
            "detail": self.detail,
            "value": self.value,
            "duration_ms": self.duration_ms,
            "unsupported": self.unsupported,
        }


@dataclass
class ConnectionHealth:
    """Aggregate health across the five stages."""

    host: str
    port: int
    state: ConnectionState = ConnectionState.OFFLINE
    stages: list[StageOutcome] = field(default_factory=list)
    server_version: str | None = None
    cleanup_failures: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return self.state in (ConnectionState.HEALTHY, ConnectionState.VERSION_MISMATCH)

    @property
    def first_failing_stage(self) -> StageOutcome | None:
        for outcome in self.stages:
            if not outcome.ok and not outcome.unsupported:
                return outcome
        return None

    def stage(self, stage: HealthStage) -> StageOutcome | None:
        for outcome in self.stages:
            if outcome.stage is stage:
                return outcome
        return None

    def as_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "state": self.state.value,
            "healthy": self.healthy,
            "server_version": self.server_version,
            "stages": [s.as_dict() for s in self.stages],
            "cleanup_failures": list(self.cleanup_failures),
        }


def probe_stages(
    backend: Any,
    host: str,
    port: int,
    *,
    timeout_s: float = 5.0,
    expected_version: str = "0.9.16",
    token: CancellationToken | None = None,
) -> ConnectionHealth:
    """Run the five-stage health probe against ``backend``.

    ``backend`` must expose ``probe``, ``server_version`` and ``available_maps``.
    Stages that are unsupported by the backend are reported as ``unsupported``
    rather than silently skipped.
    """
    import time

    health = ConnectionHealth(host=host, port=port)

    def timed(stage: HealthStage, fn) -> StageOutcome:
        started = time.perf_counter()
        try:
            token.raise_if_cancelled() if token else None
            outcome = fn()
        except Exception as exc:  # surfaced, never swallowed
            return StageOutcome(
                stage, False,
                detail=f"{type(exc).__name__}: {exc}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        return StageOutcome(
            stage, True, value=outcome,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # Stage 1 - TCP port
    health.stages.append(timed(HealthStage.PORT_OPEN, lambda: _tcp_probe(host, port, timeout_s)))

    if not health.stages[-1].ok:
        health.state = ConnectionState.UNHEALTHY
        return health

    # Stage 2 - RPC handshake
    result: Result = backend.probe(host=host, port=port, timeout_s=timeout_s)
    health.stages.append(
        StageOutcome(
            HealthStage.RPC_HANDSHAKE, result.ok,
            detail=result.reason or "handshake ok",
            duration_ms=0,
        )
    )
    if not result.ok:
        health.state = ConnectionState.UNHEALTHY
        return health

    # Stage 3 - server version (warning only; backend enforces nothing)
    version = backend.server_version()
    health.server_version = version
    health.stages.append(
        StageOutcome(
            HealthStage.SERVER_VERSION, version is not None,
            detail="" if version else "server did not report a version",
            value=version,
        )
    )

    # Stage 4 - map enumeration (may legitimately be unsupported)
    maps: Tri = backend.available_maps()
    if maps.state == TriState.PROBE_UNSUPPORTED:
        health.stages.append(
            StageOutcome(HealthStage.MAP_ENUMERATION, False, detail=maps.reason, unsupported=True)
        )
    elif maps.state == TriState.EMPTY:
        health.stages.append(
            StageOutcome(HealthStage.MAP_ENUMERATION, True, detail=maps.reason, value=[])
        )
    else:
        names = list(maps.value or [])
        health.stages.append(
            StageOutcome(HealthStage.MAP_ENUMERATION, True, value=names,
                         detail=f"{len(names)} maps")
        )

    # Stage 5 - world ready (read-only: does NOT load a world)
    world = backend.read_settings()
    health.stages.append(
        StageOutcome(
            HealthStage.WORLD_READY, bool(getattr(world, "available", True)),
            detail="world settings read without loading a world",
            value=repr(world),
        )
    )

    if version and expected_version and version != expected_version:
        health.state = ConnectionState.VERSION_MISMATCH
    else:
        health.state = ConnectionState.HEALTHY
    return health


def _tcp_probe(host: str, port: int, timeout_s: float) -> bool:
    with socket.create_connection((host, port), timeout=timeout_s):
        return True


def mutating_controls_enabled(state: ConnectionState, authority: SessionAuthority) -> bool:
    """Gate every simulator-mutating control.

    ``SHARED_READONLY`` -- the default -- disables all of them.  Per the
    operating contract, no blanket live control is ever granted.
    """
    if state not in (ConnectionState.HEALTHY, ConnectionState.VERSION_MISMATCH):
        return False
    if authority is SessionAuthority.SHARED_READONLY:
        return False
    if state is ConnectionState.VERSION_MISMATCH:
        return False
    return authority in (
        SessionAuthority.EXCLUSIVE_TICK,
        SessionAuthority.EXCLUSIVE_WORLD,
        SessionAuthority.EXCLUSIVE_TM_PORT,
    )


BACKEND_LIVE = "carla"
BACKEND_MOCK = "mock"