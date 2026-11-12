"""Traffic Manager as a **requested-write ledger**.

CARLA 0.9.16 exposes no getters for most Traffic Manager setters: of the eleven
governed setters, only a handful can be read back. Therefore this module never
reports ``CONFIRMED``.

Three states only:

* ``REQUESTED``   -- we issued the write; the server gave no error.
* ``WRITE_ONLY``  -- the field is declared but provably not readable.
* ``UNVERIFIED``  -- we could not confirm, and we say so.

There is deliberately **no fabricated "restore defaults"**: CARLA cannot read the
current values, so a snapshot/restore of TM globals is impossible and pretending
otherwise would corrupt a shared session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ultimate_pipeline.gui.results import Result

__all__ = [
    "TM_SETTERS", "TM_READABLE", "TM_DECLARED_ONLY", "WriteState",
    "WriteRecord", "TrafficManagerLedger", "apply_global", "apply_vehicle",
    "AUTOPILOT_NOTE",
]

#: The eleven governed Traffic Manager setters.
TM_SETTERS: tuple[str, ...] = (
    "set_distance_to_leading_vehicle",
    "set_percentage_speed_difference",
    "set_synchronous_mode",
    "auto_lane_change",
    "ignore_lights",
    "ignore_signs",
    "ignore_walkers",
    "randomize_seed",
    "vehicle_percentage_speed_difference",
    "distance_to_leading_vehicle",
    "vehicle_light_state",
)

#: Setters CARLA 0.9.16 actually provides a getter for. Everything else is
#: write-only: we can issue it, we can never confirm it.
TM_READABLE: frozenset[str] = frozenset({
    "auto_lane_change",
    "ignore_lights",
    "ignore_signs",
    "ignore_walkers",
    "randomize_seed",
})

#: Declared upstream but not implemented (traffic_manager_session.py:136-141).
TM_DECLARED_ONLY: tuple[str, ...] = (
    "dormant_vehicle_behavior",
    "speed_policy",
    "respawn_policy",
)

#: Detaching an actor's autopilot is NOT the same as restoring TM global state.
#: The former acts on one actor; the latter is impossible without getters.
AUTOPILOT_NOTE = (
    "Detaching autopilot from an actor is an actor-scoped operation. It is NOT "
    "a restore of Traffic Manager global state, which cannot be read back in "
    "CARLA 0.9.16 and therefore cannot be restored."
)


class WriteState:
    REQUESTED = "REQUESTED"
    WRITE_ONLY = "WRITE_ONLY"
    UNVERIFIED = "UNVERIFIED"
    DECLINED = "DECLINED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class WriteRecord:
    scope: str            # "global" | "vehicle"
    target: str           # actor id, or "global"
    setter: str
    state: str
    value: Any = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {"scope": self.scope, "target": self.target, "setter": self.setter,
                "state": self.state, "value": self.value, "detail": self.detail}


@dataclass
class TrafficManagerLedger:
    """Process-side record of everything we asked the TM to do."""

    records: list[WriteRecord] = field(default_factory=list)
    port: int = 8000
    owner_token: str = ""

    @property
    def claimed(self) -> bool:
        return bool(self.owner_token)

    def by_state(self, state: str) -> list[WriteRecord]:
        return [r for r in self.records if r.state == state]

    def confirmed_count(self) -> int:
        """Always zero. CARLA 0.9.16 confirms nothing here."""
        return 0

    def as_dict(self) -> dict:
        return {"port": self.port, "owner_token": self.owner_token,
                "claimed": self.claimed, "confirmed": self.confirmed_count(),
                "records": [r.as_dict() for r in self.records]}

    def provenance(self) -> str:
        return (f"tm port {self.port}; confirmed=0 by construction "
                f"(CARLA 0.9.16 exposes no getter for these setters)")


def _state_for(setter: str, verified: bool | None) -> str:
    if verified is True:
        # Cannot happen in 0.9.16 for these setters, but keep the branch honest.
        return WriteState.REQUESTED
    if verified is False:
        return WriteState.UNVERIFIED
    return WriteState.WRITE_ONLY if setter not in TM_READABLE else WriteState.UNVERIFIED


def apply_global(ledger: TrafficManagerLedger, tm: Any, policy: dict[str, Any]) -> Result:
    """Write global TM policy. Declines when port ownership is unavailable."""
    if not ledger.claimed:
        ledger.records.append(WriteRecord(
            "global", "global", "*", WriteState.DECLINED, None,
            "Traffic Manager port ownership is not held"))
        return Result.blocked(
            "Traffic Manager port ownership unavailable",
            remediation="claim the master TM port before writing global policy")

    unknown = sorted(set(policy) - set(TM_SETTERS))
    if unknown:
        ledger.records.append(WriteRecord(
            "global", "global", ",".join(unknown), WriteState.FAILED, None,
            "unknown setter"))
        return Result.blocked(f"unknown TM setter(s): {unknown}")

    for setter in sorted(policy):
        value = policy[setter]
        method = getattr(tm, setter, None)
        if method is None or not callable(method):
            ledger.records.append(WriteRecord(
                "global", "global", setter, WriteState.FAILED, value,
                "setter is not available on this backend"))
            continue
        try:
            method(value)
        except Exception as exc:
            ledger.records.append(WriteRecord(
                "global", "global", setter, WriteState.FAILED, value,
                f"{type(exc).__name__}: {exc}"))
            continue
        ledger.records.append(WriteRecord(
            "global", "global", setter, _state_for(setter, None), value,
            "write issued; not readable back in CARLA 0.9.16"))

    return Result.success(ledger.as_dict())


def apply_vehicle(
    ledger: TrafficManagerLedger,
    tm: Any,
    actor_id: int,
    policy: dict[str, Any],
    owned_actor_ids: Iterable[int],
) -> Result:
    """Per-vehicle policy. Actor-scoped and refused for unowned actors."""
    if not ledger.claimed:
        ledger.records.append(WriteRecord(
            "vehicle", str(actor_id), "*", WriteState.DECLINED, None,
            "Traffic Manager port ownership is not held"))
        return Result.blocked(
            "Traffic Manager port ownership unavailable",
            remediation="claim the master TM port before writing per-vehicle policy")

    owned = set(owned_actor_ids)
    if actor_id not in owned:
        ledger.records.append(WriteRecord(
            "vehicle", str(actor_id), "*", WriteState.DECLINED, None,
            "actor is not in the owned registry"))
        return Result.blocked(
            f"actor {actor_id} is not owned by this session",
            remediation="per-vehicle policy may only target session-owned actors")

    unknown = sorted(set(policy) - set(TM_SETTERS))
    if unknown:
        return Result.blocked(f"unknown TM setter(s): {unknown}")

    for setter in sorted(policy):
        value = policy[setter]
        try:
            tm.set_vehicle_perfect_centering = getattr(tm, "set_vehicle_perfect_centering", False)
            getattr(tm, setter)(actor_id, value)
        except Exception as exc:
            ledger.records.append(WriteRecord(
                "vehicle", str(actor_id), setter, WriteState.FAILED, value,
                f"{type(exc).__name__}: {exc}"))
            continue
        ledger.records.append(WriteRecord(
            "vehicle", str(actor_id), setter, _state_for(setter, None), value,
            "write issued; not readable back in CARLA 0.9.16"))

    return Result.success(ledger.as_dict())


def detach_autopilot(tm: Any, actor_id: int, owned_actor_ids: Iterable[int]) -> Result:
    """Detach autopilot for ONE owned actor. Never claims to restore TM globals."""
    if actor_id not in set(owned_actor_ids):
        return Result.blocked(
            f"actor {actor_id} is not owned by this session",
            remediation=AUTOPILOT_NOTE)
    try:
        tm.set_vehicle_autopilot(actor_id, False)
    except Exception as exc:
        return Result.failure(f"autopilot detach failed: {exc}",
                              error_class=type(exc).__name__)
    return Result.success({"actor_id": actor_id, "detached": True,
                           "note": AUTOPILOT_NOTE})