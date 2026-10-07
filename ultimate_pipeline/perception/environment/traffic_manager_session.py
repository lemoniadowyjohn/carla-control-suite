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
import os
import time
import uuid
from threading import Lock
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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
WALKER_TRANSACTION_FAILED = "WALKER_TRANSACTION_FAILED"
WALKER_POSITION_UNGOVERNED = "WALKER_POSITION_UNGOVERNED"

SCENARIO_ACTOR_LEAK = "SCENARIO_ACTOR_LEAK"

TM_ACTOR_LEDGER_SCHEMA = "TRAFFIC_MANAGER_ACTOR_LEDGER/v1"
TM_OWNERSHIP_SCHEMA = "TRAFFIC_MANAGER_OWNERSHIP/v1"
WALKER_SCENARIO_MANIFEST_SCHEMA = "WALKER_SCENARIO_MANIFEST/v1"

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
    #:
    #: The value is an owner TOKEN, not the human-readable session label. The
    #: previous registry stored ``session_id``, whose default is
    #: ``f"{host}:{tm_port}"`` -- so two different session objects that merely
    #: shared host and port compared EQUAL and the second claim silently
    #: succeeded. Reusing a human-readable label must never bypass exclusivity.
    _masters: Dict[int, Dict[str, Any]] = {}

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
        run_uuid: str = "",
        owner_token: str = "",
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
        # A reused human-readable label is metadata only; it carries no
        # ownership authority.
        self.session_id = str(session_id or f"{self.host}:{self.tm_port}")
        self.run_uuid = str(run_uuid or uuid.uuid4().hex)
        self.owner_token = str(owner_token or f"{self.run_uuid}:{uuid.uuid4().hex}")
        self.process_id = int(os.getpid())
        self.created_at = time.time()
        self.closed: bool = False
        self.closed_at: Optional[float] = None

        self._tm: Any = None
        self._claimed_master: bool = False
        self._configured: List[str] = []
        self._skipped: Dict[str, str] = {}
        self._seeded: bool = False
        self._reseed_required: bool = False
        #: Governed actor ledger (NEW-326 evidence). Claims are derived from it.
        self._actor_ledger: List[Dict[str, Any]] = []
        self._ledger_lock_obj: Optional[Lock] = None

    # -- master guard --------------------------------------------------------

    @classmethod
    def claim_master(
        cls,
        tm_port: int,
        session_id: str,
        *,
        owner_token: str = "",
        run_uuid: str = "",
        process_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Register this session as the sole master of ``tm_port``.

        Exclusivity is keyed on ``owner_token`` (cross-checked against
        ``run_uuid``), never on the human-readable ``session_id``. Two distinct
        session objects sharing host:port therefore still conflict, and a reused
        label cannot defeat the guard.
        """
        port = int(tm_port)
        token = str(owner_token or session_id)
        record = {
            "owner_token": token,
            "run_uuid": str(run_uuid or ""),
            "session_id": str(session_id),
            "process_id": int(process_id if process_id is not None else os.getpid()),
            "claimed_at": time.time(),
        }
        existing = cls._masters.get(port)
        if existing is not None:
            same_owner = (
                str(existing.get("owner_token")) == token
                and str(existing.get("run_uuid")) == record["run_uuid"]
            )
            if not same_owner:
                raise RuntimeError(
                    f"{TRAFFIC_MANAGER_MULTIPLE_MASTERS}:port={port}:"
                    f"already_owned_by_token={existing.get('owner_token')}:"
                    f"already_owned_by_run={existing.get('run_uuid')}:"
                    f"requested_by_token={token}:requested_by_run={record['run_uuid']}"
                )
        cls._masters[port] = record
        return dict(record)

    @classmethod
    def release_master(cls, tm_port: int, owner_token: str = "", session_id: str = "") -> bool:
        """Release the master claim. True when a claim was actually removed."""
        port = int(tm_port)
        record = cls._masters.get(port)
        if record is None:
            return False
        token = str(owner_token or session_id)
        if str(record.get("owner_token")) != token:
            return False
        cls._masters.pop(port, None)
        return True

    @classmethod
    def master_registry_snapshot(cls) -> Dict[str, Any]:
        return {str(port): dict(record) for port, record in sorted(cls._masters.items())}

    @classmethod
    def reset_master_registry(cls) -> None:
        """Test/utility hook -- clears the process master registry."""
        cls._masters.clear()

    # -- transactional lifecycle -------------------------------------------

    def _ledger_lock(self) -> Lock:
        if self._ledger_lock_obj is None:
            self._ledger_lock_obj = Lock()
        return self._ledger_lock_obj

    def close(self, *, detach_autopilot: bool = True) -> Dict[str, Any]:
        """Release every resource this session claimed. Safe to call twice.

        Every acquired master claim must be released on *every* exit path:
        normal completion, setup failure, capture failure, sensor failure, route
        failure, exception and cleanup. Callers should use ``with`` so an
        exception cannot leak the claim; this method is the non-context-manager
        equivalent and is also invoked by ``__exit__``.
        """
        if self.closed:
            return {
                "schema": TM_OWNERSHIP_SCHEMA,
                "already_closed": True,
                "owner_token": self.owner_token,
                "run_uuid": self.run_uuid,
                "master_released": False,
            }

        detached: List[str] = []
        detach_errors: Dict[str, str] = {}
        if detach_autopilot:
            for entry in list(self._actor_ledger):
                actor = entry.get("_actor_ref")
                if actor is None:
                    continue
                try:
                    actor.set_autopilot(False, int(entry.get("tm_port", self.tm_port)))
                    detached.append(str(entry.get("actor_id")))
                except Exception as exc:
                    detach_errors[str(entry.get("actor_id"))] = (
                        f"{type(exc).__name__}:{exc}"
                    )

        released = False
        if self._claimed_master:
            released = self.release_master(self.tm_port, owner_token=self.owner_token)
            self._claimed_master = False

        self._tm = None
        self._seeded = False
        self._reseed_required = False
        # Governed ownership metadata is detached, not merely flagged.
        for entry in self._actor_ledger:
            entry["owner_session_id"] = None
            entry["detached"] = True
        self.closed = True
        self.closed_at = time.time()

        return {
            "schema": TM_OWNERSHIP_SCHEMA,
            "already_closed": False,
            "owner_token": self.owner_token,
            "run_uuid": self.run_uuid,
            "session_id": self.session_id,
            "tm_port": self.tm_port,
            "master_released": released,
            "autopilot_detached": detached,
            "autopilot_detach_errors": detach_errors,
            "actors_detached": len(detached),
            "closed": True,
        }

    def __enter__(self) -> "TrafficManagerSession":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.close()
        return False

    # -- TM actor ledger (evidence-derived claims) --------------------------

    def record_actor(
        self,
        actor: Any,
        *,
        actor_type: str = "vehicle",
        autopilot_enabled: bool = True,
        policies: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record a governed actor in the TM ledger.

        The ledger is the only source for TM evidence claims. A claim such as
        "all governed actors use one port" must be computed from these rows, not
        asserted.
        """
        entry: Dict[str, Any] = {
            "actor_id": str(getattr(actor, "id", id(actor))),
            "actor_type": str(actor_type),
            "autopilot_enabled": bool(autopilot_enabled),
            "tm_port": int(self.tm_port),
            "owner_session_id": self.session_id,
            "owner_token": self.owner_token,
            "policy_digest": _sha(dict(policies or {})),
            "_actor_ref": actor,
        }
        with self._ledger_lock():
            self._actor_ledger.append(entry)
        return {k: v for k, v in entry.items() if k != "_actor_ref"}

    def actor_ledger(self) -> List[Dict[str, Any]]:
        with self._ledger_lock():
            return [
                {k: v for k, v in entry.items() if k != "_actor_ref"}
                for entry in self._actor_ledger
            ]

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
            # A claim that is not followed by a successful setup must not poison
            # the registry for the next run.
            try:
                self.claim_master(
                    self.tm_port,
                    self.session_id,
                    owner_token=self.owner_token,
                    run_uuid=self.run_uuid,
                    process_id=self.process_id,
                )
                self._claimed_master = True
            except Exception:
                self._claimed_master = False
                raise

        try:
            self._tm = client.get_trafficmanager(self.tm_port)
        except Exception as exc:
            # Setup failed after the claim: release it transactionally so the
            # next run can take the port.
            self._release_claim_after_failed_setup()
            raise RuntimeError(
                f"{TRAFFIC_MANAGER_SETUP_FAILED}:get_trafficmanager:"
                f"port={self.tm_port}:{type(exc).__name__}:{exc}"
            ) from exc

        if self._tm is None:
            self._release_claim_after_failed_setup()
            raise RuntimeError(
                f"{TRAFFIC_MANAGER_UNAVAILABLE}:port={self.tm_port}"
            )

        sync = self.synchronous_mode if world_sync_mode is None else bool(world_sync_mode)
        try:
            self._configure_tm(sync=sync)
        except Exception:
            self._release_claim_after_failed_setup()
            self._tm = None
            raise
        return self._tm

    def _release_claim_after_failed_setup(self) -> None:
        if self._claimed_master:
            self.release_master(self.tm_port, owner_token=self.owner_token)
            self._claimed_master = False

    def _configure_tm(self, *, sync: bool) -> None:
        """Apply the governed TM configuration.

        Hybrid physics uses the real CARLA traffic-manager API:
        ``hybrid_physics_mode(True)`` and ``hybrid_physics_radius(r)``.

        The previous implementation called a ``hybrid_physics_mode`` method that
        CARLA does not expose, then substituted ``distance_to_leading_vehicle``
        for the hybrid radius. Those are different quantities: the radius is how
        far ahead a vehicle switches to hybrid behaviour, while the follow gap is
        the spacing target. Configuring the gap while claiming a radius means the
        governed hybrid radius never took effect, and on a real TM the missing
        method raised TRAFFIC_MANAGER_SETUP_FAILED.
        """
        self._apply("set_synchronous_mode", sync, required=True)

        if self.hybrid_physics:
            self._apply("hybrid_physics_mode", True, required=True)
            if self.hybrid_radius is not None:
                # required=True: if the installed CARLA does not expose the
                # radius API, a governed hybrid radius cannot be claimed.
                self._apply("hybrid_physics_radius", self.hybrid_radius, required=True)
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

    def _tm_api_surface(self) -> List[str]:
        return _tm_api_surface(self._tm)

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
            "owner_token": self.owner_token,
            "run_uuid": self.run_uuid,
            "closed": self.closed,
            "actor_ledger_row_count": len(self.actor_ledger()),
        }
        # The two ownership claims are DERIVED from the actor ledger, never
        # asserted. With no governed actors recorded they are None (no
        # evidence), not True.
        evidence = tm_actor_ledger_evidence(
            self.actor_ledger(),
            expected_tm_port=self.tm_port,
            expected_owner_session_id=self.session_id,
        )
        config["all_governed_actors_use_single_port"] = evidence[
            "all_governed_actors_use_single_port"
        ]
        config["single_tm_master"] = evidence["single_tm_master"]
        config["ownership_claims_are_derived"] = True
        config["ownership_insufficient_evidence"] = evidence["insufficient_evidence"]
        config[TM_DIGEST_FIELD] = _sha(
            {k: v for k, v in config.items() if k != TM_DIGEST_FIELD}
        )
        return config


def tm_actor_ledger_evidence(
    ledger: Sequence[Mapping[str, Any]],
    *,
    expected_tm_port: Optional[int] = None,
    expected_owner_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Derive TM claims from an actual actor ledger.

    No boolean in the result is asserted: each is computed from the ledger rows.
    When the ledger is empty the claims are ``None`` with an explicit
    ``insufficient_evidence`` reason, never a hardcoded ``true``.
    """
    rows = [dict(r) for r in ledger]
    active = [r for r in rows if bool(r.get("autopilot_enabled"))]

    master_ports = sorted(
        {int(r["tm_port"]) for r in rows if r.get("tm_port") is not None}
    )
    active_ports = sorted(
        {int(r["tm_port"]) for r in active if r.get("tm_port") is not None}
    )
    active_masters = TrafficManagerSession.master_registry_snapshot()
    active_master_ports = sorted(int(p) for p in active_masters)

    actors_without_governed_tm = [
        {
            "actor_id": r.get("actor_id"),
            "actor_type": r.get("actor_type"),
            "tm_port": r.get("tm_port"),
            "owner_session_id": r.get("owner_session_id"),
            "reason": (
                "autopilot_disabled"
                if not bool(r.get("autopilot_enabled"))
                else "no_owner_session"
                if not r.get("owner_session_id")
                else "no_tm_port"
            ),
        }
        for r in active
        if not r.get("owner_session_id") or r.get("tm_port") is None
    ]

    wrong_port = [
        {
            "actor_id": r.get("actor_id"),
            "actor_type": r.get("actor_type"),
            "actor_tm_port": r.get("tm_port"),
            "expected_tm_port": expected_tm_port,
        }
        for r in active
        if expected_tm_port is not None
        and r.get("tm_port") is not None
        and int(r["tm_port"]) != int(expected_tm_port)
    ]

    wrong_owner = [
        {
            "actor_id": r.get("actor_id"),
            "actor_type": r.get("actor_type"),
            "actor_owner_session_id": r.get("owner_session_id"),
            "expected_owner_session_id": expected_owner_session_id,
        }
        for r in active
        if expected_owner_session_id is not None
        and r.get("owner_session_id") is not None
        and str(r["owner_session_id"]) != str(expected_owner_session_id)
    ]

    insufficient = not rows
    return {
        "schema": TM_ACTOR_LEDGER_SCHEMA,
        "ledger_row_count": len(rows),
        "active_actor_count": len(active),
        "unique_active_master_count": len(active_master_ports),
        "unique_active_master_ports": active_master_ports,
        "unique_tm_ports_for_governed_actors": active_ports,
        "unique_tm_ports_all_ledger_rows": master_ports,
        "actors_without_governed_tm": actors_without_governed_tm,
        "actors_using_wrong_port": wrong_port,
        "actors_using_wrong_owner": wrong_owner,
        "master_registry": active_masters,
        # Derived claims. None (not True) when there is nothing to derive from.
        "single_tm_master": (
            None
            if insufficient
            else bool(len(active_master_ports) <= 1 and len(active_ports) <= 1)
        ),
        "all_governed_actors_use_single_port": (
            None if insufficient else bool(len(active_ports) <= 1)
        ),
        "all_governed_actors_owned": (
            None if insufficient else not actors_without_governed_tm
        ),
        "all_governed_actors_on_expected_port": (
            None if insufficient or expected_tm_port is None else not wrong_port
        ),
        "claims_are_derived": True,
        "insufficient_evidence": insufficient,
        "insufficient_evidence_reason": "empty_actor_ledger" if insufficient else "",
    }


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


def _xyz(location: Any) -> Optional[Dict[str, float]]:
    if location is None:
        return None
    if isinstance(location, Mapping):
        try:
            return {
                "x": float(location["x"]),
                "y": float(location["y"]),
                "z": float(location.get("z", 0.0)),
            }
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(location, (tuple, list)) and len(location) >= 3:
        try:
            return {
                "x": float(location[0]),
                "y": float(location[1]),
                "z": float(location[2]),
            }
        except (TypeError, ValueError):
            return None
    try:
        return {
            "x": float(location.x),
            "y": float(location.y),
            "z": float(getattr(location, "z", 0.0)),
        }
    except (AttributeError, TypeError, ValueError):
        return None


def resolve_navigation_location(world: Any, rng: Any) -> Tuple[Optional[Any], str]:
    """Resolve one navigation location and report how it was obtained.

    ``world.get_random_location_from_navigation()`` is CARLA-side randomness
    governed by the server, NOT by the Python seed tree. Calling it in strict
    mode produced unreplayable pedestrian spawns while the run was reported as
    seeded. This reports the provenance so a caller can refuse an ungoverned
    position instead of describing it as deterministic.

    Returns ``(location, provenance)`` where provenance is one of
    ``nav_governed_pool``, ``nav_carla_random``, ``rng_fallback`` or
    ``unresolved``.
    """
    pool = getattr(world, "_governed_nav_pool", None)
    if isinstance(pool, (list, tuple)) and pool:
        try:
            return pool[int(rng.randrange(len(pool)))], "nav_governed_pool"
        except Exception:
            pass

    nav = getattr(world, "get_random_location_from_navigation", None)
    if callable(nav):
        try:
            loc = nav()
        except Exception:
            loc = None
        if loc is not None:
            return loc, "nav_carla_random"

    loc = _carla_location(
        world, rng.uniform(-50.0, 50.0), rng.uniform(-50.0, 50.0), 1.0
    )
    if loc is None:
        return None, "unresolved"
    return loc, "rng_fallback"


#: Provenance values that the Python seed tree actually governs.
GOVERNED_POSITION_PROVENANCE = ("nav_governed_pool", "rng_fallback")


def build_walker_scenario_manifest(
    world: Any,
    *,
    rng: Any,
    seed_tree_branch: str,
    count: int,
    max_speed: float = 1.4,
    experiment_seed: Optional[int] = None,
    walker_blueprint: str = "walker.pedestrian.*",
    controller_blueprint: str = WALKER_CONTROLLER_BLUEPRINT,
) -> Dict[str, Any]:
    """Strategy A: pre-resolve nav locations once, bind them by hash.

    Both paired arms replay this manifest instead of each asking CARLA for a
    random nav location, which is server-side randomness outside the Python seed
    tree. The manifest is hashed so a replay can prove it used the same plan.

    Each entry carries walker_index, blueprint, spawn transform, destination
    transform, max speed, seed-tree branch and a ``governed`` flag that is False
    whenever a position came from CARLA-side randomness.
    """
    entries: List[Dict[str, Any]] = []
    for index in range(max(0, int(count))):
        spawn, spawn_prov = resolve_navigation_location(world, rng)
        dest, dest_prov = resolve_navigation_location(world, rng)
        entries.append(
            {
                "walker_index": int(index),
                "blueprint": str(walker_blueprint),
                "controller_blueprint": str(controller_blueprint),
                "spawn_transform": _xyz(spawn),
                "destination_transform": _xyz(dest),
                "max_speed": float(max_speed),
                "seed_tree_branch": str(seed_tree_branch),
                "spawn_provenance": spawn_prov,
                "destination_provenance": dest_prov,
                "governed": (
                    spawn_prov in GOVERNED_POSITION_PROVENANCE
                    and dest_prov in GOVERNED_POSITION_PROVENANCE
                ),
            }
        )

    payload: Dict[str, Any] = {
        "schema": WALKER_SCENARIO_MANIFEST_SCHEMA,
        "seed_tree_branch": str(seed_tree_branch),
        "experiment_seed": experiment_seed,
        "walker_count": len(entries),
        "entries": entries,
        "ungoverned_entry_count": sum(1 for e in entries if not e["governed"]),
    }
    payload["scenario_manifest_sha256"] = _sha(
        {k: v for k, v in payload.items() if k != "scenario_manifest_sha256"}
    )
    return payload


def _destroy_actor(actor: Any) -> Optional[str]:
    if actor is None:
        return None
    stop = getattr(actor, "stop", None)
    if callable(stop):
        try:
            stop()
        except Exception:
            pass
    try:
        actor.destroy()
    except Exception as exc:
        return f"{type(exc).__name__}:{exc}"
    return None


def _actor_alive(actor: Any) -> bool:
    alive = getattr(actor, "is_alive", None)
    if callable(alive):
        try:
            return bool(alive())
        except Exception:
            return False
    return actor is not None


def _rollback_walker_transaction(actors: Sequence[Any]) -> List[Any]:
    """Destroy every provisional actor, controllers first."""
    out: List[Any] = []
    for item in reversed(list(actors)):
        if _destroy_actor(item) is None:
            out.append(getattr(item, "id", None))
    return out


def build_controlled_walker(
    world: Any,
    blueprint_library: Any,
    walker_bp: Any,
    *,
    controller_bp: Any,
    rng: Any,
    attempt: int = 0,
    walker_index: Optional[int] = None,
    spawn_location: Any = None,
    destination_location: Any = None,
    max_speed: float = 1.4,
    spawn_provenance: str = "",
    destination_provenance: str = "",
    seed_tree_branch: str = "",
    scenario_manifest_sha256: str = "",
    ownership_registry: Any = None,
    strict_governed_position: bool = True,
) -> Dict[str, Any]:
    """Spawn a genuinely **controlled** pedestrian, transactionally.

    Transaction: spawn walker -> spawn controller -> start controller -> assign
    destination -> verify both actors alive -> register ownership -> commit.

    On any failure the controller is stopped and destroyed, the walker is
    destroyed, provisional ownership is not registered, and a structured failure
    is returned. A walker is never left alive after a controller failure.

    ``controlled`` is True only when the controller actually started, the
    destination was actually assigned, both actors are alive, and the position
    was governed rather than CARLA-side random. The previous implementation
    reported ``controlled=True`` and ``controller_started=True`` even when
    ``start()`` or the destination assignment had failed.
    """
    failure: Dict[str, Any] = {
        "mode": WALKER_MODE_CONTROLLED,
        "controlled": False,
        "controller_started": False,
        "destination_assigned": False,
        "attempt": int(attempt),
        "transaction_committed": False,
        "failure_code": "",
        "rollback": {},
    }

    if spawn_location is None:
        spawn_location, spawn_provenance = resolve_navigation_location(world, rng)
    if destination_location is None:
        destination_location, destination_provenance = resolve_navigation_location(world, rng)

    if spawn_location is None or destination_location is None:
        failure["failure_code"] = f"{WALKER_TRANSACTION_FAILED}:navigation_unresolved"
        return failure

    governed = (
        spawn_provenance in GOVERNED_POSITION_PROVENANCE
        and destination_provenance in GOVERNED_POSITION_PROVENANCE
    )
    if strict_governed_position and not governed:
        failure["failure_code"] = (
            f"{WALKER_POSITION_UNGOVERNED}:"
            f"spawn={spawn_provenance}:destination={destination_provenance}"
        )
        return failure

    actor = None
    controller = None
    provisional: List[Any] = []

    # 1. spawn walker
    try:
        actor = world.try_spawn_actor(walker_bp, _carla_transform(world, spawn_location))
    except Exception as exc:
        failure["failure_code"] = (
            f"{WALKER_TRANSACTION_FAILED}:walker_spawn:{type(exc).__name__}:{exc}"
        )
        return failure
    if actor is None:
        failure["failure_code"] = f"{WALKER_TRANSACTION_FAILED}:walker_spawn:returned_none"
        return failure
    provisional.append(actor)

    # 2. spawn controller
    try:
        controller = world.try_spawn_actor(
            controller_bp, _carla_transform(world, spawn_location), attach_to=actor
        )
    except Exception as exc:
        failure["failure_code"] = (
            f"{WALKER_TRANSACTION_FAILED}:controller_spawn:{type(exc).__name__}:{exc}"
        )
        failure["rollback"] = {"destroyed": _rollback_walker_transaction(provisional)}
        return failure
    if controller is None:
        failure["failure_code"] = (
            f"{WALKER_TRANSACTION_FAILED}:controller_spawn:returned_none"
        )
        failure["rollback"] = {"destroyed": _rollback_walker_transaction(provisional)}
        return failure
    provisional.append(controller)

    # 3. start controller
    try:
        controller.start()
        controller_started = True
    except Exception as exc:
        failure["failure_code"] = (
            f"{WALKER_TRANSACTION_FAILED}:controller_start:{type(exc).__name__}:{exc}"
        )
        failure["rollback"] = {"destroyed": _rollback_walker_transaction(provisional)}
        return failure

    # 4. assign destination
    try:
        controller.go_to_location(destination_location)
        controller.set_max_speed(float(max_speed))
        destination_assigned = True
    except Exception as exc:
        failure["failure_code"] = (
            f"{WALKER_TRANSACTION_FAILED}:destination:{type(exc).__name__}:{exc}"
        )
        failure["rollback"] = {"destroyed": _rollback_walker_transaction(provisional)}
        return failure

    # 5. verify both actors alive
    if not _actor_alive(actor) or not _actor_alive(controller):
        failure["failure_code"] = (
            f"{WALKER_TRANSACTION_FAILED}:actor_not_alive_after_spawn"
        )
        failure["rollback"] = {"destroyed": _rollback_walker_transaction(provisional)}
        return failure

    # 6./7. register ownership, then commit
    if ownership_registry is not None:
        try:
            ownership_registry.register("walker", actor)
            ownership_registry.register("walker_controller", controller)
        except Exception as exc:
            failure["failure_code"] = (
                f"{WALKER_TRANSACTION_FAILED}:ownership_register:"
                f"{type(exc).__name__}:{exc}"
            )
            failure["rollback"] = {"destroyed": _rollback_walker_transaction(provisional)}
            return failure

    return {
        "mode": WALKER_MODE_CONTROLLED,
        "controlled": True,
        "counts_as_pedestrian_traffic": True,
        "walker_actor_id": getattr(actor, "id", None),
        "controller_actor_id": getattr(controller, "id", None),
        "controller_started": bool(controller_started),
        "destination_assigned": bool(destination_assigned),
        "relationship": "controller_attached_to_walker",
        "transaction_committed": True,
        "attempt": int(attempt),
        "walker_index": walker_index,
        "spawn_transform": _xyz(spawn_location),
        "destination_transform": _xyz(destination_location),
        "max_speed": float(max_speed),
        "seed_tree_branch": str(seed_tree_branch),
        "scenario_manifest_sha256": str(scenario_manifest_sha256),
        "spawn_provenance": spawn_provenance,
        "destination_provenance": destination_provenance,
        "position_governed": governed,
        "failure_code": "",
    }


def build_static_walker(
    world: Any,
    walker_bp: Any,
    *,
    rng: Any,
    spawn_location: Any = None,
    spawn_provenance: str = "",
    walker_index: Optional[int] = None,
    seed_tree_branch: str = "",
    scenario_manifest_sha256: str = "",
) -> Dict[str, Any]:
    """Spawn a walker explicitly declared as a static prop (not traffic)."""
    if spawn_location is None:
        spawn_location, spawn_provenance = resolve_navigation_location(world, rng)
    if spawn_location is None:
        return {
            "mode": WALKER_MODE_STATIC_PROP,
            "controlled": False,
            "counts_as_pedestrian_traffic": False,
            "error": "navigation_unresolved",
            "failure_code": f"{WALKER_TRANSACTION_FAILED}:navigation_unresolved",
        }
    actor = world.try_spawn_actor(walker_bp, _carla_transform(world, spawn_location))
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
        controlled = bool(entry.get("controlled", False))
        claims_traffic = bool(entry.get("counts_as_pedestrian_traffic", False))
        if controlled:
            # A controlled walker only counts once its controller genuinely
            # started and a destination was actually assigned; an explicit False
            # on either is a contradiction with controlled=True.
            #
            # An ABSENT key is not treated as a contradiction, because legacy
            # callers construct entries without those fields. Every builder in
            # this module sets them explicitly, so a real spawn is always
            # checked on its merits.
            if entry.get("controller_started") is False:
                reasons.append(
                    f"{WALKER_UNCONTROLLED}:controller_not_started:"
                    f"{entry.get('walker_actor_id')}"
                )
            elif entry.get("destination_assigned") is False:
                reasons.append(
                    f"{WALKER_UNCONTROLLED}:destination_not_assigned:"
                    f"{entry.get('walker_actor_id')}"
                )
            else:
                counted += 1
        elif claims_traffic:
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

    def verify_clean(self, *, expect_empty: Optional[bool] = None) -> Dict[str, Any]:
        """Report whether any owned actor is still alive.

        Default behaviour is unchanged: ``clean`` means no owned actor is still
        alive. ``expect_empty=True`` additionally requires the registry itself to
        be empty, for callers that treat a non-empty registry as a leak even when
        every tracked actor is already dead.
        """
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
        clean = not remaining
        if expect_empty is True:
            clean = clean and self.owned_count() == 0
        return {
            "clean": clean,
            "expect_empty": bool(expect_empty),
            "owned_actors_still_alive": remaining,
            "owned_actors_remaining": remaining,
            "owned_count": self.owned_count(),
            "failure_code": None if clean else SCENARIO_ACTOR_LEAK,
        }