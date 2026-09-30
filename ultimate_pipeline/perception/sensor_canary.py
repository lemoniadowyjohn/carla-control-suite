"""Sensor readiness canary (NEW-255).

TCP 2001 being open is diagnostic evidence, never the readiness oracle.  The
decisive gate is an actual sensor: spawn one low-resolution front RGB camera,
attach a callback, advance 5-10 ticks, and require a plausible frame.

The canary must then be stopped *without* unsafe Grid destruction - teardown
goes through :mod:`ultimate_pipeline.perception.sensor_lifecycle`.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ultimate_pipeline.perception.sensor_lifecycle import (
    LifecyclePolicy,
    stop_sensor_callbacks,
)

CANARY_NAME = "canary_rgb_front"
DEFAULT_CANARY_WIDTH = 320
DEFAULT_CANARY_HEIGHT = 180
DEFAULT_TICKS = 8
MIN_FRAMES = 1
MAX_REASONABLE_FRAME_ID = 10_000_000_000


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return int(default)
    try:
        return int(float(str(raw).strip()))
    except Exception:
        return int(default)


def _frame_id_plausible(frame_id: Any) -> bool:
    try:
        value = int(frame_id)
    except Exception:
        return False
    if value <= 0:
        return False
    return value <= MAX_REASONABLE_FRAME_ID


def run_sensor_canary(
    world: Any,
    *,
    ego_vehicle: Any = None,
    client: Any = None,
    tick_timeout_s: float = 10.0,
    ticks: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    carla_pid: Optional[int] = None,
    known_unstable_map: bool = False,
    state_machine: Any = None,
    phase_journal: Any = None,
    output_path: Any = None,
    attach_to: Any = None,
) -> Dict[str, Any]:
    """Run the RGB sensor canary and return ``SENSOR_CANARY.json`` payload."""
    required_ticks = max(5, min(10, int(ticks if ticks is not None else _env_int("UP_SENSOR_CANARY_TICKS", DEFAULT_TICKS))))
    cam_w = int(width if width is not None else _env_int("UP_SENSOR_CANARY_WIDTH", DEFAULT_CANARY_WIDTH))
    cam_h = int(height if height is not None else _env_int("UP_SENSOR_CANARY_HEIGHT", DEFAULT_CANARY_HEIGHT))

    frames: List[int] = []
    errors: List[str] = []
    actor = None
    listener_attached = False
    actor_alive = False
    blueprint_ok = False
    spawn_error: Optional[str] = None
    started = time.time()
    first_frame_at: Optional[float] = None
    carla_alive = True
    snapshot: Dict[str, Any] = {}

    def _journal(phase: str, **extra: Any) -> None:
        if phase_journal is None:
            return
        try:
            phase_journal.record(phase, sensor=CANARY_NAME, sensor_type="sensor.camera.rgb", **extra)
        except Exception:
            pass

    _journal("RGB_CANARY_BEGIN", width=cam_w, height=cam_h, ticks=required_ticks)

    if state_machine is not None:
        try:
            state_machine._record("RGB_CANARY_BEGIN", {"ticks": required_ticks})
        except Exception:
            pass

    def _callback(image: Any) -> None:
        nonlocal first_frame_at
        try:
            frame_id = int(image.frame)
        except Exception:
            errors.append("callback_missing_frame_id")
            return
        frames.append(frame_id)
        if first_frame_at is None:
            first_frame_at = time.time()

    try:
        import carla  # type: ignore

        bp_lib = world.get_blueprint_library()
        blueprint = bp_lib.find("sensor.camera.rgb")
        blueprint_ok = blueprint is not None
        if blueprint is not None:
            blueprint.set_attribute("image_size_x", str(cam_w))
            blueprint.set_attribute("image_size_y", str(cam_h))
            blueprint.set_attribute("sensor_tick", "0.0")
        else:
            errors.append("blueprint_not_found:sensor.camera.rgb")
    except Exception as exc:
        spawn_error = f"{type(exc).__name__}:{exc}"
        errors.append(f"blueprint_setup_failed:{spawn_error}")
        blueprint_ok = False

    if blueprint_ok:
        try:
            blueprint = world.get_blueprint_library().find("sensor.camera.rgb")
            blueprint.set_attribute("image_size_x", str(cam_w))
            blueprint.set_attribute("image_size_y", str(cam_h))
            transform = carla.Transform(carla.Location(x=1.5, z=1.8))
            parent = attach_to if attach_to is not None else ego_vehicle
            if parent is not None:
                actor = world.spawn_actor(blueprint, transform, attach_to=parent)
            else:
                actor = world.spawn_actor(blueprint, transform)
        except Exception as exc:
            spawn_error = f"{type(exc).__name__}:{exc}"
            errors.append(f"canary_spawn_failed:{spawn_error}")
            actor = None

    if actor is not None:
        try:
            actor_alive = bool(getattr(actor, "is_alive", True))
            actor.listen(_callback)
            listener_attached = True
        except Exception as exc:
            errors.append(f"canary_listen_failed:{type(exc).__name__}:{exc}")

        if listener_attached:
            for _ in range(required_ticks):
                try:
                    world.tick(float(tick_timeout_s))
                except Exception as exc:
                    errors.append(f"canary_tick_failed:{type(exc).__name__}:{exc}")
                    break
                if len(frames) >= MIN_FRAMES and (time.time() - started) > 0.0:
                    # keep ticking to the full soak; break early only when we
                    # already have evidence and the caller asked for minimum
                    pass

        try:
            actor_alive = bool(getattr(actor, "is_alive", True))
        except Exception:
            actor_alive = False

    try:
        if client is not None:
            client.get_world()
    except Exception:
        carla_alive = False
        errors.append("carla_rpc_dead_after_canary")

    if frames and first_frame_at is None:
        first_frame_at = time.time()

    # --- verdict -------------------------------------------------------
    checks: Dict[str, bool] = {
        "actor_alive": bool(actor is not None and actor_alive),
        "listener_attached": bool(listener_attached),
        "frames_received_at_least_one": len(frames) >= MIN_FRAMES,
        "frame_id_plausible": bool(frames) and all(_frame_id_plausible(f) for f in frames),
        "carla_still_alive": bool(carla_alive),
        "rpc_alive": bool(carla_alive),
    }
    passed = all(checks.values())

    # --- clean stop (no unsafe Grid destruction) ------------------------
    stop_error: Optional[str] = None
    if actor is not None:
        try:
            stop_sensor_callbacks(
                [(CANARY_NAME, actor)],
                policy=LifecyclePolicy.KNOWN_UNSTABLE if known_unstable_map else LifecyclePolicy.STABLE,
                destroy=False,
                drain_timeout_s=2.0,
            )
        except Exception as exc:
            stop_error = f"{type(exc).__name__}:{exc}"
            errors.append(f"canary_stop_failed:{stop_error}")

    elapsed = time.time() - started
    payload: Dict[str, Any] = {
        "schema": "SENSOR_CANARY/v1",
        "passed": bool(passed),
        "checks": checks,
        "sensor": {
            "name": CANARY_NAME,
            "type": "sensor.camera.rgb",
            "width": cam_w,
            "height": cam_h,
            "low_resolution": True,
        },
        "ticks_requested": required_ticks,
        "frames_received": len(frames),
        "frame_ids": frames[:32],
        "first_frame_id": frames[0] if frames else None,
        "last_frame_id": frames[-1] if frames else None,
        "first_frame_latency_s": (first_frame_at - started) if first_frame_at else None,
        "elapsed_s": elapsed,
        "spawn_error": spawn_error,
        "stop_error": stop_error,
        "carla_pid": carla_pid,
        "carla_alive": carla_alive,
        "port_2001_status": "DIAGNOSTIC_ONLY_NOT_DECISIVE",
        "port_2001_note": (
            "TCP 2001 is retained as diagnostic evidence only. On Grid maps it "
            "is not a reliable readiness oracle; this canary is the decisive gate."
        ),
        "errors": errors,
        "unsafe_destroy_used": False,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    snapshot["sensor_canary"] = {
        "passed": bool(passed),
        "frames_received": len(frames),
        "actor_alive": bool(actor is not None and actor_alive),
    }

    _journal("RGB_CANARY_CALLBACK", frames_received=len(frames), passed=bool(passed))
    if state_machine is not None:
        try:
            state_machine._record("RGB_CANARY_RETURN", {"passed": bool(passed), "frames": len(frames)})
        except Exception:
            pass

    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(target)

    return payload


def assert_canary_passed(report: Optional[Dict[str, Any]]) -> None:
    if not report or not report.get("passed"):
        checks = (report or {}).get("checks", {})
        failed = sorted(k for k, v in checks.items() if not v)
        raise RuntimeError(f"sensor_canary_failed:failed_checks={failed}")
