"""Post-load stability soak (NEW-260).

A single successful ``world.tick`` is not evidence that a loaded map is safe to
perceive from.  After a map load the pipeline must observe a configurable
number of *advancing* world ticks before the state may move from
``MAP_LOADED`` to ``MAP_STABLE``.

Perception may not start from merely ``MAP_LOADED``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

MAP_LOADED = "MAP_LOADED"
MAP_STABLE = "MAP_STABLE"

DEFAULT_MIN_TICKS = 30
HARD_MIN_TICKS = 30


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return int(default)
    try:
        return int(float(str(raw).strip()))
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def resolve_required_soak_ticks(requested: Optional[int] = None) -> int:
    """Soak may be raised by configuration but never lowered below 30."""
    if requested is None:
        requested = _env_int("UP_POSTLOAD_SOAK_TICKS", DEFAULT_MIN_TICKS)
    try:
        value = int(requested)
    except Exception:
        value = DEFAULT_MIN_TICKS
    return max(int(HARD_MIN_TICKS), value)


@dataclass
class ResourceSample:
    t: float
    t_utc: str
    frame: Optional[int]
    rpc_ok: bool
    carla_pid_alive: Optional[bool]
    vram_mb: Optional[float] = None
    rss_mb: Optional[float] = None
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "t": self.t,
            "t_utc": self.t_utc,
            "frame": self.frame,
            "rpc_ok": self.rpc_ok,
            "carla_pid_alive": self.carla_pid_alive,
            "vram_mb": self.vram_mb,
            "rss_mb": self.rss_mb,
            "error": self.error,
        }


def sample_vram_mb() -> Optional[float]:
    try:
        from ultimate_pipeline.core.opendrive_gen_diagnostic import sample_vram_mb as _sample

        return _sample()
    except Exception:
        pass
    try:
        import subprocess

        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text = (out.stdout or "").strip().splitlines()
        if text:
            return float(text[0].strip())
    except Exception:
        return None
    return None


def sample_rss_mb(pid: Optional[int] = None) -> Optional[float]:
    try:
        import psutil  # type: ignore

        proc = psutil.Process(int(pid)) if pid else psutil.Process()
        return float(proc.memory_info().rss) / (1024.0 * 1024.0)
    except Exception:
        return None


class _Marker:
    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def wait(self, timeout: float) -> bool:
        # Stand-in for tests; real waits go through world.tick timeouts.
        return self._event.wait(timeout)


def run_postload_soak(
    world: Any,
    *,
    min_ticks: Optional[int] = None,
    tick_timeout_s: float = 10.0,
    carla_pid: Optional[int] = None,
    client: Any = None,
    state_machine: Any = None,
    resource_sampler: Optional[Callable[[], Dict[str, Any]]] = None,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Advance the world for at least ``min_ticks`` and record evidence.

    Returns a report with ``gate`` in {``MAP_LOADED``, ``MAP_STABLE``}.
    ``MAP_STABLE`` is only returned when the required number of *advancing*
    ticks completed while RPC stayed healthy and the CARLA process stayed
    alive.
    """
    required = resolve_required_soak_ticks(min_ticks)
    started = time.time()
    first_frame: Optional[int] = None
    last_frame: Optional[int] = None
    advancing_ticks = 0
    rpc_failures = 0
    tick_errors: List[str] = []
    samples: List[ResourceSample] = []
    frames_seen: List[int] = []
    pid_alive: Optional[bool] = None

    def _rpc_ok() -> bool:
        if client is None:
            return True
        try:
            client.get_world()
            return True
        except Exception:
            return False

    def _pid_alive() -> Optional[bool]:
        if not carla_pid:
            return None
        try:
            import psutil  # type: ignore

            return bool(psutil.pid_exists(int(carla_pid)))
        except Exception:
            return None

    def _sample(frame: Optional[int]) -> None:
        vram = None
        rss = None
        err = None
        if resource_sampler is not None:
            try:
                custom = resource_sampler() or {}
                vram = custom.get("vram_mb")
                rss = custom.get("rss_mb")
            except Exception as exc:
                err = str(exc)
        else:
            vram = sample_vram_mb()
            rss = sample_rss_mb(carla_pid)
        samples.append(
            ResourceSample(
                t=time.time(),
                t_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                frame=frame,
                rpc_ok=_rpc_ok(),
                carla_pid_alive=_pid_alive() if carla_pid else pid_alive,
                vram_mb=vram,
                rss_mb=rss,
                error=err,
            )
        )

    if state_machine is not None:
        try:
            state_machine._record(
                "POSTLOAD_STABILITY_BEGIN",
                {"required_ticks": required, "gate": MAP_LOADED},
            )
        except Exception:
            pass

    _sample(None)

    deadline_cap = float(required) * max(1.0, float(tick_timeout_s)) + 60.0
    overall_deadline = started + deadline_cap

    while advancing_ticks < required and time.time() < overall_deadline:
        try:
            world.tick(float(tick_timeout_s))
        except Exception as exc:
            tick_errors.append(f"{type(exc).__name__}:{exc}")
            if len(tick_errors) >= 5:
                break
            time.sleep(0.05)
            continue

        frame: Optional[int] = None
        try:
            frame = int(world.get_snapshot().frame)
        except Exception:
            try:
                frame = int(getattr(world, "frame", 0))
            except Exception:
                frame = None

        if frame is not None:
            if first_frame is None:
                first_frame = frame
            if last_frame is not None and frame <= last_frame:
                # tick did not advance -> not an advancing tick
                rpc_failures += 0
                samples.append(
                    ResourceSample(
                        t=time.time(),
                        t_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        frame=frame,
                        rpc_ok=True,
                        carla_pid_alive=_pid_alive() if carla_pid else None,
                        error="non_advancing_tick",
                    )
                )
                continue
            last_frame = frame
            frames_seen.append(frame)
        advancing_ticks += 1

        if not _rpc_ok():
            rpc_failures += 1

        if advancing_ticks % 5 == 0 or advancing_ticks == required:
            _sample(frame)
            if on_progress is not None:
                try:
                    on_progress({"advancing_ticks": advancing_ticks, "required": required, "frame": frame})
                except Exception:
                    pass

    elapsed = time.time() - started
    _sample(last_frame)

    stable = advancing_ticks >= required and rpc_failures == 0 and not tick_errors
    pid_ok = True
    if carla_pid:
        alive = _pid_alive()
        pid_ok = bool(alive)
        stable = stable and pid_ok

    gate = MAP_STABLE if stable else MAP_LOADED

    report: Dict[str, Any] = {
        "schema": "POSTLOAD_STABILITY_REPORT/v1",
        "gate": gate,
        "stable": bool(stable),
        "required_ticks": required,
        "advancing_ticks": advancing_ticks,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "elapsed_simulation_wall_time_s": elapsed,
        "rpc_failures": rpc_failures,
        "rpc_state_throughout": rpc_failures == 0,
        "tick_errors": tick_errors,
        "carla_pid": carla_pid,
        "carla_pid_alive": pid_ok,
        "resource_samples": [s.as_dict() for s in samples],
        "peak_vram_mb": _peak(samples, "vram_mb"),
        "peak_rss_mb": _peak(samples, "rss_mb"),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "note": "MAP_LOADED before soak; MAP_STABLE only after the soak gate passes.",
    }

    if state_machine is not None:
        try:
            state_machine._record(
                "POSTLOAD_STABILITY_RETURN",
                {"gate": gate, "advancing_ticks": advancing_ticks, "stable": bool(stable)},
            )
        except Exception:
            pass
        if stable:
            try:
                state_machine._record("MAP_STABLE", {"gate": gate})
            except Exception:
                pass

    return report


def _peak(samples: List[ResourceSample], attr: str) -> Optional[float]:
    values: List[float] = []
    for sample in samples:
        value = getattr(sample, attr, None)
        if isinstance(value, (int, float)):
            values.append(float(value))
    if not values:
        return None
    return max(values)


def write_soak_report(report: Dict[str, Any], path: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def assert_perception_may_start(report: Dict[str, Any]) -> None:
    """Fail-closed gate: perception may not start from merely MAP_LOADED."""
    if not report or report.get("gate") != MAP_STABLE:
        advancing = (report or {}).get("advancing_ticks", 0)
        required = (report or {}).get("required_ticks", HARD_MIN_TICKS)
        raise RuntimeError(
            "postload_stability_gate_failed:"
            f"gate={(report or {}).get('gate')}:"
            f"advancing_ticks={advancing}:required={required}"
        )
