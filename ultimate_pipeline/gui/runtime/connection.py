"""Connection adapter: a governed ladder, not a competing runtime controller.

This module **wraps** the existing ``carla_utils`` / ``TrafficManagerSession``
services. It does not replace them and it does not become a second owner of the
clock.

Two hard rules:

* **The destructive connect path is never taken implicitly.**
  ``ultimate_pipeline/core/carla_utils.py`` calls ``_kill_stuck_carla()``
  (`:314`, `:411`, `:433`) and ``shutil.rmtree`` over ``CarlaUE4`` directories
  (`:168-194`) *inside* connect. Those actions require explicit typed
  confirmation; an ordinary connection never performs them.
* **Version mismatch is a gate, not a warning that gets swallowed.**
  The upstream check is warn-only and is itself swallowed
  (``carla_utils.py:477-485``). Here a mismatch blocks until the operator
  explicitly accepts it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ultimate_pipeline.gui.results import Result

__all__ = [
    "ConnectStage", "StageReport", "ConnectLadder", "ConnectionProfile",
    "DestructiveAction", "confirm_destructive", "connect",
]


class ConnectStage(str, Enum):
    """The five-stage health ladder for a connection attempt."""

    RPC_PORT = "RPC_PORT"
    API_VERSION = "API_VERSION"
    MAP_IDENTITY = "MAP_IDENTITY"
    TICK_AUTHORITY = "TICK_AUTHORITY"
    SENSOR_CANARY = "SENSOR_CANARY"


@dataclass(frozen=True)
class StageReport:
    stage: ConnectStage
    ok: bool
    detail: str = ""
    value: Any = None
    #: ``True`` when the backend cannot perform this stage at all. Never a pass.
    unsupported: bool = False
    #: A mismatch that blocks unless explicitly accepted.
    requires_confirmation: bool = False

    def as_dict(self) -> dict:
        return {"stage": self.stage.value, "ok": self.ok, "detail": self.detail,
                "value": self.value, "unsupported": self.unsupported,
                "requires_confirmation": self.requires_confirmation}


@dataclass(frozen=True)
class DestructiveAction:
    """A destructive side effect the upstream connect path would perform."""

    name: str
    detail: str
    confirmed: bool = False

    def as_dict(self) -> dict:
        return {"name": self.name, "detail": self.detail, "confirmed": self.confirmed}


#: What ``carla_utils.connect`` does that a GUI must never do implicitly.
IMPLICIT_DESTRUCTIVE_ACTIONS: tuple[DestructiveAction, ...] = (
    DestructiveAction(
        "kill_stuck_carla",
        "carla_utils._kill_stuck_carla() kills CarlaUE4 processes "
        "(carla_utils.py:314, :411, :433)",
    ),
    DestructiveAction(
        "rmtree_carlaue4_dirs",
        "shutil.rmtree over crashes/cache/temp under the CarlaUE4 directory "
        "(carla_utils.py:168-194)",
    ),
    DestructiveAction(
        "rmtree_project_cache",
        "project cache removal on threshold breach (carla_utils.py:432-433)",
    ),
)


def confirm_destructive(action_names: list[str]) -> tuple[bool, list[str]]:
    """Typed confirmation. Returns ``(all_confirmed, unconfirmed)``."""
    known = {a.name for a in IMPLICIT_DESTRUCTIVE_ACTIONS}
    unconfirmed = [name for name in action_names if name not in known]
    return (not unconfirmed, unconfirmed)


@dataclass
class ConnectionProfile:
    host: str = "localhost"
    port: int = 2000
    expected_client_version: str = "0.9.16"
    expected_server_version: str = "0.9.16"
    allow_version_mismatch: bool = False


@dataclass
class ConnectLadder:
    """Runs the five stages and stops at the first blocking failure."""

    profile: ConnectionProfile
    stages: list[StageReport] = field(default_factory=list)

    @property
    def connected(self) -> bool:
        blocking = [s for s in self.stages if not s.ok and not s.unsupported]
        return bool(self.stages) and not blocking

    @property
    def first_failure(self) -> StageReport | None:
        for report in self.stages:
            if not report.ok and not report.unsupported:
                return report
        return None

    def as_dict(self) -> dict:
        return {"host": self.profile.host, "port": self.profile.port,
                "connected": self.connected,
                "stages": [s.as_dict() for s in self.stages]}


def connect(
    backend: Any,
    profile: ConnectionProfile | None = None,
    *,
    tick_authority: Any = None,
    destructive_confirmed: list[str] | None = None,
) -> Result:
    """Connect through the governed ladder.

    ``backend`` needs ``probe``, ``server_version``, ``available_maps``,
    ``read_settings`` and optionally ``attach_sensor`` for the canary stage.

    No destructive action is ever performed here. Confirming them is a separate
    decision recorded by :func:`confirm_destructive`; passing the confirmation
    in does not cause this function to delete anything.
    """
    prof = profile or ConnectionProfile()
    ladder = ConnectLadder(prof)

    if destructive_confirmed:
        ok, unconfirmed = confirm_destructive(destructive_confirmed)
        if not ok:
            return Result.blocked(
                f"unknown destructive action(s): {unconfirmed}",
                remediation="name only actions from IMPLICIT_DESTRUCTIVE_ACTIONS",
            )

    # 1. RPC port + handshake
    probe = backend.probe(host=prof.host, port=prof.port, timeout_s=5.0)
    ladder.stages.append(StageReport(
        ConnectStage.RPC_PORT, probe.ok, probe.reason or "rpc handshake ok", probe.value))
    if not probe.ok:
        return Result.failure(
            f"RPC port stage failed: {probe.reason}",
            error_class=probe.error_class or "ConnectionError",
            remediation="check the server is running and the port is correct",
        )

    # 2. API version -- a gate, never a swallowed warning
    server_version = None
    try:
        server_version = backend.server_version()
    except Exception as exc:
        ladder.stages.append(StageReport(
            ConnectStage.API_VERSION, False, f"version query raised: {exc}"))
        return Result.failure(
            "server did not report a version",
            error_class="VersionUnknown",
            remediation="the version gate cannot be satisfied without a version string",
        )
    if not server_version:
        ladder.stages.append(StageReport(ConnectStage.API_VERSION, False, "no version reported"))
        return Result.failure("server reported no version", error_class="VersionUnknown")

    mismatch = server_version != prof.expected_server_version
    if mismatch and not prof.allow_version_mismatch:
        ladder.stages.append(StageReport(
            ConnectStage.API_VERSION, False,
            f"server version {server_version!r} != expected "
            f"{prof.expected_server_version!r}",
            value=server_version, requires_confirmation=True))
        return Result.blocked(
            f"API version mismatch: server {server_version}, "
            f"expected {prof.expected_server_version}",
            remediation="set ConnectionProfile.allow_version_mismatch=True to accept explicitly",
        )
    ladder.stages.append(StageReport(
        ConnectStage.API_VERSION, True, "version accepted",
        value=server_version, requires_confirmation=mismatch))

    # 3. Map identity -- unsupported is not a pass
    maps = backend.available_maps()
    if maps.state == "PROBE_UNSUPPORTED":
        ladder.stages.append(StageReport(
            ConnectStage.MAP_IDENTITY, False, maps.reason, unsupported=True))
    elif maps.state == "EMPTY":
        ladder.stages.append(StageReport(
            ConnectStage.MAP_IDENTITY, False, maps.reason, value=[]))
        return Result.blocked("no maps available", remediation="load or cook a map first")
    else:
        ladder.stages.append(StageReport(
            ConnectStage.MAP_IDENTITY, True, "map list read", value=list(maps.value or [])))

    # 4. Tick authority readiness
    if tick_authority is not None and not tick_authority.may_mutate:
        ladder.stages.append(StageReport(
            ConnectStage.TICK_AUTHORITY, False,
            "session is SHARED_READONLY; simulator mutation stays disabled"))
    else:
        ladder.stages.append(StageReport(
            ConnectStage.TICK_AUTHORITY, True, "tick authority ready"))

    # 5. Sensor canary -- optional capability
    canary = getattr(backend, "attach_sensor", None)
    if canary is None:
        ladder.stages.append(StageReport(
            ConnectStage.SENSOR_CANARY, False,
            "backend exposes no sensor canary", unsupported=True))
    else:
        ladder.stages.append(StageReport(
            ConnectStage.SENSOR_CANARY, True, "canary available"))

    return Result.success(ladder.as_dict())