from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional


RunFn = Callable[..., subprocess.CompletedProcess[str]]


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _coerce_events(payload: str) -> List[Dict[str, Any]]:
    text = (payload or "").strip()
    if not text:
        return []
    data = json.loads(text)
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _tdr_query_script(*, lookback_hours: float, sample_limit: int) -> str:
    hours = max(0.01, float(lookback_hours))
    limit = max(1, int(sample_limit))
    return f"""
$ErrorActionPreference = 'Stop'
$since = (Get-Date).AddHours(-{hours!r})
$events = @(
  Get-WinEvent -FilterHashtable @{{LogName='Application'; ProviderName='Windows Error Reporting'; StartTime=$since}} -ErrorAction SilentlyContinue |
    Where-Object {{
      ($_.Message -match 'LiveKernelEvent') -and
      (($_.Message -match 'P1\\s*:\\s*141') -or ($_.Message -match 'P1\\s+141') -or ($_.Message -match 'Code\\s*:\\s*141'))
    }} |
    Select-Object -First {limit} @{{Name='timeCreated'; Expression={{$_.TimeCreated.ToString('o')}}}},
      Id, ProviderName, @{{Name='message'; Expression={{$_.Message}}}}
)
$events | ConvertTo-Json -Compress
""".strip()


def windows_gpu_tdr_preflight(
    *,
    lookback_hours: float = 24.0,
    max_events: int = 0,
    sample_limit: Optional[int] = None,
    platform: Optional[str] = None,
    runner: RunFn = subprocess.run,
) -> Dict[str, Any]:
    """
    Fail-closed Windows GPU watchdog preflight for CARLA runtime evidence.

    LiveKernelEvent 141 is a Windows Error Reporting signature for a GPU/display
    watchdog timeout. If recent events exist, CARLA runtime evidence is not
    trustworthy on this machine until the event stream stops.
    """
    current_platform = platform if platform is not None else sys.platform
    if current_platform != "win32":
        return {
            "ok": True,
            "skipped": True,
            "reason": "non_windows",
            "lookback_hours": float(lookback_hours),
            "max_events": int(max_events),
            "events": [],
        }
    if _env_truthy("UP_DISABLE_CARLA"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "carla_disabled",
            "lookback_hours": float(lookback_hours),
            "max_events": int(max_events),
            "events": [],
        }

    limit = int(sample_limit if sample_limit is not None else max(1, int(max_events) + 1))
    script = _tdr_query_script(lookback_hours=float(lookback_hours), sample_limit=limit)
    try:
        proc = runner(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "reason": "event_log_query_failed",
            "detail": str(exc),
            "lookback_hours": float(lookback_hours),
            "max_events": int(max_events),
            "events": [],
        }

    if int(getattr(proc, "returncode", 1) or 0) != 0:
        return {
            "ok": False,
            "skipped": False,
            "reason": "event_log_query_failed",
            "detail": (getattr(proc, "stderr", "") or "").strip()[:2000],
            "lookback_hours": float(lookback_hours),
            "max_events": int(max_events),
            "events": [],
        }

    try:
        events = _coerce_events(getattr(proc, "stdout", "") or "")
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "reason": "event_log_query_invalid_json",
            "detail": str(exc),
            "lookback_hours": float(lookback_hours),
            "max_events": int(max_events),
            "events": [],
        }

    blocked = len(events) > int(max_events)
    return {
        "ok": not blocked,
        "skipped": False,
        "reason": "recent_livekernelevent_141" if blocked else "no_recent_livekernelevent_141",
        "lookback_hours": float(lookback_hours),
        "max_events": int(max_events),
        "event_count_sampled": len(events),
        "sample_limit": limit,
        "events": events,
    }


def windows_gpu_tdr_preflight_from_env() -> Dict[str, Any]:
    lookback = _env_float("UP_CARLA_TDR_LOOKBACK_HOURS", 24.0)
    max_events = _env_int("UP_CARLA_TDR_MAX_EVENTS", 0)
    return windows_gpu_tdr_preflight(lookback_hours=lookback, max_events=max_events)
