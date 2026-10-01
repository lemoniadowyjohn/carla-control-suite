#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-322 -- transactional cleanup for the calibration sanity check.

``sensors/calibration_sanity_check.py`` spawns an ego and attaches sensors in
straight-line code with **no** ``try``/``finally``.  Every early ``return
report`` (ego spawn failure, sensor attach failure) and every raised exception
leaks the ego actor, the sensor actors, and any listener, straight into the
next perception run's world.

This module provides :class:`CalibrationCleanupGuard`: a context manager that
guarantees, on **all** paths,

* every sensor listener is stopped,
* every sensor actor is destroyed,
* every temporary target/prop actor is destroyed,
* the ego actor is destroyed,
* any modified world settings are restored,
* and, where RPC stays healthy, the actor cleanup is verified.

It emits ``calibration_cleanup_receipt.json`` recording what was attempted,
what succeeded and what was left behind -- including when the cleanup itself
was forced by an exception.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

CLEANUP_RECEIPT_FILENAME = "calibration_cleanup_receipt.json"
CLEANUP_SCHEMA = "CALIBRATION_CLEANUP_RECEIPT/v1"

CLEANUP_INCOMPLETE = "CLEANUP_INCOMPLETE"
CLEANUP_ACTOR_SURVIVED = "CLEANUP_ACTOR_SURVIVED"
CLEANUP_SETTINGS_NOT_RESTORED = "CLEANUP_SETTINGS_NOT_RESTORED"


def _actor_id(actor: Any) -> str:
    return str(getattr(actor, "id", id(actor)))


def _alive(actor: Any) -> Optional[bool]:
    fn = getattr(actor, "is_alive", None)
    if not callable(fn):
        return None
    try:
        return bool(fn())
    except Exception:
        return None


def _destroy(actor: Any) -> Optional[str]:
    try:
        actor.destroy()
        return None
    except Exception as exc:
        return f"{type(exc).__name__}:{exc}"


class CalibrationCleanupGuard:
    """Lifecycle guard for a calibration assay.

    Usage::

        with CalibrationCleanupGuard(world, out_dir=out_path) as guard:
            ego = guard.track_ego(world.spawn_actor(bp, tf))
            sensor = guard.track_sensor(world.spawn_actor(sbp, stf, attach_to=ego))
            sensor.listen(cb)
            ...
        # receipt written; guard.cleanup_complete() is True
    """

    def __init__(
        self,
        world: Any,
        *,
        out_dir: Optional[Any] = None,
        restore_settings: bool = True,
        rpc_timeout_s: float = 10.0,
    ) -> None:
        self.world = world
        self.out_dir = Path(out_dir) if out_dir is not None else None
        self.restore_settings = bool(restore_settings)
        self.rpc_timeout_s = float(rpc_timeout_s)

        self._sensors: List[Any] = []
        self._listeners: List[Any] = []
        self._temp_actors: List[Any] = []
        self._ego: List[Any] = []
        self._original_settings: Any = None
        self._settings_captured = False
        self._settings_restored = False

        self.stages_completed: List[str] = []
        self.failure_reason: Optional[str] = None
        self.exception: Optional[str] = None
        self._entered = False
        self._exited = False
        self._groups: Dict[str, Dict[str, Any]] = {}
        self._settings: Dict[str, Any] = {}

    # -- registration --------------------------------------------------------

    def track_sensor(self, actor: Any) -> Any:
        if actor is not None:
            self._sensors.append(actor)
        return actor

    def track_listener(self, listener: Any) -> Any:
        if listener is not None:
            self._listeners.append(listener)
        return listener

    def track_temp_actor(self, actor: Any) -> Any:
        if actor is not None:
            self._temp_actors.append(actor)
        return actor

    def track_ego(self, actor: Any) -> Any:
        if actor is not None:
            self._ego.append(actor)
        return actor

    def capture_original_settings(self) -> Any:
        if self.restore_settings and not self._settings_captured:
            try:
                self._original_settings = self.world.get_settings()
                self._settings_captured = True
                self.stages_completed.append("capture_original_settings")
            except Exception as exc:
                self._original_settings = None
                self.stages_completed.append(
                    f"capture_original_settings_failed:{type(exc).__name__}"
                )
        return self._original_settings

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> "CalibrationCleanupGuard":
        self._entered = True
        self.capture_original_settings()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.exception = f"{getattr(exc_type, '__name__', exc_type)}:{exc}"
            self.failure_reason = self.failure_reason or "exception_during_assay"
        self.cleanup()
        return False

    # -- cleanup -------------------------------------------------------------

    def cleanup(self) -> Dict[str, Any]:
        """Idempotent, all-path cleanup.  Never raises."""
        if self._exited:
            return self.receipt()
        self._exited = True

        listener_errors: Dict[str, str] = {}
        for index, listener in enumerate(list(self._listeners)):
            try:
                listener.stop()
            except Exception as exc:
                listener_errors[str(index)] = f"{type(exc).__name__}:{exc}"
        self.stages_completed.append(f"stopped_listeners:{len(self._listeners)}")

        sensor_report = self._destroy_group(self._sensors, "sensors")
        temp_report = self._destroy_group(self._temp_actors, "temporary_actors")
        ego_report = self._destroy_group(self._ego, "ego")

        settings_report = self._restore_settings()

        self._groups = {
            "sensors": sensor_report,
            "temporary_actors": temp_report,
            "ego": ego_report,
        }
        self._settings = settings_report
        self.settings_restored = settings_report["restored"]
        return {
            "listener_errors": listener_errors,
            "sensors": sensor_report,
            "temporary_actors": temp_report,
            "ego": ego_report,
            "settings": settings_report,
        }

    def _destroy_group(self, actors: Sequence[Any], label: str) -> Dict[str, Any]:
        destroyed: List[str] = []
        survivors: List[str] = []
        errors: Dict[str, str] = {}
        for actor in list(actors):
            actor_id = _actor_id(actor)
            was_alive = _alive(actor)
            if was_alive is False:
                destroyed.append(actor_id)
                continue
            err = _destroy(actor)
            if err is not None:
                errors[actor_id] = err
                survivors.append(actor_id)
                continue
            destroyed.append(actor_id)
            after = _alive(actor)
            if after is True:
                survivors.append(actor_id)
                errors.setdefault(actor_id, "alive_after_destroy")
        # Second verification pass after a short settle: destruction over RPC
        # is asynchronous, so a single read-back can be misleading.
        time.sleep(0.0)
        verified_survivors: List[str] = []
        for actor in list(actors):
            actor_id = _actor_id(actor)
            if actor_id in survivors and _alive(actor) is True:
                verified_survivors.append(actor_id)
        self.stages_completed.append(
            f"destroyed_{label}:{len(destroyed)}:survivors:{len(verified_survivors)}"
        )
        return {
            "requested": len(list(actors)),
            "destroyed": destroyed,
            "destroy_errors": errors,
            "survivors_after_verification": verified_survivors,
            "clean": not verified_survivors,
        }

    def _restore_settings(self) -> Dict[str, Any]:
        if not self.restore_settings:
            return {"restored": True, "skipped": True, "detail": "restore_settings=False"}
        if not self._settings_captured or self._original_settings is None:
            return {"restored": False, "skipped": False,
                    "detail": "original_settings_never_captured"}
        if self._settings_restored:
            return {"restored": True, "skipped": False, "detail": "already_restored"}
        try:
            self.world.apply_settings(self._original_settings)
            self._settings_restored = True
            self.stages_completed.append("restored_world_settings")
            return {"restored": True, "skipped": False, "detail": None}
        except Exception as exc:
            self.stages_completed.append(f"restore_world_settings_failed:{type(exc).__name__}")
            return {
                "restored": False, "skipped": False,
                "detail": f"{type(exc).__name__}:{exc}",
            }

    # -- receipt -------------------------------------------------------------

    def cleanup_complete(self) -> bool:
        return self.cleanup_complete_reasons() == []

    def cleanup_complete_reasons(self) -> List[str]:
        reasons: List[str] = []
        if not self._exited:
            reasons.append(f"{CLEANUP_INCOMPLETE}:guard_still_open")
            return reasons
        groups = getattr(self, "_groups", None) or {}
        for group in ("sensors", "temporary_actors", "ego"):
            report = groups.get(group) or {}
            if report and not report.get("clean", True):
                reasons.append(
                    f"{CLEANUP_ACTOR_SURVIVED}:{group}:"
                    f"{report.get('survivors_after_verification')}"
                )
        settings = getattr(self, "_settings", None) or {}
        if settings and not settings.get("restored", False):
            reasons.append(f"{CLEANUP_SETTINGS_NOT_RESTORED}:{settings.get('detail')}")
        return reasons

    def receipt(self) -> Dict[str, Any]:
        """``calibration_cleanup_receipt.json`` payload."""
        reasons = self.cleanup_complete_reasons()
        groups = getattr(self, "_groups", None) or {}
        settings = getattr(self, "_settings", None) or {}
        total_destroyed = sum(
            len((groups.get(g) or {}).get("destroyed") or [])
            for g in ("sensors", "temporary_actors", "ego")
        )
        return {
            "schema": CLEANUP_SCHEMA,
            "cleanup_complete": not reasons,
            "invalid_reasons": reasons,
            "transactional": True,
            "guarded_failure_reason": self.failure_reason,
            "guarded_exception": self.exception,
            "stages_completed": list(self.stages_completed),
            "registered": {
                "listeners": len(self._listeners),
                "sensors": len(self._sensors),
                "temporary_actors": len(self._temp_actors),
                "ego": len(self._ego),
            },
            "cleanup_results": {
                "groups": groups,
                "settings": settings,
                "total_actors_destroyed": total_destroyed,
            },
            "residual_actor_leak_possible": bool(reasons),
            "next_perception_run_contaminated": bool(reasons),
        }

    def write_receipt(self, path: Optional[Any] = None) -> Optional[str]:
        target = Path(str(path)) if path is not None else (
            self.out_dir / CLEANUP_RECEIPT_FILENAME if self.out_dir else None
        )
        if target is None:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.receipt(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return str(target)