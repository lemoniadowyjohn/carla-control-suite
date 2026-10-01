#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-331 / NEW-332 -- governed simulation physics and experiment-start state.

NEW-331: substepping is a governed profile, not a boolean
----------------------------------------------------------
``record_route_fixed`` explicitly set ``settings.substepping = False`` with no
profile, no budget check and no verification, and never set
``max_substep_delta_time`` / ``max_substeps`` at all.  For CARLA 0.9.16
scientific runs the profile below enables substepping with an explicit budget
and enforces the physical consistency inequality

    fixed_delta_seconds <= max_substep_delta_time * max_substeps

with a maximum desired physical substep of at most 0.01 s for the
high-fidelity profile.

NEW-332: simulation settings precede experimental actors
---------------------------------------------------------
The recorder enabled synchronous mode only *after* ego and sensors had already
been materialised, so the world advanced asynchronously while the rig was being
built.  The ordered lifecycle below is explicit, and no governed capture may
start until ``SIMULATION_STATE_READY`` is true.

Claim boundary for OpenDRIVE generation
----------------------------------------
CARLA 0.9.16 cannot hold synchronous mode across ``generate_opendrive_world`` /
``reload_world``: the world is rebuilt and settings are reset by the server.  So
for an OpenDRIVE-derived arm the supported sequence is

    load/generate world -> apply governed settings -> verify -> reseed TM ->
    deterministic warmup -> spawn actors -> attach sensors -> capture

which is exactly :data:`EXPERIMENT_START_SEQUENCE`.  The resulting claim
boundary is recorded as ``SYNC_APPLIED_POST_GENERATION``: synchrony governs the
repeatable episode, not the map-generation step itself.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional

PHYSICS_PROFILE_SCHEMA = "SIMULATION_PHYSICS_PROFILE/v1"
PHYSICS_DIGEST_FIELD = "simulation_physics_sha256"

# --- NEW-331 failure codes -------------------------------------------------
PHYSICS_SUBSTEPPING_DISABLED = "PHYSICS_SUBSTEPPING_DISABLED"
PHYSICS_SUBSTEP_BUDGET_EXCEEDED = "PHYSICS_SUBSTEP_BUDGET_EXCEEDED"
PHYSICS_SUBSTEP_TOO_COARSE = "PHYSICS_SUBSTEP_TOO_COARSE"
PHYSICS_ATTRIBUTE_UNSUPPORTED = "PHYSICS_ATTRIBUTE_UNSUPPORTED"

# --- NEW-332 failure codes -------------------------------------------------
SIMULATION_STATE_NOT_READY = "SIMULATION_STATE_NOT_READY"
SIMULATION_SETTINGS_VERIFY_FAILED = "SIMULATION_SETTINGS_VERIFY_FAILED"

#: Claim boundary for arms whose map is produced by OpenDRIVE generation.
CLAIM_SYNC_POST_GENERATION = "SYNC_APPLIED_POST_GENERATION"
CLAIM_SYNC_FROM_WORLD_LOAD = "SYNC_FROM_WORLD_LOAD"

#: The governed profile for CARLA 0.9.16 scientific runs.
HIGH_FIDELITY_PROFILE: Dict[str, Any] = {
    "profile_name": "carla_0_9_16_high_fidelity_substepped",
    "synchronous_mode": True,
    "substepping": True,
    "max_substep_delta_time": 0.01,
    "max_substeps": 10,
    "max_desired_physical_substep_s": 0.01,
    "render_blocking": False,
    "no_rendering_mode": False,
}

#: A cheaper profile retained for smoke/diagnostic runs only.  It is NOT
#: admissible for a paired scientific claim.
DIAGNOSTIC_PROFILE: Dict[str, Any] = {
    "profile_name": "diagnostic_single_step",
    "synchronous_mode": True,
    "substepping": False,
    "max_substep_delta_time": None,
    "max_substeps": None,
    "max_desired_physical_substep_s": None,
    "render_blocking": False,
    "no_rendering_mode": False,
}

PROFILES: Dict[str, Dict[str, Any]] = {
    HIGH_FIDELITY_PROFILE["profile_name"]: HIGH_FIDELITY_PROFILE,
    DIAGNOSTIC_PROFILE["profile_name"]: DIAGNOSTIC_PROFILE,
}

DEFAULT_PROFILE = HIGH_FIDELITY_PROFILE["profile_name"]

#: Ordered governed experiment-start lifecycle (NEW-332).
EXPERIMENT_START_SEQUENCE: tuple = (
    "LOAD_OR_GENERATE_INTENDED_WORLD",
    "ESTABLISH_FINAL_WORLD_IDENTITY",
    "APPLY_GOVERNED_SIMULATION_SETTINGS",
    "VERIFY_SIMULATION_SETTINGS",
    "INITIALIZE_AND_SEED_TRAFFIC_MANAGER",
    "DETERMINISTIC_WARMUP",
    "SPAWN_GOVERNED_ACTORS",
    "ATTACH_SENSORS",
    "CAPTURE",
)

SEQUENCE_STATE_KEYS: tuple = tuple(
    s for s in EXPERIMENT_START_SEQUENCE if s != "CAPTURE"
)


def _sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _round6(value: float) -> float:
    return round(float(value), 6)


# ---------------------------------------------------------------------------
# NEW-331: profile construction and validation
# ---------------------------------------------------------------------------


def build_physics_profile(
    fps: int,
    *,
    profile: str = DEFAULT_PROFILE,
    fixed_delta_seconds: Optional[float] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the governed physics profile for a capture.

    ``fixed_delta_seconds`` defaults to ``1/fps``.  The substep budget is sized
    so the fixed step is physically representable.
    """
    name = str(profile)
    if name not in PROFILES:
        raise ValueError(f"unknown_physics_profile:{name}")
    base = dict(PROFILES[name])
    base["overrides_applied"] = {}

    if fixed_delta_seconds is None:
        if int(fps) <= 0:
            raise ValueError(f"invalid_fps:{fps}")
        fixed_delta_seconds = 1.0 / float(fps)
    fixed_dt = float(fixed_delta_seconds)
    base["fixed_delta_seconds"] = _round6(fixed_dt)
    base["fps_target"] = int(fps)

    for key, value in dict(overrides or {}).items():
        base[str(key)] = value
        base["overrides_applied"][str(key)] = value

    if base.get("substepping"):
        # Size the budget so fixed_delta_seconds is representable, while never
        # exceeding the governed maximum physical substep.
        max_sub = float(base["max_desired_physical_substep_s"])
        max_dt = float(base["max_substep_delta_time"])
        max_steps = int(base["max_substeps"])
        required_steps = int(_ceil_div(fixed_dt, max_dt))
        if required_steps > max_steps:
            base["max_substeps"] = required_steps
        base["substep_budget_seconds"] = _round6(
            float(base["max_substep_delta_time"]) * float(base["max_substeps"])
        )
    else:
        base["substep_budget_seconds"] = None

    base["schema"] = PHYSICS_PROFILE_SCHEMA
    base["digest_excludes"] = ["evaluation", "settings_readback"]
    base[PHYSICS_DIGEST_FIELD] = physics_profile_sha256(base)
    return base


def physics_profile_sha256(profile: Mapping[str, Any]) -> str:
    payload = {k: v for k, v in profile.items() if k not in ("evaluation", "digest_excludes")}
    payload.pop(PHYSICS_DIGEST_FIELD, None)
    payload.pop("settings_readback", None)
    return _sha(payload)


def validate_physics_profile(
    profile: Mapping[str, Any], *, strict: bool = True
) -> Dict[str, Any]:
    """Fail-closed physics-profile validation (NEW-331).

    Rejects, under a strict scientific profile:
      * ``substepping`` disabled;
      * a fixed delta that exceeds ``max_substep_delta_time * max_substeps``;
      * a desired physical substep coarser than the governed maximum;
      * missing required attributes.
    """
    reasons: List[str] = []
    name = str(profile.get("profile_name", ""))
    strict_profile = name == HIGH_FIDELITY_PROFILE["profile_name"]

    substepping = profile.get("substepping")
    if strict and strict_profile and not bool(substepping):
        reasons.append(f"{PHYSICS_SUBSTEPPING_DISABLED}:{name}")

    fixed_dt = profile.get("fixed_delta_seconds")
    if fixed_dt is None:
        reasons.append(f"{PHYSICS_SUBSTEPPING_DISABLED}:fixed_delta_seconds_missing")
    elif substepping:
        max_dt = profile.get("max_substep_delta_time")
        max_steps = profile.get("max_substeps")
        if max_dt in (None, 0) or max_steps in (None, 0):
            reasons.append(f"{PHYSICS_ATTRIBUTE_UNSUPPORTED}:substep_budget_unset")
        else:
            budget = float(max_dt) * int(max_steps)
            if float(fixed_dt) > budget + 1e-12:
                reasons.append(
                    f"{PHYSICS_SUBSTEP_BUDGET_EXCEEDED}:"
                    f"fixed_delta_seconds={_round6(float(fixed_dt))}>"
                    f"max_substep_delta_time*max_substeps={_round6(budget)}"
                )
            desired = profile.get("max_desired_physical_substep_s")
            if desired is not None and float(desired) > 0.01 + 1e-12:
                reasons.append(
                    f"{PHYSICS_SUBSTEP_TOO_COARSE}:{_round6(float(desired))}>0.01"
                )

    if not bool(profile.get("synchronous_mode", False)) and strict:
        reasons.append(f"{SIMULATION_SETTINGS_VERIFY_FAILED}:synchronous_mode=False")

    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "profile_name": name,
        "substepping": substepping,
        "substep_budget_seconds": profile.get("substep_budget_seconds"),
        "fixed_delta_seconds": fixed_dt,
        "strict": bool(strict),
        PHYSICS_DIGEST_FIELD: str(profile.get(PHYSICS_DIGEST_FIELD, "")),
    }


def apply_physics_profile(settings: Any, profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply a governed physics profile to a CARLA ``WorldSettings``.

    Capability detection is per attribute: a setting the installed server does
    not expose is recorded rather than blindly assigned.
    """
    applied: Dict[str, Any] = {}
    unsupported: List[str] = []
    for key, value in (
        ("synchronous_mode", bool(profile.get("synchronous_mode", True))),
        ("fixed_delta_seconds", float(profile.get("fixed_delta_seconds") or 0.1)),
        ("substepping", bool(profile.get("substepping", False))),
        ("max_substep_delta_time", profile.get("max_substep_delta_time")),
        ("max_substeps", profile.get("max_substeps")),
        ("render_blocking", profile.get("render_blocking")),
        ("no_rendering_mode", profile.get("no_rendering_mode")),
    ):
        if value is None:
            continue
        if not hasattr(settings, key):
            unsupported.append(key)
            continue
        try:
            setattr(settings, key, value)
            applied[key] = value
        except Exception:
            unsupported.append(key)
    return {
        "applied": applied,
        "unsupported": sorted(unsupported),
        "required_attributes_present": not unsupported,
    }


def verify_physics_settings(
    world: Any, profile: Mapping[str, Any]
) -> Dict[str, Any]:
    """Read the world settings back and compare against the governed profile."""
    reasons: List[str] = []
    readback: Dict[str, Any] = {}
    try:
        settings = world.get_settings()
    except Exception as exc:
        return {
            "verified": False,
            "invalid_reasons": [f"{SIMULATION_SETTINGS_VERIFY_FAILED}:{exc}"],
            "readback": {},
        }
    for key in (
        "synchronous_mode", "fixed_delta_seconds", "substepping",
        "max_substep_delta_time", "max_substeps",
    ):
        want = profile.get(key)
        if want is None:
            continue
        try:
            got = getattr(settings, key)
        except Exception:
            continue
        readback[key] = got
        if isinstance(want, bool):
            if bool(got) != bool(want):
                reasons.append(f"{SIMULATION_SETTINGS_VERIFY_FAILED}:{key}:{got}!={want}")
        elif abs(float(got) - float(want)) > 1e-9:
            reasons.append(
                f"{SIMULATION_SETTINGS_VERIFY_FAILED}:{key}:{got}!={want}"
            )
    return {
        "verified": not reasons,
        "invalid_reasons": reasons,
        "readback": readback,
    }


def validate_physics_equality(
    manual_profile: Mapping[str, Any], auto_profile: Mapping[str, Any]
) -> Dict[str, Any]:
    """NEW-331: both arms must use the same physics profile digest."""
    reasons: List[str] = []
    m = str(manual_profile.get(PHYSICS_DIGEST_FIELD) or "")
    a = str(auto_profile.get(PHYSICS_DIGEST_FIELD) or "")
    if not m:
        reasons.append(f"{PHYSICS_ATTRIBUTE_UNSUPPORTED}:manual_{PHYSICS_DIGEST_FIELD}_missing")
    if not a:
        reasons.append(f"{PHYSICS_ATTRIBUTE_UNSUPPORTED}:auto_{PHYSICS_DIGEST_FIELD}_missing")
    if m and a and m != a:
        reasons.append(f"{PHYSICS_SUBSTEP_BUDGET_EXCEEDED}:profile_digest:{m}!={a}")
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "manual_simulation_physics_sha256": m,
        "auto_simulation_physics_sha256": a,
    }


def _ceil_div(a: float, b: float) -> int:
    if float(b) <= 0:
        return 0
    return int(-(-float(a) // float(b)))


# ---------------------------------------------------------------------------
# NEW-332: the experiment-start lifecycle
# ---------------------------------------------------------------------------


class ExperimentStartState:
    """Ordered, fail-closed experiment-start lifecycle.

    ``SIMULATION_STATE_READY`` becomes true only after settings have been
    applied **and** verified, and only after the traffic manager is initialised
    and seeded.  Governed capture may not begin before that.
    """

    def __init__(self, *, claim_boundary: str = CLAIM_SYNC_POST_GENERATION) -> None:
        self.claim_boundary = str(claim_boundary)
        self.stages: Dict[str, Dict[str, Any]] = {
            key: {"complete": False, "detail": None} for key in SEQUENCE_STATE_KEYS
        }
        self.order: List[str] = []
        self._violations: List[str] = []

    # -- stage marking -------------------------------------------------------

    def _require_predecessors(self, stage: str) -> None:
        index = SEQUENCE_STATE_KEYS.index(stage)
        for prior in SEQUENCE_STATE_KEYS[:index]:
            if not self.stages[prior]["complete"]:
                self._violations.append(
                    f"{stage}:out_of_order:{prior}_incomplete"
                )

    def complete(self, stage: str, detail: Any = None) -> None:
        if stage not in SEQUENCE_STATE_KEYS:
            raise ValueError(f"unknown_experiment_stage:{stage}")
        self._require_predecessors(stage)
        self.stages[stage] = {"complete": True, "detail": detail}
        if stage not in self.order:
            self.order.append(stage)

    # -- readiness -----------------------------------------------------------

    @property
    def simulation_state_ready(self) -> bool:
        required = (
            "LOAD_OR_GENERATE_INTENDED_WORLD",
            "ESTABLISH_FINAL_WORLD_IDENTITY",
            "APPLY_GOVERNED_SIMULATION_SETTINGS",
            "VERIFY_SIMULATION_SETTINGS",
            "INITIALIZE_AND_SEED_TRAFFIC_MANAGER",
        )
        return all(self.stages[k]["complete"] for k in required)

    def capture_permitted(self) -> bool:
        """Governed capture requires READY plus actor/sensor stages."""
        if not self.simulation_state_ready:
            return False
        for stage in ("DETERMINISTIC_WARMUP", "SPAWN_GOVERNED_ACTORS", "ATTACH_SENSORS"):
            if not self.stages[stage]["complete"]:
                return False
        return True

    def require_capture_ready(self) -> None:
        if not self.simulation_state_ready:
            raise RuntimeError(
                f"{SIMULATION_STATE_NOT_READY}:SIMULATION_STATE_READY=False:"
                f"incomplete={[k for k, v in self.stages.items() if not v['complete']]}"
            )

    def proof(self) -> Dict[str, Any]:
        return {
            "schema": "EXPERIMENT_START_STATE/v1",
            "SIMULATION_STATE_READY": self.simulation_state_ready,
            "capture_permitted": self.capture_permitted(),
            "claim_boundary": self.claim_boundary,
            "governed_sequence": list(EXPERIMENT_START_SEQUENCE),
            "stages": {k: dict(v) for k, v in self.stages.items()},
            "completed_order": list(self.order),
            "order_violations": list(self._violations),
            "ordering_compliant": not self._violations,
            "capture_sequence_doc": list(EXPERIMENT_START_SEQUENCE),
        }


def claim_boundary_for(map_mode: str) -> str:
    """Document the supported reset sequence per map mode (NEW-332)."""
    if str(map_mode).lower() in ("builtin", "cooked", "town"):
        return CLAIM_SYNC_FROM_WORLD_LOAD
    return CLAIM_SYNC_POST_GENERATION


def evaluate_start_state_transcript(
    proof: Mapping[str, Any]
) -> Dict[str, Any]:
    """Fail-closed evaluation of a recorded lifecycle proof."""
    reasons: List[str] = []
    if not bool(proof.get("SIMULATION_STATE_READY")):
        reasons.append(f"{SIMULATION_STATE_NOT_READY}:SIMULATION_STATE_READY=False")
    if not bool(proof.get("ordering_compliant", True)):
        reasons.append(
            f"{SIMULATION_STATE_NOT_READY}:order_violations="
            f"{proof.get('order_violations')}"
        )
    stages = dict(proof.get("stages") or {})
    for stage in SEQUENCE_STATE_KEYS:
        if stage not in stages:
            reasons.append(f"{SIMULATION_STATE_NOT_READY}:missing_stage:{stage}")
        elif not bool(stages[stage].get("complete")):
            reasons.append(f"{SIMULATION_STATE_NOT_READY}:incomplete_stage:{stage}")
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "SIMULATION_STATE_READY": bool(proof.get("SIMULATION_STATE_READY")),
        "claim_boundary": proof.get("claim_boundary"),
    }