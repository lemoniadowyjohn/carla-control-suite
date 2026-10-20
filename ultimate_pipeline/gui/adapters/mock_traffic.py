"""Deterministic ``TrafficManagerBackend`` mock.

Mirrors ``TrafficManagerBackend``: ``claim``/``release``,
``apply_global``/``apply_vehicle``, ``ledger``, ``api_surface`` and
``declared_only``.

Two documented realities are reproduced deliberately, because the GUI must
surface them rather than hide them:

* ``apply_global`` returns ``readable_back=False`` -- the Traffic Manager does
  not read its own settings back.
* ``dormant_vehicle_behavior``, ``speed_policy`` and ``respawn_policy`` are
  declared in the source but not implemented upstream, so the mock reports them
  as *declared only*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ultimate_pipeline.gui.results import Result

__all__ = ["MockTrafficManagerBackend", "TmClaim", "TmPolicy", "TmReceipt",
           "DECLARED_ONLY"]

#: Declared upstream but not implemented (traffic_manager_session.py:136-141).
DECLARED_ONLY = ("dormant_vehicle_behavior", "speed_policy", "respawn_policy")

_API_SURFACE = {
    "set_distance_to_leading_vehicle": True,
    "set_percentage_speed_difference": True,
    "set_synchronous_mode": True,
    "auto_lane_change": True,
    "ignore_lights": True,
    "ignore_signs": True,
    "ignore_walkers": True,
    "randomize_seed": True,
    "distance_to_leading_vehicle": False,
    "vehicle_percentage_speed_difference": False,
}


@dataclass(frozen=True)
class TmClaim:
    owner_token: str
    port: int
    acquired: bool
    conflict_holder: str = ""


@dataclass(frozen=True)
class TmPolicy:
    percentage_speed_difference: float = 0.0
    auto_lane_change: bool = True
    ignore_lights: bool = False
    ignore_signs: bool = False


@dataclass(frozen=True)
class TmReceipt:
    scope: str
    actor_id: int
    applied: bool
    readable_back: bool = False
    detail: str = ""


class MockTrafficManagerBackend:
    """Offline Traffic Manager stand-in with genuine conflict semantics."""

    def __init__(self, default_port: int = 8000) -> None:
        self.default_port = default_port
        self._claim: TmClaim | None = None
        self._ledger: list[TmReceipt] = []
        self._owned_actors: set[int] = set()

    # -- authority ---------------------------------------------------------
    def claim(self, owner_token: str, port: int = 8000) -> TmClaim:
        if self._claim is not None and self._claim.acquired:
            return TmClaim(owner_token, port, False, self._claim.owner_token)
        self._claim = TmClaim(owner_token, port, True)
        return self._claim

    def release(self, claim: TmClaim) -> Result:
        if self._claim is None or not self._claim.acquired:
            return Result.failure("no Traffic Manager claim is held")
        if claim.owner_token != self._claim.owner_token:
            return Result.failure(
                f"claim held by {self._claim.owner_token!r}",
                error_class="PermissionError",
            )
        self._claim = None
        return Result.success(True)

    @property
    def claim_holder(self) -> str:
        return self._claim.owner_token if self._claim and self._claim.acquired else ""

    # -- application -------------------------------------------------------
    def apply_global(self, claim: TmClaim, policy: TmPolicy) -> Result:
        verified = self._verify(claim)
        if verified is not None:
            return verified
        receipt = TmReceipt("global", 0, True, readable_back=False,
                            detail="Traffic Manager does not read its own settings back")
        self._ledger.append(receipt)
        return Result.success(receipt)

    def apply_vehicle(self, claim: TmClaim, actor_id: int, policy: TmPolicy) -> Result:
        verified = self._verify(claim)
        if verified is not None:
            return verified
        if actor_id not in self._owned_actors:
            return Result.failure(
                f"actor {actor_id} is not in the owned registry",
                error_class="RuntimeError",
                remediation="spawn the actor through this session first",
            )
        receipt = TmReceipt("vehicle", actor_id, True, readable_back=False,
                            detail="not readable back")
        self._ledger.append(receipt)
        return Result.success(receipt)

    def register_owned_actor(self, actor_id: int) -> None:
        """Mirror the session-owned actor registry the TM adapter consults."""
        self._owned_actors.add(actor_id)

    # -- introspection -----------------------------------------------------
    def ledger(self) -> list[TmReceipt]:
        return list(self._ledger)

    def api_surface(self) -> dict[str, bool]:
        return dict(_API_SURFACE)

    def declared_only(self) -> list[str]:
        return list(DECLARED_ONLY)

    def _verify(self, claim: TmClaim) -> Result | None:
        if self._claim is None or not self._claim.acquired:
            return Result.blocked("no Traffic Manager claim is held",
                                  remediation="claim the TM master port first")
        if claim.owner_token != self._claim.owner_token:
            return Result.blocked(
                f"TM port {self._claim.port} is claimed by {self._claim.owner_token!r}",
                remediation="release the existing claim or choose another port",
            )
        return None