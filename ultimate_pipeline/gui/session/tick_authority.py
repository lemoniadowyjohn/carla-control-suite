"""Single authoritative tick ownership.

The repository has **six** known places that drive the simulator clock:

1. ``ultimate_pipeline/carla_tools/session.py``
2. ``ultimate_pipeline/**/reload_ready_for_sensors.py``
3. ``ultimate_pipeline/**/carla_sim_consolidated.py``
4. ``ultimate_pipeline/perception/**/local_perception_runner.py``
5. ``ultimate_pipeline/**/evaluate_generated_map.py``
6. ``ultimate_pipeline/core/carla_opendrive_loader.py``

Two synchronous tick owners corrupt a CARLA session. This module is the **one**
place a tick may be granted, and it fails closed: exclusive ownership that
cannot be *proven* means REFUSE, not "probably fine".

Snapshot/restore of ``synchronous_mode`` and ``fixed_delta_seconds`` is
mandatory on grant and on release, so a crash cannot leave a world in a mode
nobody asked for.

**Substepping is NOT claimed.** CARLA substepping support was not independently
verified, so no substep parameter is exposed here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ultimate_pipeline.gui.results import Result

__all__ = [
    "TickAuthority", "TickGrant", "SyncSettings", "KnownTickWriter",
    "KNOWN_TICK_WRITERS", "substep_support_verified", "TickRefusal",
]

#: The six documented writers, recorded so the conflict report can name them.
KNOWN_TICK_WRITERS: tuple[str, ...] = (
    "ultimate_pipeline/carla_tools/session.py",
    "ultimate_pipeline/reload_ready_for_sensors.py",
    "ultimate_pipeline/carla_sim_consolidated.py",
    "ultimate_pipeline/perception/local_perception_runner.py",
    "ultimate_pipeline/evaluate_generated_map.py",
    "ultimate_pipeline/core/carla_opendrive_loader.py",
)


def substep_support_verified() -> bool:
    """Substepping is deliberately NOT claimed: support is unverified."""
    return False


class TickRefusal(str, Enum):
    ALREADY_GRANTED = "ALREADY_GRANTED"
    SHARED_READONLY = "SHARED_READONLY"
    CONFLICTING_WRITER = "CONFLICTING_WRITER"
    NO_WORLD = "NO_WORLD"
    SNAPSHOT_FAILED = "SNAPSHOT_FAILED"


@dataclass(frozen=True)
class SyncSettings:
    """The two synchronous-mode settings that must be restored exactly."""

    synchronous_mode: bool
    fixed_delta_seconds: float

    def as_dict(self) -> dict:
        return {"synchronous_mode": self.synchronous_mode,
                "fixed_delta_seconds": self.fixed_delta_seconds}


@dataclass(frozen=True)
class TickGrant:
    granted: bool
    owner: str = ""
    reason: str = ""
    refusal: str = ""
    conflict_writers: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.granted


@dataclass
class TickAuthority:
    """The single grant point for simulator ticks.

    ``world`` only needs ``get_settings()`` and ``apply_settings(...)``; a mock
    satisfies both, so this is fully testable offline.
    """

    world: Any = None
    exclusive: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _owner: str = ""
    _original: SyncSettings | None = None
    _granted: bool = False
    #: Writers observed to have driven the clock outside this authority.
    external_writers: set[str] = field(default_factory=set)

    # -- state -------------------------------------------------------------
    @property
    def owner(self) -> str:
        return self._owner

    @property
    def granted(self) -> bool:
        return self._granted

    def snapshot(self) -> SyncSettings:
        """Read the current sync settings. Raises if they cannot be read."""
        settings = self.world.get_settings()
        return SyncSettings(
            synchronous_mode=bool(settings.synchronous_mode),
            fixed_delta_seconds=float(settings.fixed_delta_seconds),
        )

    def restore(self, settings: SyncSettings | None) -> bool:
        """Restore the snapshot. Returns False if restoration is impossible.

        An incomplete restore is *failure evidence*, never a success.
        """
        if settings is None:
            return False
        try:
            self.world.apply_settings(settings)
        except Exception:
            return False
        try:
            now = self.snapshot()
        except Exception:
            return False
        return (now.synchronous_mode == settings.synchronous_mode
                and abs(now.fixed_delta_seconds - settings.fixed_delta_seconds) < 1e-9)

    # -- grant -------------------------------------------------------------
    def acquire(self, owner: str) -> TickGrant:
        """Grant exclusive tick ownership, or refuse with a reason."""
        with self._lock:
            if self.world is None:
                return TickGrant(False, refusal=TickRefusal.NO_WORLD.value,
                                 reason="no world bound to this authority")
            if not self.exclusive:
                return TickGrant(False, refusal=TickRefusal.SHARED_READONLY.value,
                                 reason="SHARED_READONLY authority cannot grant tick")
            if self._granted:
                return TickGrant(False, self._owner, "tick already granted",
                                 TickRefusal.ALREADY_GRANTED.value)
            if self.external_writers:
                names = tuple(sorted(self.external_writers))
                return TickGrant(
                    False, "", "runtime conflict: another writer drives the clock",
                    TickRefusal.CONFLICTING_WRITER.value, names,
                )
            try:
                original = self.snapshot()
            except Exception as exc:
                return TickGrant(False, "", f"could not snapshot sync settings: {exc}",
                                 TickRefusal.SNAPSHOT_FAILED.value)
            self._original = original
            try:
                self.world.apply_settings(SyncSettings(True, 0.05))
            except Exception as exc:
                self._original = None
                return TickGrant(False, "", f"could not enter synchronous mode: {exc}",
                                 TickRefusal.SNAPSHOT_FAILED.value)
            self._owner = owner
            self._granted = True
            return TickGrant(True, owner)

    def release(self, owner: str = "") -> Result:
        """Release tick ownership and restore the snapshot exactly."""
        with self._lock:
            if not self._granted:
                return Result.blocked("no tick grant is held")
            if owner and owner != self._owner:
                return Result.failure(
                    f"tick held by {self._owner!r}, not {owner!r}",
                    error_class="PermissionError",
                )
            restored = self.restore(self._original)
            self._granted = False
            self._owner = ""
            self._original = None
            if not restored:
                return Result.failure(
                    "synchronous settings could NOT be restored; world left in "
                    "synchronous mode",
                    error_class="SyncRestoreError",
                    remediation="manually reset synchronous_mode and fixed_delta_seconds",
                    state_restored=False,
                )
            return Result.success(True)

    # -- conflict detection ------------------------------------------------
    def note_external_write(self, writer: str) -> None:
        """Record that ``writer`` drove the clock outside this authority."""
        with self._lock:
            if writer not in KNOWN_TICK_WRITERS:
                raise ValueError(f"{writer!r} is not a known tick writer")
            self.external_writers.add(writer)

    def conflict_report(self) -> dict:
        with self._lock:
            return {
                "granted": self._granted,
                "owner": self._owner,
                "exclusive": self.exclusive,
                "external_writers": sorted(self.external_writers),
                "known_writers": list(KNOWN_TICK_WRITERS),
                "substep_support_verified": substep_support_verified(),
            }

    # -- ticking -----------------------------------------------------------
    def tick(self, owner: str = "") -> Result:
        """Advance one frame. Only the grant holder may do this."""
        with self._lock:
            if not self._granted:
                return Result.blocked("no tick grant is held; refusing to drive the clock")
            if owner and owner != self._owner:
                return Result.blocked(
                    f"tick held by {self._owner!r}, not {owner!r}",
                    remediation="acquire the tick yourself, or coordinate with the holder",
                )
            try:
                self.world.tick()
            except Exception as exc:
                return Result.failure(
                    f"tick failed: {exc}", error_class=type(exc).__name__,
                    error_source="ultimate_pipeline/gui/session/tick_authority.py",
                    state_restored=True,
                )
            return Result.success(True)