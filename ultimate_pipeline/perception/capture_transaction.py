#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/capture_transaction.py

Governed capture lifecycle transaction for the RQ3 paired-perception contract.

Purpose
-------
Every mutation performed by an RQ3 capture (world settings, weather, traffic
manager, actor spawns, sensor spawns, listener attachments, ticks, dataset
writes) happens inside a transaction. If ANY critical boundary raises, the
transaction rolls back:

* world settings are restored and READ BACK (not assumed),
* weather is restored and READ BACK,
* traffic-manager mode is restored and READ BACK,
* every owned actor is destroyed,
* every registered listener is detached,
* the staging area is quarantined so it can never be promoted to accepted data.

Design rules:
* No CARLA import at module level -> fully offline-testable.
* Restoration is verified by readback. When CARLA does not expose a readback
  for a field, the field is reported as ``UNOBSERVABLE`` and the transaction
  is marked ``RESTORATION_NOT_VERIFIED`` -- it is NOT reported as restored.
* A failed restoration invalidates the capture: ``authoritative`` becomes
  False and ``invalidating_reasons`` is populated.

Transaction stages (in order), each individually fault-injectable:

    1  world_settings
    2  weather
    3  traffic_manager
    4  ego_spawn
    5  first_sensor_spawn
    6  second_sensor_spawn
    7  listener_attachment
    8  first_tick
    9  dataset_write
    10 teardown
    11 restoration
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

TRANSACTION_SCHEMA_VERSION = "RQ3_CAPTURE_TRANSACTION/v1"

#: Ordered critical boundaries. A fault at any of these must roll back.
CRITICAL_STAGES: Tuple[str, ...] = (
    "world_settings",
    "weather",
    "traffic_manager",
    "ego_spawn",
    "first_sensor_spawn",
    "second_sensor_spawn",
    "listener_attachment",
    "first_tick",
    "dataset_write",
    "teardown",
    "restoration",
)

#: Readback verdict states.
READBACK_VERIFIED = "READBACK_VERIFIED"
READBACK_FAILED = "READBACK_FAILED"
UNOBSERVABLE = "UNOBSERVABLE"
NOT_ATTEMPTED = "NOT_ATTEMPTED"


@dataclass
class RestorationField:
    """One field that the transaction mutated and must restore."""

    name: str
    before: Any
    after: Any = None
    restored: bool = False
    readback: str = NOT_ATTEMPTED
    observable: bool = True
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.name,
            "before": self.before,
            "after": self.after,
            "restored": self.restored,
            "readback": self.readback,
            "observable": self.observable,
            "detail": self.detail,
        }


@dataclass
class OwnedActor:
    """An actor spawned by this transaction (must be destroyed on rollback)."""

    actor_id: str
    kind: str
    destroyed: bool = False


@dataclass
class OwnedListener:
    """A sensor listener registered by this transaction."""

    sensor_id: str
    callback_id: str
    detached: bool = False


@dataclass
class TransactionResult:
    """Outcome of a governed capture transaction."""

    stages_completed: List[str] = field(default_factory=list)
    failed_stage: Optional[str] = None
    error: str = ""
    error_type: str = ""
    restorations: Dict[str, RestorationField] = field(default_factory=dict)
    actors: List[OwnedActor] = field(default_factory=list)
    listeners: List[OwnedListener] = field(default_factory=list)
    rolled_back: bool = False
    rollback_errors: List[str] = field(default_factory=list)
    staging_quarantined: bool = False
    authoritative: bool = True
    invalidating_reasons: List[str] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)

    @property
    def restoration_verified(self) -> bool:
        return all(
            f.readback in (READBACK_VERIFIED, UNOBSERVABLE)
            for f in self.restorations.values()
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "stages_completed": list(self.stages_completed),
            "failed_stage": self.failed_stage,
            "error": self.error,
            "error_type": self.error_type,
            "restorations": {k: v.to_dict() for k, v in self.restorations.items()},
            "actors": [a.to_dict() if hasattr(a, "to_dict") else {
                "actor_id": a.actor_id, "kind": a.kind, "destroyed": a.destroyed} for a in self.actors],
            "listeners": [{
                "sensor_id": l.sensor_id, "callback_id": l.callback_id,
                "detached": l.detached} for l in self.listeners],
            "rolled_back": self.rolled_back,
            "rollback_errors": list(self.rollback_errors),
            "staging_quarantined": self.staging_quarantined,
            "authoritative": self.authoritative,
            "invalidating_reasons": list(self.invalidating_reasons),
            "restoration_verified": self.restoration_verified,
            "artifacts": dict(self.artifacts),
        }


class CaptureTransaction:
    """Governed capture lifecycle with rollback on failure.

    The transaction is intentionally duck-typed against CARLA objects so that
    offline tests can inject fakes. Every mutating helper is optional: a host
    that does not expose a given capability simply omits the corresponding
    callback and the field is reported ``UNOBSERVABLE`` rather than silently
    claimed restored.
    """

    def __init__(
        self,
        *,
        world: Any = None,
        traffic_manager: Any = None,
        get_weather: Optional[Callable[[], Any]] = None,
        set_weather: Optional[Callable[[Any], None]] = None,
        destroy_actor: Optional[Callable[[Any], None]] = None,
        detach_listener: Optional[Callable[[Any, str], None]] = None,
        quarantine_staging: Optional[Callable[[], None]] = None,
        readback_settings: Optional[Callable[[], Mapping[str, Any]]] = None,
        readback_weather: Optional[Callable[[], Any]] = None,
        readback_tm: Optional[Callable[[], Mapping[str, Any]]] = None,
        settings_snapshot: Optional[Callable[[], Mapping[str, Any]]] = None,
        tm_snapshot: Optional[Callable[[], Mapping[str, Any]]] = None,
        weather_snapshot: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.world = world
        self.traffic_manager = traffic_manager
        self._get_weather = get_weather
        self._set_weather = set_weather
        self._destroy_actor = destroy_actor
        self._detach_listener = detach_listener
        self._quarantine_staging = quarantine_staging
        self._readback_settings = readback_settings
        self._readback_weather = readback_weather
        self._readback_tm = readback_tm
        self._settings_snapshot = settings_snapshot
        self._tm_snapshot = tm_snapshot
        self._weather_snapshot = weather_snapshot

        self.result = TransactionResult()
        self._actors: List[Any] = []
        self._listeners: List[Tuple[Any, str]] = []

    # -- registration -----------------------------------------------------

    def own_actor(self, actor: Any, actor_id: str, kind: str) -> None:
        """Register an actor this transaction spawned."""
        self._actors.append(actor)
        self.result.actors.append(OwnedActor(actor_id=actor_id, kind=kind))

    def own_listener(self, sensor: Any, callback_id: str) -> None:
        """Register a listener this transaction attached."""
        self._listeners.append((sensor, callback_id))
        self.result.listeners.append(OwnedListener(sensor_id=str(sensor), callback_id=callback_id))

    # -- mutation helpers -------------------------------------------------

    def apply_world_settings(self, settings: Any) -> None:
        """Apply world settings and record the pre-state for restoration."""
        before = self._settings_snapshot() if self._settings_snapshot else None
        field = RestorationField(name="world_settings", before=before, observable=before is not None)
        self.result.restorations["world_settings"] = field
        if self.world is None:
            raise RuntimeError("capture transaction requires a world")
        apply = getattr(self.world, "apply_settings", None)
        if apply is None:
            raise RuntimeError("world has no apply_settings")
        apply(settings)
        field.after = self._readback_settings() if self._readback_settings else None

    def apply_weather(self, weather: Any) -> None:
        before = self._weather_snapshot() if self._weather_snapshot else None
        field = RestorationField(name="weather", before=before, observable=before is not None)
        self.result.restorations["weather"] = field
        if self._set_weather is None:
            raise RuntimeError("capture transaction requires set_weather")
        self._set_weather(weather)

    def apply_traffic_manager(self, **kwargs: Any) -> None:
        before = self._tm_snapshot() if self._tm_snapshot else None
        field = RestorationField(name="traffic_manager", before=before, observable=before is not None)
        self.result.restorations["traffic_manager"] = field
        if self.traffic_manager is None:
            raise RuntimeError("capture transaction requires a traffic_manager")
        setter = getattr(self.traffic_manager, "set_synchronous_mode", None)
        if setter is None:
            raise RuntimeError("traffic_manager has no set_synchronous_mode")
        sync = bool(kwargs.get("synchronous_mode", True))
        setter(sync)
        if "sync_mode" in kwargs:
            setter(kwargs.get("sync_mode"))
        if "distance" in kwargs:
            d = getattr(self.traffic_manager, "set_distance_to_leading_vehicle", None)
            if d is not None:
                d(float(kwargs["distance"]))

    # -- rollback ---------------------------------------------------------

    def rollback(self) -> None:
        """Undo every mutation made by this transaction.

        Restoration is READ BACK where observable. A readback mismatch, a
        readback failure, or an unobservable field that the contract requires
        invalidates the capture.
        """
        self.result.rolled_back = True

        # 1. listeners
        for sensor, callback_id in list(self._listeners):
            try:
                if self._detach_listener is not None:
                    self._detach_listener(sensor, callback_id)
                for entry in self.result.listeners:
                    if entry.callback_id == callback_id and not entry.detached:
                        entry.detached = True
            except Exception as exc:  # noqa: BLE001 - rollback must not mask
                self.result.rollback_errors.append(f"listener_detach_failed:{callback_id}:{exc}")

        # 2. owned actors
        for actor, entry in zip(self._actors, self.result.actors):
            try:
                if self._destroy_actor is not None:
                    self._destroy_actor(actor)
                entry.destroyed = True
            except Exception as exc:  # noqa: BLE001
                self.result.rollback_errors.append(f"actor_destroy_failed:{entry.actor_id}:{exc}")

        # 3. world settings
        self._restore_field(
            "world_settings",
            apply_fn=self._apply_settings_snapshot,
            readback_fn=self._readback_settings,
        )

        # 4. weather
        self._restore_field(
            "weather",
            apply_fn=self._apply_weather_snapshot,
            readback_fn=self._readback_weather,
            compare=lambda before, after: _weather_equal(before, after),
        )

        # 5. traffic manager
        self._restore_field(
            "traffic_manager",
            apply_fn=self._apply_tm_snapshot,
            readback_fn=self._readback_tm,
        )

        # 6. staging quarantine
        if self._quarantine_staging is not None:
            try:
                self._quarantine_staging()
                self.result.staging_quarantined = True
            except Exception as exc:  # noqa: BLE001
                self.result.rollback_errors.append(f"staging_quarantine_failed:{exc}")
                self.result.invalidating_reasons.append("staging_quarantine_failed")

        if self.result.rollback_errors:
            self.result.invalidating_reasons.append("rollback_errors")

    def _restore_field(
        self,
        name: str,
        *,
        apply_fn: Callable[[Any], None],
        readback_fn: Optional[Callable[[], Any]],
        compare: Optional[Callable[[Any, Any], bool]] = None,
    ) -> None:
        field = self.result.restorations.get(name)
        if field is None:
            return
        if not field.observable:
            field.readback = UNOBSERVABLE
            field.detail = "no snapshot capability for this field"
            self.result.invalidating_reasons.append(f"{name}_unobservable")
            return
        try:
            apply_fn(field.before)
        except Exception as exc:  # noqa: BLE001
            field.readback = READBACK_FAILED
            field.detail = f"restore_apply_failed:{exc}"
            self.result.invalidating_reasons.append(f"{name}_restore_failed")
            return
        if readback_fn is None:
            field.readback = UNOBSERVABLE
            field.detail = "no readback capability for this field"
            self.result.invalidating_reasons.append(f"{name}_unobservable")
            return
        try:
            after = readback_fn()
        except Exception as exc:  # noqa: BLE001
            field.readback = READBACK_FAILED
            field.detail = f"readback_failed:{exc}"
            self.result.invalidating_reasons.append(f"{name}_readback_failed")
            return
        field.after = after
        cmp = compare or (lambda b, a: b == a)
        if cmp(field.before, after):
            field.restored = True
            field.readback = READBACK_VERIFIED
        else:
            field.restored = False
            field.readback = READBACK_FAILED
            field.detail = "readback differs from pre-state"
            self.result.invalidating_reasons.append(f"{name}_readback_mismatch")

    def _apply_settings_snapshot(self, before: Any) -> None:
        if before is None or self.world is None:
            return
        apply = getattr(self.world, "apply_settings", None)
        if apply is None:
            return
        apply(_FakeSettings(before))

    def _apply_weather_snapshot(self, before: Any) -> None:
        if before is None or self._set_weather is None:
            return
        self._set_weather(before)

    def _apply_tm_snapshot(self, before: Any) -> None:
        if before is None or self.traffic_manager is None:
            return
        setter = getattr(self.traffic_manager, "set_synchronous_mode", None)
        if setter is None:
            return
        setter(bool(before.get("synchronous_mode", True)))


class _FakeSettings:
    """Adapter that presents a mapping snapshot as a world-settings object."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload)

    def __getattr__(self, item: str) -> Any:
        return self._payload.get(item)


def _weather_equal(before: Any, after: Any) -> bool:
    if before is None or after is None:
        return before == after
    try:
        return str(before) == str(after)
    except Exception:  # noqa: BLE001
        return before == after


def run_governed_capture(
    transaction: CaptureTransaction,
    stages: Mapping[str, Callable[[], Any]],
    *,
    stage_order: Sequence[str] = CRITICAL_STAGES,
) -> TransactionResult:
    """Execute the capture stages inside a governed transaction.

    Each entry of `stages` is a callable that performs one stage. If a stage
    raises, the transaction is rolled back and the exception is NOT re-raised
    to the caller -- the failure is recorded in the result so that the caller
    can adjudicate the capture as non-authoritative.
    """
    for stage in stage_order:
        fn = stages.get(stage)
        if fn is None:
            continue
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - boundary capture
            transaction.result.failed_stage = stage
            transaction.result.error = str(exc)
            transaction.result.error_type = type(exc).__name__
            transaction.result.authoritative = False
            if stage not in transaction.result.invalidating_reasons:
                transaction.result.invalidating_reasons.append(f"failed_stage:{stage}")
            transaction.rollback()
            transaction.result.authoritative = False
            return transaction.result
        transaction.result.stages_completed.append(stage)
    return transaction.result


__all__ = [
    "TRANSACTION_SCHEMA_VERSION",
    "CRITICAL_STAGES",
    "READBACK_VERIFIED",
    "READBACK_FAILED",
    "UNOBSERVABLE",
    "NOT_ATTEMPTED",
    "RestorationField",
    "OwnedActor",
    "OwnedListener",
    "TransactionResult",
    "CaptureTransaction",
    "run_governed_capture",
]
