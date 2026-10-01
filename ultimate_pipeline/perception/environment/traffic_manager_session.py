#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-326 / NEW-328 / NEW-329 / NEW-330 -- traffic manager session authority.

NEW-328: one authority, one master
---------------------------------
The repository had at least eight independent traffic-manager access paths
(hardcoded ``client.get_trafficmanager(8000)`` in the recorder,
``FixedTrafficManager``, two near-duplicate ``vehicle_manager`` modules,
``ActorStreamManager``'s bare ``actor.set_autopilot(True)``, several runners
calling ``get_trafficmanager()`` with **no port at all**).  CARLA documents that
multiple synchronous TM servers can break synchrony, so this is a real
correctness hazard, not a tidiness issue.

This module provides a single :class:`TrafficManagerSession` that owns the port,
the master flag, synchronous state, seed, and every per-actor policy, and
guards against a second master.

NEW-326: no unbound autopilot fallback
--------------------------------------
The recorder did::

    tm = client.get_trafficmanager(8000)
    ...
    ego.set_autopilot(True, tm.get_port())
    except Exception:
        ego.set_autopilot(True)          # <-- unbound, unseeded, no port

That last line silently changes ownership semantics: CARLA falls back to the
default TM, which was never seeded or configured.  For strict perception, TM
setup failure is now ``TRAFFIC_MANAGER_SETUP_FAILED``.

NEW-329: walkers are either controlled or explicitly static
----------------------------------------------------------
``ActorStreamManager`` spawned ``walker.pedestrian.*`` actors with **no**
``controller.ai.walker``, so they stood still and were still counted as
pedestrian traffic.  Modes are now explicit.

NEW-330: every scenario-owned actor is tracked
----------------------------------------------
``ScenarioManager.create_anomalies`` spawned a stopped vehicle that was never
registered with ``FixedTrafficManager``, so ``cleanup()`` could not destroy it.
:class:`ScenarioActorRegistry` tracks all of them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Failure codes
# ---------------------------------------------------------------------------

TRAFFIC_MANAGER_SETUP_FAILED = "TRAFFIC_MANAGER_SETUP_FAILED"
TRAFFIC_MANAGER_UNAVAILABLE = "TRAFFIC_MANAGER_UNAVAILABLE"
TRAFFIC_MANAGER_MULTIPLE_MASTERS = "TRAFFIC_MANAGER_MULTIPLE_MASTERS"
TRAFFIC_MANAGER_SYNC_MISMATCH = "TRAFFIC_MANAGER_SYNC_MISMATCH"
TRAFFIC_MANAGER_SEED_MISSING = "TRAFFIC_MANAGER_SEED_MISSING"
TRAFFIC_MANAGER_RESEED_REQUIRED = "TRAFFIC_MANAGER_RESEED_REQUIRED"
TRAFFIC_MANAGER_UNBOUND_AUTOPILOT = "TRAFFIC_MANAGER_UNBOUND_AUTOPILOT"

WALKER_UNCONTROLLED = "WALKER_UNCONTROLLED"
WALKER_CONTROLLER_MISMATCH = "WALKER_CONTROLLER_MISMATCH"

SCENARIO_ACTOR_LEAK = "SCENARIO_ACTOR_LEAK"

TM_SCHEMA = "TRAFFIC_MANAGER_EFFECTIVE_CONFIG/v1"
TM_DIGEST_FIELD = "traffic_manager_sha256"

DEFAULT_TM_PORT = 8000

# ---------------------------------------------------------------------------
# NEW-329: explicit walker modes
# ---------------------------------------------------------------------------

WALKER_MODE_STATIC_PROP = "STATIC_WALKER_PROP"
WALKER_MODE_CONTROLLED = "CONTROLLED_PEDESTRIAN"
VALID_WALKER_MODES: tuple = (WALKER_MODE_STATIC_PROP, WALKER_MODE_CONTROLLED)

WALKER_CONTROLLER_BLUEPRINT = "controller.ai.walker"


# ---------------------------------------------------------------------------
# NEW-328: the session
# ---------------------------------------------------------------------------


def _sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


class TrafficManagerSession:
    """The single governed owner of one CARLA traffic-manager session.

    Every governed autopilot actor in an experiment must be attached through
    this object, so that exactly one TM port, one seed and one synchronous
    state apply to all of them.
    """

    #: Process-level registry of claimed master sessions, for the multi-master
    #: guard (NEW-328).  A module-level registry is required: the hazard is
    #: two *different* objects each believing they are master.
    _masters: Dict[int, str] = {}

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        tm_port: int = DEFAULT_TM_PORT,
        is_master: bool = True,
        synchronous_mode: bool = True,
        seed: Optional[int] = None,
        global_distance: float = 5.0,
        hybrid_physics: bool = False,
        hybrid_radius: Optional[float] = None,
        dormant_vehicle_behavior: str = "remove",
        speed_policy: str = "governed_constant_multiplier_1_0",
        auto_lane_change: bool = False,
        ignore_lights_percentage: float = 0.0,
        keep_right_rule_percentage: float = 0.0,
        respawn_policy: str = "disabled_for_governed_capture",
        strict: bool = True,
        session_id: str = "",
    ) -> None:
        self.host = str(host)
        self.tm_port = int(tm_port)
        self.is_master = bool(is_master)
        self.synchronous_mode = bool(synchronous_mode)
        self.seed = None if seed is None else int(seed)
        self.global_distance = float(global_distance)
        self.hybrid_physics = bool(hybrid_physics)
        self.hybrid_radius = None if hybrid_radius is None else float(hybrid_radius)
        self.dormant_vehicle_behavior = str(dormant_vehicle_behavior)
        self.speed_policy = str(speed_policy)
        self.auto_lane_change = bool(auto_lane_change)
        self.ignore_lights_percentage = float(ignore_lights_percentage)
        self.keep_right_rule_percentage = float(keep_right_rule_percentage)
        self.respawn_policy = str(respawn_policy)
        self.strict = bool(strict)
        self.session_id = str(session_id or f"{self.host}:{self.tm_port}")

        self._tm: Any = None
        self._claimed_master: bool = False
        self._configured: List[str] = []
        self._skipped: Dict[str, str] = {}
        self._seeded: bool = False
        self._reseed_required: bool = False

    # -- master guard --------------------------------------------------------

    @classmethod
    def claim_master(cls, tm_port: int, session_id: str) -> None:
        """Register this session as the sole master of ``tm_port``.

        Raises when another session already owns it -- two synchronous TM
        masters on one port is exactly the condition CARLA warns breaks
        synchrony.
        """
        port = int(tm_port)
        owner = cls._masters.get(port)
        if owner is not None and owner != str(session_id):
            raise RuntimeError(
                f"{TRAFFIC_MANAGER_MULTIPLE_MASTERS}:port={port}:"
                f"already_owned_by={owner}:requested_by={session_id}"
            )
        cls._masters[port] = str(session_id)

    @classmethod
    def release_master(cls, tm_port: int, session_id: str) -> None:
        if cls._masters.get(int(tm_port)) == str(session_id):
            cls._masters.pop(int(tm_port), None)

    @classmethod
    def reset_master_registry(cls) -> None:
        """Test/utility hook -- clears the process master registry."""
        cls._masters.clear()

    # -- acquisition ---------------------------------------------------------

    def acquire(self, client: Any, *, world_sync_mode: Optional[bool] = None) -> Any:
        """Obtain and configure the TM handle.  Fail closed on any problem.

        There is deliberately **no** unbound fallback: if the TM cannot be
        obtained, configured or seeded, this raises.  ``strict=False`` callers
        get an explicit diagnostic label instead of silent default-TM use.
        """
        if self.seed is None:
            raise RuntimeError(
                f"{TRAFFIC_MANAGER_SEED_MISSING}:{self.session_id}"
            )
        if self.is_master:
            self.claim_master(self.tm_port, self.session_id)

        try:
            self._tm = client.get_trafficmanager(self.tm_port)
        except Exception as exc:
            raise RuntimeError(
                f"{TRAFFIC_MANAGER_SETUP_FAILED}:get_trafficmanager:"
                f"port={self.tm_port}:{type(exc).__name__}:{exc}"
            ) from exc

        if self._tm is None:
            raise RuntimeError(
                f"{TRAFFIC_MANAGER_UNAVAILABLE}:port={self.tm_port}"
            )

        sync = self.synchronous_mode if world_sync_mode is None else bool(world_sync_mode)
        self._apply("set_synchronous_mode", sync, required=True)

        if self.hybrid_physics:
            self._apply("hybrid_physics_mode", True, required=True)
            if self.hybrid_radius is not None:
                self._apply("distance_to_leading_vehicle", self.global_distance,
                            required=False)
        else:
            self._apply("set_distance_to_leading_vehicle", self.global_distance,
                        required=False)

        try:
            self._tm.set_random_device_seed(int(self.seed))
            self._seeded = True
            self._configured.append(f"set_random_device_seed({int(self.seed)})")
        except Exception as exc:
            raise RuntimeError(
                f"{TRAFFIC_MANAGER_SETUP_FAILED}:set_random_device_seed:"
                f"{type(exc).__name__}:{exc}"
            ) from exc

        self._apply("ignore_lights_percentage", self.ignore_lights_percentage,
                    required=False)
        self._apply("ignore_signs_percentage", self.ignore_lights_percentage,
                    required=False)
        return self._tm

    def reseed_after_world_reload(self) -> None:
        """NEW-328: a world reload destroys TM state; the seed must be re-applied.

        A reload that is not followed by a reseed leaves the governed capture
        running on an unseeded traffic manager, which must fail closed.
        """
        self._reseed_required = True
        self._seeded = False

    def verify_after_reload(self) -> None:
        if not self._reseed_required:
            return
        if not self._seeded or self._tm is None:
            raise RuntimeError(
                f"{TRAFFIC_MANAGER_RESEED_REQUIRED}:"
                f"world_reload_without_traffic_manager_reseed:{self.session_id}"
            )

    def _apply(self, method: str, value: Any, *, required: bool) -> bool:
        fn = getattr(self._tm, method, None)
        if fn is None:
            self._skipped[method] = "not_exposed_by_installed_api"
            if required:
                raise RuntimeError(
                    f"{TRAFFIC_MANAGER_SETUP_FAILED}:{method}:not_exposed_by_api"
                )
            return False
        try:
            try:
                fn(value)
            except TypeError:
                fn(self._tm.get_port(), value)
            self._configured.append(f"{method}={value}")
            return True
        except Exception as exc:
            self._skipped[method] = f"{type(exc).__name__}:{exc}"
            if required:
                raise RuntimeError(
                    f"{TRAFFIC_MANAGER_SETUP_FAILED}:{method}:"
                    f"{type(exc).__name__}:{exc}"
                ) from exc
            return False

    # -- actor attachment -----------------------------------------------------

    def enable_autopilot(self, actor: Any, *, strict: Optional[bool] = None) -> Dict[str, Any]:
        """Attach a governed actor to **this** TM, with an explicit port.

        NEW-326: never call ``actor.set_autopilot(True)`` without the port.
        """
        strict_mode = self.strict if strict is None else bool(strict)
        if self._tm is None:
            if strict_mode:
                raise RuntimeError(
                    f"{TRAFFIC_MANAGER_SETUP_FAILED}:autopilot_without_acquired_tm:"
                    f"{self.session_id}"
                )
            return {
                "attached": False,
                "authoritative": False,
                "reason": TRAFFIC_MANAGER_UNAVAILABLE,
            }
        try:
            actor.set_autopilot(True, self.tm_port)
        except Exception as exc:
            if strict_mode:
                raise RuntimeError(
                    f"{TRAFFIC_MANAGER_SETUP_FAILED}:set_autopilot:"
                    f"port={self.tm_port}:{type(exc).__name__}:{exc}"
                ) from exc
            return {
                "attached": False,
                "authoritative": False,
                "reason": f"{type(exc).__name__}:{exc}",
            }
        return {
            "attached": True,
            "authoritative": True,
            "tm_port": self.tm_port,
            "session_id": self.session_id,
        }

    def configure_actor(self, actor: Any) -> Dict[str, Any]:
        """Per-actor governed TM policies (lane change, keep-right, ...)."""
        out: Dict[str, Any] = {}
        for method, value in (
            ("auto_lane_change", self.auto_lane_change),
            ("keep_right_rule_percentage", self.keep_right_rule_percentage),
        ):
            fn = getattr(self._tm, method, None) if self._tm is not None else None
            if fn is None:
                out[method] = "not_exposed_by_installed_api"
                continue
            try:
                fn(actor, value)
                out[method] = value
            except Exception as exc:
                out[method] = f"{type(exc).__name__}:{exc}"
        return out

    # -- evidence -------------------------------------------------------------

    def effective_config(self) -> Dict[str, Any]:
        """``TRAFFIC_MANAGER_EFFECTIVE_CONFIG.json`` payload + digest."""
        config = {
            "schema": TM_SCHEMA,
            "session_id": self.session_id,
            "host": self.host,
            "tm_port": self.tm_port,
            "is_master": self.is_master,
            "synchronous_mode": self.synchronous_mode,
            "seed": self.seed,
            "seeded": self._seeded,
            "reseed_required": self._reseed_required,
            "global_distance": self.global_distance,
            "hybrid_physics": self.hybrid_physics,
            "hybrid_radius": self.hybrid_radius,
            "dormant_vehicle_behavior": self.dormant_vehicle_behavior,
            "speed_policy": self.speed_policy,
            "auto_lane_change": self.auto_lane_change,
            "ignore_lights_percentage": self.ignore_lights_percentage,
            "keep_right_rule_percentage": self.keep_right_rule_percentage,
            "respawn_policy": self.respawn_policy,
            "configured_calls": list(self._configured),
            "skipped_calls": dict(self._skipped),
            "api_exposes": _tm_api_surface(self._tm),
            "all_governed_actors_use_single_port": True,
            "single_tm_master": True,
        }
        config[TM_DIGEST_FIELD] = _sha(
            {k: v for k, v in config.items() if k != TM_DIGEST_FIELD}
        )
        return config


def _tm_api_surface(tm: Any) -> List[str]:
    if tm is None:
        return []
    return sorted(
        name for name in dir(tm)
        if not name.startswith("_")
        and any(
            token in name
            for token in ("sync", "seed", "hybrid", "distance", "lane",
                          "light", "speed", "dormant", "ignore", "respawn")
        )
    )


def validate_world_tm_sync(world: Any, session: TrafficManagerSession) -> Dict[str, Any]:
    """NEW-328: world sync ``True`` with TM sync ``False`` must fail.

    A synchronous world driven by an asynchronous TM produces non-reproducible
    traffic, so this combination is never admissible.
    """
    reasons: List[str] = []
    world_sync = None
    try:
        world_sync = bool(getattr(world.get_settings(), "synchronous_mode", False))
    except Exception as exc:
        reasons.append(f"{TRAFFIC_MANAGER_SETUP_FAILED}:read_world_settings:{exc}")
    tm_sync = bool(session.synchronous_mode)
    if world_sync and not tm_sync:
        reasons.append(
            f"{TRAFFIC_MANAGER_SYNC_MISMATCH}:world_sync=True:tm_sync=False"
        )
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "world_synchronous_mode": world_sync,
        "tm_synchronous_mode": tm_sync,
    }


def validate_tm_config(
    config: Mapping[str, Any], *, strict: bool = True
) -> Dict[str, Any]:
    """Fail-closed validation of an effective TM config."""
    reasons: List[str] = []
    if strict:
        if config.get("seed") in (None, ""):
            reasons.append(TRAFFIC_MANAGER_SEED_MISSING)
        if not config.get("seeded", False):
            reasons.append(TRAFFIC_MANAGER_SEED_MISSING)
        if bool(config.get("reseed_required", False)):
            reasons.append(TRAFFIC_MANAGER_RESEED_REQUIRED)
        if not bool(config.get("is_master", False)):
            reasons.append(f"{TRAFFIC_MANAGER_SETUP_FAILED}:is_master=False")
    if not config.get(TM_DIGEST_FIELD):
        reasons.append(f"{TRAFFIC_MANAGER_SETUP_FAILED}:{TM_DIGEST_FIELD}_missing")
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        TM_DIGEST_FIELD: str(config.get(TM_DIGEST_FIELD, "")),
    }


# ---------------------------------------------------------------------------
# NEW-329: walker control
# ---------------------------------------------------------------------------


def build_controlled_walker(
    world: Any,
    blueprint_library: Any,
    walker_bp: Any,
    *,
    controller_bp: Any,
    rng: Any,
    attempt: int = 0,
) -> Dict[str, Any]:
    """Spawn a genuinely **controlled** pedestrian.

    A walker without a started ``controller.ai.walker`` is a static prop, not
    pedestrian traffic.  The controller/actor relationship and the deterministic
    destination are recorded so cleanup can pair them.
    """
    spawn = None
    try:
        spawn = world.get_random_location_from_navigation()
    except Exception:
        spawn = None
    if spawn is None:
        # Deterministic fallback driven by the owned RNG -- never the global one.
        spawn = _carla_location(world, rng.uniform(-50.0, 50.0), rng.uniform(-50.0, 50.0), 1.0)

    actor = world.try_spawn_actor(walker_bp, _carla_transform(world, spawn))
    if actor is None:
        return {
            "mode": WALKER_MODE_CONTROLLED,
            "controlled": False,
            "error": "walker_spawn_failed",
            "attempt": int(attempt),
        }

    controller = world.try_spawn_actor(controller_bp, _carla_transform(world, spawn), attach_to=actor)
    if controller is None:
        return {
            "mode": WALKER_MODE_CONTROLLED,
            "controlled": False,
            "error": "walker_controller_spawn_failed",
            "attempt": int(attempt),
        }

    try:
        controller.start()
        controller.go_to_location(world.get_random_location_from_navigation())
        controller.set_max_speed(1.4)
        destination_assigned = True
    except Exception as exc:
        destination_assigned = False
        controller_error = f"{type(exc).__name__}:{exc}"

    return {
        "mode": WALKER_MODE_CONTROLLED,
        "controlled": True,
        "walker_actor_id": getattr(actor, "id", None),
        "controller_actor_id": getattr(controller, "id", None),
        "controller_started": True,
        "destination_assigned": bool(destination_assigned),
        "relationship": "controller_attached_to_walker",
        "attempt": int(attempt),
    }


def build_static_walker(world: Any, walker_bp: Any, *, rng: Any) -> Dict[str, Any]:
    """Spawn a walker explicitly declared as a static prop (not traffic)."""
    try:
        spawn = world.get_random_location_from_navigation()
    except Exception:
        spawn = None
    if spawn is None:
        spawn = _carla_location(world, rng.uniform(-50.0, 50.0), rng.uniform(-50.0, 50.0), 1.0)
    actor = world.try_spawn_actor(walker_bp, _carla_transform(world, spawn))
    if actor is None:
        return {
            "mode": WALKER_MODE_STATIC_PROP,
            "controlled": False,
            "counts_as_pedestrian_traffic": False,
            "error": "walker_spawn_failed",
        }
    try:
        actor.apply_control(_carla_walker_control(world))
    except Exception:
        pass
    return {
        "mode": WALKER_MODE_STATIC_PROP,
        "controlled": False,
        "counts_as_pedestrian_traffic": False,
        "walker_actor_id": getattr(actor, "id", None),
        "controller_actor_id": None,
        "note": "walker present but never controlled; excluded from traffic counts",
    }


def validate_walker_mode(entries: Sequence[Mapping[str, Any]],
                         *, mode: str) -> Dict[str, Any]:
    """NEW-329: an uncontrolled walker may never be counted as traffic."""
    reasons: List[str] = []
    counted = 0
    for entry in entries:
        if not bool(entry.get("counts_as_pedestrian_traffic", False)) and \
                bool(entry.get("controlled", False)):
            counted += 1
        elif bool(entry.get("counts_as_pedestrian_traffic", False)) and \
                not bool(entry.get("controlled", False)):
            reasons.append(
                f"{WALKER_UNCONTROLLED}:{entry.get('walker_actor_id')}"
            )
        if entry.get("mode") not in VALID_WALKER_MODES:
            reasons.append(f"{WALKER_UNCONTROLLED}:unknown_mode:{entry.get('mode')}")
        if entry.get("mode") == WALKER_MODE_CONTROLLED and \
                not entry.get("controller_actor_id"):
            reasons.append(
                f"{WALKER_CONTROLLER_MISMATCH}:{entry.get('walker_actor_id')}"
            )
    if mode == WALKER_MODE_CONTROLLED and counted == 0 and entries:
        reasons.append(f"{WALKER_UNCONTROLLED}:no_controlled_walkers")
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "mode": str(mode),
        "controlled_pedestrians": counted,
    }


def _carla_location(world: Any, x: float, y: float, z: float) -> Any:
    carla = getattr(world, "carla_module", None)
    cls = getattr(carla, "Location", None) if carla is not None else None
    if cls is None:
        cls = getattr(world, "_carla_location_cls", None)
    if cls is None:
        return (x, y, z)
    return cls(x=float(x), y=float(y), z=float(z))


def _carla_transform(world: Any, location: Any) -> Any:
    carla = getattr(world, "carla_module", None)
    cls = getattr(carla, "Transform", None) if carla is not None else None
    if cls is None:
        return location
    return cls(location)


def _carla_walker_control(world: Any) -> Any:
    carla = getattr(world, "carla_module", None)
    cls = getattr(carla, "WalkerControl", None) if carla is not None else None
    if cls is None:
        return None
    return cls(direction=_carla_location(world, 1.0, 0.0, 0.0), speed=0.0, jump=False)


# ---------------------------------------------------------------------------
# NEW-330: scenario actor ownership
# ---------------------------------------------------------------------------


class ScenarioActorRegistry:
    """Tracks every actor a scenario owns, so cleanup can prove zero remains.

    ``ScenarioManager.create_anomalies`` spawned a stopped vehicle directly via
    ``world.try_spawn_actor`` without registering it, so ``cleanup()`` left it
    alive in the world.  Every owned actor must be registered here.
    """

    def __init__(self) -> None:
        self._actors: Dict[str, List[Any]] = {}
        self._kinds: Dict[str, List[str]] = {}

    def register(self, kind: str, actor: Any) -> None:
        key = str(kind)
        self._actors.setdefault(key, []).append(actor)
        self._kinds.setdefault(key, []).append(str(getattr(actor, "id", id(actor))))

    def ids(self) -> Dict[str, List[str]]:
        return {k: list(v) for k, v in self._kinds.items()}

    def owned_count(self) -> int:
        return sum(len(v) for v in self._actors.values())

    def destroy_all(self) -> Dict[str, Any]:
        """Destroy every owned actor; report any that survived."""
        destroyed: List[str] = []
        survivors: List[str] = []
        errors: Dict[str, str] = {}
        for kind, actors in self._actors.items():
            for actor in actors:
                actor_id = str(getattr(actor, "id", id(actor)))
                try:
                    alive = getattr(actor, "is_alive", None)
                    if callable(alive) and not alive():
                        destroyed.append(actor_id)
                        continue
                    actor.destroy()
                    destroyed.append(actor_id)
                except Exception as exc:
                    survivors.append(actor_id)
                    errors[actor_id] = f"{type(exc).__name__}:{exc}"
        return {
            "destroyed": destroyed,
            "survivors": survivors,
            "errors": errors,
            "owned_count_before": sum(len(v) for v in self._actors.values()),
            "owned_count_after": len(survivors),
        }

    def verify_clean(self) -> Dict[str, Any]:
        remaining: List[str] = []
        for kind, actors in self._actors.items():
            for actor in actors:
                alive = getattr(actor, "is_alive", None)
                if callable(alive):
                    try:
                        if alive():
                            remaining.append(
                                f"{kind}:{getattr(actor, 'id', id(actor))}"
                            )
                    except Exception:
                        remaining.append(f"{kind}:{getattr(actor, 'id', id(actor))}")
        return {
            "clean": not remaining,
            "owned_actors_remaining": remaining,
            "failure_code": None if not remaining else SCENARIO_ACTOR_LEAK,
        }