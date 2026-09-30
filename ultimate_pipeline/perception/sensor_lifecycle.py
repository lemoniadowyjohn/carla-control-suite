"""Single sensor lifecycle authority (NEW-267).

Every path that stops, drains or destroys a streaming sensor in this repository
must go through this module.  Before it existed, ``ThesisSensorRig`` performed
``actor.destroy()`` directly from ``_cleanup_spawned_sensor_actors()``, which
bypasses the Grid instability policy and turns a partial-spawn cleanup into a
crash vector.

Policy
------
``LifecyclePolicy.KNOWN_UNSTABLE``
    For Grid0821 / Grid0828 / generated OpenDRIVE worlds known to be unstable:
      * stop callbacks
      * drain in-flight writes
      * do **not** individually destroy streaming sensors
      * mark the process/session disposable

``LifecyclePolicy.STABLE``
    For proven-stable maps (e.g. Town10HD): normal controlled teardown including
    per-actor destroy is permitted.

Invariant: **failure cleanup must be at least as safe as successful cleanup.**
Both the success and the exception path call the same functions here.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


class LifecyclePolicy(str, Enum):
    KNOWN_UNSTABLE = "KNOWN_UNSTABLE"
    STABLE = "STABLE"


#: Map names (normalised) treated as known-unstable for destroy purposes.
KNOWN_UNSTABLE_MAPS = frozenset({"grid0821", "grid0828"})


def policy_for_map(map_name: Optional[str]) -> LifecyclePolicy:
    text = str(map_name or "").strip().lower()
    for token in ("/", "\\", "."):
        text = text.replace(token, "/")
    leaf = text.split("/")[-1] if text else ""
    for candidate in (leaf, text):
        if candidate in KNOWN_UNSTABLE_MAPS:
            return LifecyclePolicy.KNOWN_UNSTABLE
    return LifecyclePolicy.STABLE


def is_known_unstable_map(map_name: Optional[str]) -> bool:
    return policy_for_map(map_name) == LifecyclePolicy.KNOWN_UNSTABLE


@dataclass
class LifecycleAction:
    sensor: str
    action: str
    ok: bool
    error: Optional[str] = None
    detail: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sensor": self.sensor,
            "action": self.action,
            "ok": self.ok,
            "error": self.error,
            "detail": self.detail,
        }


@dataclass
class LifecycleReport:
    policy: str
    map_name: Optional[str]
    actions: List[LifecycleAction] = field(default_factory=list)
    destroyed: List[str] = field(default_factory=list)
    stopped: List[str] = field(default_factory=list)
    skipped_destroy: List[str] = field(default_factory=list)
    session_disposable: bool = False
    unsafe_destroy_used: bool = False

    @property
    def ok(self) -> bool:
        return all(a.ok for a in self.actions)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": "SENSOR_LIFECYCLE_REPORT/v1",
            "policy": self.policy,
            "map_name": self.map_name,
            "ok": self.ok,
            "actions": [a.as_dict() for a in self.actions],
            "destroyed": list(self.destroyed),
            "stopped": list(self.stopped),
            "skipped_destroy": list(self.skipped_destroy),
            "session_disposable": self.session_disposable,
            "unsafe_destroy_used": self.unsafe_destroy_used,
        }


def _stop_actor(actor: Any) -> Tuple[bool, Optional[str]]:
    stop = getattr(actor, "stop", None)
    if not callable(stop):
        return True, None
    try:
        stop()
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


def _destroy_actor(actor: Any, *, timeout_s: float = 5.0) -> Tuple[bool, Optional[str]]:
    """Destroy with a watchdog so a wedged RPC cannot hang the whole run."""
    result: Dict[str, Any] = {}

    def _target() -> None:
        try:
            actor.destroy()
            result["ok"] = True
        except Exception as exc:  # pragma: no cover - defensive
            result["ok"] = False
            result["error"] = f"{type(exc).__name__}:{exc}"

    thread = threading.Thread(target=_target, name="sensor-destroy", daemon=True)
    thread.start()
    thread.join(float(timeout_s))
    if thread.is_alive():
        return False, f"destroy_timeout:{timeout_s}s"
    return bool(result.get("ok")), result.get("error")


def stop_sensor_callbacks(
    sensors: Iterable[Tuple[str, Any]],
    *,
    policy: LifecyclePolicy,
    destroy: bool = False,
    drain_timeout_s: float = 5.0,
    map_name: Optional[str] = None,
) -> LifecycleReport:
    """Stop listeners (and optionally destroy) under an explicit policy.

    This is the shared primitive used by the canary, the rig cleanup path and
    the capture teardown so that there is exactly one cleanup authority.
    """
    policy = LifecyclePolicy(policy)
    report = LifecycleReport(policy=policy.value, map_name=map_name)
    items = list(sensors)

    # Phase 1: stop callbacks for everything first (drain order matters more
    # than per-actor completion order).
    for name, actor in items:
        if actor is None:
            report.actions.append(LifecycleAction(name, "stop", True, None, "actor_none"))
            continue
        ok, err = _stop_actor(actor)
        if ok:
            report.stopped.append(name)
        report.actions.append(LifecycleAction(name, "stop", ok, err))

    # Phase 2: give in-flight writer jobs a bounded window to drain.
    if drain_timeout_s and drain_timeout_s > 0:
        time.sleep(min(float(drain_timeout_s), 1.0))

    # Phase 3: destroy only under the STABLE policy (or explicit override).
    allow_destroy = bool(destroy) and policy == LifecyclePolicy.STABLE
    for name, actor in items:
        if actor is None:
            continue
        if not allow_destroy:
            report.skipped_destroy.append(name)
            report.actions.append(
                LifecycleAction(
                    name,
                    "destroy_skipped",
                    True,
                    None,
                    f"policy={policy.value}:individual_destroy_refused",
                )
            )
            continue
        ok, err = _destroy_actor(actor)
        if ok:
            report.destroyed.append(name)
        report.actions.append(LifecycleAction(name, "destroy", ok, err))

    if policy == LifecyclePolicy.KNOWN_UNSTABLE and report.skipped_destroy:
        report.session_disposable = True
    if policy == LifecyclePolicy.KNOWN_UNSTABLE and report.destroyed:
        report.unsafe_destroy_used = True
    return report


def cleanup_spawned_sensors(
    spawned: Dict[str, Any],
    *,
    map_name: Optional[str] = None,
    policy: Optional[LifecyclePolicy] = None,
    destroy: Optional[bool] = None,
    drain_timeout_s: float = 5.0,
    report_path: Any = None,
) -> LifecycleReport:
    """The one authorised cleanup entry point.

    ``spawned`` maps sensor name -> object with an ``actor`` attribute (the
    ``SpawnedSensor`` shape used by ``ThesisSensorRig``).
    """
    resolved_policy = LifecyclePolicy(policy) if policy else policy_for_map(map_name)
    resolved_destroy = (
        (resolved_policy == LifecyclePolicy.STABLE) if destroy is None else bool(destroy)
    )
    pairs: List[Tuple[str, Any]] = []
    for name in reversed(list(spawned.keys())):
        entry = spawned.get(name)
        actor = getattr(entry, "actor", None) if entry is not None else None
        pairs.append((str(name), actor))

    report = stop_sensor_callbacks(
        pairs,
        policy=resolved_policy,
        destroy=resolved_destroy,
        drain_timeout_s=drain_timeout_s,
        map_name=map_name,
    )
    if report_path is not None:
        try:
            target = Path(report_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(
                json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            tmp.replace(target)
        except Exception:
            pass
    return report


def env_forced_policy() -> Optional[LifecyclePolicy]:
    raw = os.environ.get("UP_SENSOR_LIFECYCLE_POLICY")
    if not raw:
        return None
    text = str(raw).strip().upper()
    try:
        return LifecyclePolicy(text)
    except Exception:
        return None
