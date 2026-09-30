"""Staged sensor bring-up (section 9) + resource budget (section 27).

Escalation ladder::

    S0 map only
    S1 ego vehicle
    S2 one RGB
    S3 RGB + LiDAR
    S4 RGB + semantic camera
    S5 front-only thesis rig
    S6 full thesis rig
    S7 optional NPC / enrichment

After every stage the run must observe advancing world ticks, a live CARLA
process, live RPC, live actors, a first callback where relevant, and VRAM /
host memory below the configured safety ceiling.

If S4 crashes while S3 succeeded, the diagnostics must say exactly that: the
``highest_stage_passed`` field is the authority, not a single boolean.

``LAPTOP_6GB_SAFE`` is the named conservative profile.  VRAM is recorded after
every sensor addition; exceeding the budget raises ``RESOURCE_BUDGET_BLOCK``
*before* the next sensor is attached.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Named profiles
# ---------------------------------------------------------------------------

STAGES: tuple = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7")

STAGE_TITLES: Dict[str, str] = {
    "S0": "map only",
    "S1": "ego vehicle",
    "S2": "one RGB",
    "S3": "RGB + LiDAR",
    "S4": "RGB + semantic camera",
    "S5": "front-only thesis rig",
    "S6": "full thesis rig",
    "S7": "optional NPC/enrichment",
}

PROFILES: Dict[str, Dict[str, Any]] = {
    "LAPTOP_6GB_SAFE": {
        "name": "LAPTOP_6GB_SAFE",
        "description": (
            "Conservative 6 GB VRAM profile: front RGB, front semantic, primary "
            "LiDAR, low-resolution cameras, 0 NPC, no enrichment. Escalate only "
            "after each stage records VRAM below the safety ceiling."
        ),
        "stages": ["S0", "S1", "S2", "S3", "S4"],
        "default_terminate_after_stage": "S4",
        "cameras": ["rgb_front", "semseg_front"],
        "lidar": ["lidar_top"],
        "resolution": {"width": 640, "height": 480},
        "npc_count": 0,
        "enrichment": False,
        "max_total_camera_pixels": 640 * 480 * 2,
        "vram_budget_mb": float(os.environ.get("UP_VRAM_BUDGET_MB", "5600")),
        "host_memory_budget_mb": float(os.environ.get("UP_HOST_MEM_BUDGET_MB", "12288")),
        "escalation": (
            "Start conservatively; escalate only when the previous stage's "
            "recorded peak VRAM stays under vram_budget_mb."
        ),
    },
    "THESIS_FULL": {
        "name": "THESIS_FULL",
        "description": "Full governed thesis rig (S6).",
        "stages": list(STAGES[:7]),
        "default_terminate_after_stage": "S6",
        "cameras": None,
        "lidar": None,
        "resolution": None,
        "npc_count": 0,
        "enrichment": False,
        "vram_budget_mb": float(os.environ.get("UP_VRAM_BUDGET_MB", "5600")),
        "host_memory_budget_mb": float(os.environ.get("UP_HOST_MEM_BUDGET_MB", "12288")),
    },
    "DEFAULT": {
        "name": "DEFAULT",
        "stages": list(STAGES),
        "default_terminate_after_stage": "S6",
        "vram_budget_mb": float(os.environ.get("UP_VRAM_BUDGET_MB", "5600")),
        "host_memory_budget_mb": float(os.environ.get("UP_HOST_MEM_BUDGET_MB", "12288")),
    },
}


def resolve_profile(name: Optional[str] = None) -> Dict[str, Any]:
    key = str(name or os.environ.get("UP_CAPTURE_PROFILE") or "DEFAULT").strip()
    if key not in PROFILES:
        # allow env alias for the laptop profile
        lowered = key.lower()
        for candidate, payload in PROFILES.items():
            if candidate.lower() == lowered:
                return dict(payload)
        raise KeyError(
            f"unknown_capture_profile:{key}:available={sorted(PROFILES)}"
        )
    return dict(PROFILES[key])


class ResourceBudgetBlock(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Stage runner
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    stage: str
    title: str
    passed: bool = False
    skipped: bool = False
    reason: str = ""
    ticks_advanced: Optional[int] = None
    carla_alive: Optional[bool] = None
    rpc_alive: Optional[bool] = None
    actors_alive: Optional[bool] = None
    first_callback_received: Optional[bool] = None
    vram_mb: Optional[float] = None
    rss_mb: Optional[float] = None
    vram_budget_mb: Optional[float] = None
    host_memory_budget_mb: Optional[float] = None
    resource_budget_block: bool = False
    duration_s: float = 0.0
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "title": self.title,
            "passed": self.passed,
            "skipped": self.skipped,
            "reason": self.reason,
            "checks": {
                "world_ticks_advance": self.ticks_advanced,
                "carla_process_alive": self.carla_alive,
                "rpc_alive": self.rpc_alive,
                "actors_alive": self.actors_alive,
                "first_callback_received": self.first_callback_received,
                "vram_mb": self.vram_mb,
                "rss_mb": self.rss_mb,
                "vram_budget_mb": self.vram_budget_mb,
                "host_memory_budget_mb": self.host_memory_budget_mb,
            },
            "resource_budget_block": self.resource_budget_block,
            "duration_s": self.duration_s,
            "detail": self.detail,
        }


def run_staged_bringup(
    *,
    stage_checks: Dict[str, Callable[[], Dict[str, Any]]],
    profile: Optional[str] = None,
    stop_after: Optional[str] = None,
    resource_probe: Optional[Callable[[], Dict[str, Any]]] = None,
    on_stage: Optional[Callable[[StageResult], None]] = None,
    start_stage: str = "S0",
) -> Dict[str, Any]:
    """Run stages S0..S7 in order, stopping at the first failure.

    ``stage_checks`` maps stage name -> callable returning a dict with at least
    ``{passed: bool}`` and optionally ``{ticks_advanced, carla_alive,
    rpc_alive, actors_alive, first_callback_received, detail}``.
    """
    resolved = resolve_profile(profile)
    budget_vram = float(resolved.get("vram_budget_mb") or 0.0) or None
    budget_rss = float(resolved.get("host_memory_budget_mb") or 0.0) or None
    terminator = str(stop_after or resolved.get("default_terminate_after_stage") or "S6")

    results: List[StageResult] = []
    started_all = time.time()

    if start_stage in STAGES:
        skip_idx = STAGES.index(start_stage)
    else:
        skip_idx = 0

    highest_passed: Optional[str] = None
    failed_stage: Optional[str] = None

    for index, stage in enumerate(STAGES):
        result = StageResult(stage=stage, title=STAGE_TITLES[stage])
        if index < skip_idx:
            result.skipped = True
            result.reason = f"skipped_before_start_stage:{start_stage}"
            results.append(result)
            continue
        if stage not in stage_checks:
            result.skipped = True
            result.reason = "no_check_registered_for_stage"
            results.append(result)
            continue

        started = time.time()
        probe: Dict[str, Any] = {}
        if resource_probe is not None:
            try:
                probe = resource_probe() or {}
            except Exception as exc:
                probe = {"probe_error": f"{type(exc).__name__}:{exc}"}

        result.vram_mb = probe.get("vram_mb")
        result.rss_mb = probe.get("rss_mb")
        result.vram_budget_mb = budget_vram
        result.host_memory_budget_mb = budget_rss

        # Budget check happens BEFORE attaching anything further.
        if budget_vram and isinstance(result.vram_mb, (int, float)) and float(result.vram_mb) > budget_vram:
            result.passed = False
            result.resource_budget_block = True
            result.reason = (
                f"RESOURCE_BUDGET_BLOCK:vram={result.vram_mb:.1f}MB>"
                f"budget={budget_vram:.1f}MB:before_stage={stage}"
            )
            result.duration_s = time.time() - started
            results.append(result)
            failed_stage = stage
            if on_stage:
                on_stage(result)
            break

        if budget_rss and isinstance(result.rss_mb, (int, float)) and float(result.rss_mb) > budget_rss:
            result.passed = False
            result.resource_budget_block = True
            result.reason = (
                f"RESOURCE_BUDGET_BLOCK:host_rss={result.rss_mb:.1f}MB>"
                f"budget={budget_rss:.1f}MB:before_stage={stage}"
            )
            result.duration_s = time.time() - started
            results.append(result)
            failed_stage = stage
            if on_stage:
                on_stage(result)
            break

        try:
            payload = stage_checks[stage]() or {}
        except Exception as exc:
            payload = {"passed": False, "error": f"{type(exc).__name__}:{exc}"}

        result.passed = bool(payload.get("passed"))
        result.reason = str(payload.get("reason") or ("ok" if result.passed else "stage_check_failed"))
        result.ticks_advanced = payload.get("ticks_advanced")
        result.carla_alive = payload.get("carla_alive")
        result.rpc_alive = payload.get("rpc_alive")
        result.actors_alive = payload.get("actors_alive")
        result.first_callback_received = payload.get("first_callback_received")
        result.detail = {k: v for k, v in payload.items() if k not in {
            "passed", "reason", "ticks_advanced", "carla_alive", "rpc_alive",
            "actors_alive", "first_callback_received",
        }}
        result.duration_s = time.time() - started

        if result.vram_mb is None:
            result.vram_mb = payload.get("vram_mb")
        if result.rss_mb is None:
            result.rss_mb = payload.get("rss_mb")

        results.append(result)
        if on_stage:
            on_stage(result)

        if not result.passed:
            failed_stage = stage
            break
        highest_passed = stage
        if stage == terminator:
            break

    passed = failed_stage is None and highest_passed is not None
    payload = {
        "schema": "STAGED_BRINGUP/v1",
        "profile": resolved.get("name"),
        "passed": bool(passed),
        "highest_stage_passed": highest_passed,
        "failed_stage": failed_stage,
        "termination_stage": terminator,
        "stages": [r.as_dict() for r in results],
        "elapsed_s": time.time() - started_all,
        "diagnostic_note": (
            "If S4 fails while S3 passes, highest_stage_passed=S3 and "
            f"failed_stage={failed_stage} make the distinction explicit; a "
            "single boolean cannot express it."
        ),
        "budgets": {"vram_mb": budget_vram, "host_memory_budget_mb": budget_rss},
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return payload


def record_vram_after_sensor(payload: Dict[str, Any], sensor: str, vram_mb: Optional[float]) -> Dict[str, Any]:
    """Append an empirical VRAM observation (never a pixel-count heuristic)."""
    history = payload.setdefault("vram_history", [])
    history.append(
        {
            "after_sensor": str(sensor),
            "vram_mb": vram_mb,
            "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    return payload


def assert_within_budget(vram_mb: Optional[float], *, budget_mb: Optional[float]) -> None:
    if budget_mb and isinstance(vram_mb, (int, float)) and float(vram_mb) > float(budget_mb):
        raise ResourceBudgetBlock(
            f"RESOURCE_BUDGET_BLOCK:vram={float(vram_mb):.1f}MB>budget={float(budget_mb):.1f}MB"
        )


def write_bringup_report(payload: Dict[str, Any], path: Any) -> Path:
    target = Path(str(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def profile_names() -> Sequence[str]:
    return tuple(sorted(PROFILES))
