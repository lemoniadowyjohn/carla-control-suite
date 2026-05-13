#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fast CARLA map-only probe for Grid smoke preflight.

Loads a requested town map (if needed), validates map identity, advances a single
simulation tick, writes probe_result.json, and exits.

Supports:
- Cooked CARLA maps (Grid0828, Grid0821, Town01-10, etc.) via load_world()
- OpenDRIVE-based custom maps via generate_opendrive_world()

Stage-1 probe: Validates map identity BEFORE any sensor attachment.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ultimate_pipeline.carla_tools.map_registry import (
    copy_latest_carla_log,
    get_load_world_candidates,
    get_map_type,
    map_names_match,
    normalize_map_name,
    resolve_available_load_world_targets,
    resolve_expected_names,
    safe_get_available_maps,
)
from ultimate_pipeline.carla_tools.reload_ready_for_sensors import (
    _reload_ready_for_sensors,
)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Load/validate a CARLA map and tick once (no sensors)."
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--town", required=True, type=str)
    ap.add_argument("--expected-map-name", type=str, default="")
    ap.add_argument("--out", "--out-dir", dest="out", required=True, type=Path)
    ap.add_argument("--timeout-s", type=float, default=120.0)
    ap.add_argument("--tick-timeout-s", type=float, default=2.0)
    ap.add_argument("--use-current-world", action="store_true")
    ap.add_argument("--xodr-path", type=Path, default=None,
                    help="Explicit XODR path for OpenDRIVE maps (forces XODR mode)")
    ap.add_argument("--retries", type=int, default=2,
                    help="Number of load_world retry attempts")
    ap.add_argument("--settle-delay-s", type=float, default=1.0,
                    help="Delay after map load before verification")
    return ap.parse_args()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(
        text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8", newline="\n"
    )


def _tcp_port_open(host: str, port: int, timeout_s: float = 0.8) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(float(timeout_s))
        return bool(sock.connect_ex((str(host), int(port))) == 0)
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _capture_map_name(world: Any) -> str:
    """Capture raw map name from CARLA world."""
    try:
        carla_map = world.get_map()
        return str(getattr(carla_map, "name", "") or "UNKNOWN")
    except Exception:
        return "UNKNOWN"


def _classify_exception(
    *,
    exc: Exception,
    host: str,
    port: int,
    map_load_attempted: bool,
    rpc_after_load: Optional[bool],
) -> str:
    """Classify probe exception into failure reason."""
    msg = str(exc or "")

    if "MAP_NOT_AVAILABLE" in msg:
        return "MAP_NOT_AVAILABLE"
    if "MAP_LOAD_ENGINE_FATAL" in msg:
        return "MAP_LOAD_ENGINE_FATAL"
    if "WRONG_MAP_LOADED" in msg:
        return "WRONG_MAP_LOADED"
    if "XODR_NOT_FOUND" in msg:
        return "XODR_NOT_FOUND"
    if "timeout" in msg.lower():
        return "MAP_LOAD_TIMEOUT"
    if "RPC" in msg or "connection" in msg.lower():
        return "MAP_LOAD_RPC_FAILED"

    if bool(map_load_attempted) and rpc_after_load is False:
        return "MAP_LOAD_ENGINE_FATAL"
    # For map preflight we treat map-load/tick failures as engine-fatal.
    if bool(map_load_attempted):
        return "ENGINE_FATAL"
    if not _tcp_port_open(str(host), int(port), timeout_s=0.5):
        return "ENGINE_FATAL"

    return "ENGINE_FATAL"


def _load_cooked_map_with_retry(
    client: Any,
    candidates: List[str],
    retries: int,
    timeout_s: float,
    settle_delay_s: float,
    host: str,
    port: int,
) -> tuple[Any, str, List[Dict[str, Any]]]:
    """
    Attempt to load a cooked map with retry logic.

    Args:
        client: CARLA client
        candidates: List of map names to try
        retries: Number of retry attempts per candidate
        timeout_s: Timeout for load_world
        settle_delay_s: Delay after load before verification

    Returns:
        Tuple of (world, actual_map_name_raw, load_attempts_log)

    Raises:
        RuntimeError on all attempts exhausted
    """
    load_attempts: List[Dict[str, Any]] = []

    try:
        client.set_timeout(float(timeout_s))
    except Exception:
        pass

    last_exc: Optional[Exception] = None

    for candidate in candidates:
        for attempt in range(1, retries + 1):
            attempt_record = {
                "candidate": candidate,
                "attempt": attempt,
                "success": False,
                "actual_map_name_raw": "",
                "error": "",
            }

            try:
                print(f"[probe] load_world attempt {attempt}/{retries}: '{candidate}'")
                world = _reload_ready_for_sensors(client, map_name=candidate, tm_port=8000)

                # Settle delay
                if settle_delay_s > 0:
                    time.sleep(settle_delay_s)

                # Try to advance ticks for stability
                try:
                    settings = world.get_settings()
                    if bool(getattr(settings, "synchronous_mode", False)):
                        for _ in range(3):
                            world.tick()
                    else:
                        for _ in range(3):
                            world.wait_for_tick(seconds=2.0)
                except Exception:
                    pass

                actual_raw = _capture_map_name(world)
                attempt_record["actual_map_name_raw"] = actual_raw
                attempt_record["success"] = True
                load_attempts.append(attempt_record)

                return world, actual_raw, load_attempts

            except Exception as e:
                last_exc = e
                attempt_record["error"] = f"{type(e).__name__}: {e}"
                load_attempts.append(attempt_record)
                print(f"[probe] load_world failed: {e}")
                if not _tcp_port_open(str(host), int(port), timeout_s=0.8):
                    raise RuntimeError(
                        f"MAP_LOAD_ENGINE_FATAL: RPC unreachable after load_world('{candidate}')"
                    ) from e
                time.sleep(0.5)

    raise RuntimeError(
        f"MAP_LOAD_EXHAUSTED: All load attempts failed. Last error: {last_exc}"
    )


def _load_xodr_map(
    client: Any,
    xodr_path: Path,
    timeout_s: float,
) -> tuple[Any, str]:
    """Load map via OpenDRIVE."""
    from ultimate_pipeline.core.carla_opendrive_loader import (
        load_opendrive_world_from_file,
    )

    print(f"[probe] Loading map via XODR: {xodr_path}")
    world = load_opendrive_world_from_file(
        client,
        xodr_path,
        timeout_s=float(timeout_s),
        retries=2,
        do_reload=True,
    )
    actual_raw = _capture_map_name(world)
    return world, actual_raw


def main() -> int:
    args = _parse_args()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probe_result_path = out_dir / "probe_result.json"

    requested_town = str(args.town or "").strip()
    expected_map_name = str(args.expected_map_name or requested_town or "").strip()
    timeout_s = max(5.0, float(args.timeout_s))
    tick_timeout_s = max(0.5, float(args.tick_timeout_s))
    retries = max(1, int(args.retries))
    settle_delay_s = max(0.0, float(args.settle_delay_s))

    # Resolve expected names
    resolution = resolve_expected_names(expected_map_name)
    map_type = resolution["map_type"]

    # Force XODR mode if explicit path provided
    if args.xodr_path and args.xodr_path.exists():
        map_type = "xodr"

    started_utc = datetime.now(timezone.utc).isoformat()
    payload: Dict[str, Any] = {
        "schema_version": 4,
        "started_utc": started_utc,
        "ended_utc": "",
        "ok": False,
        "status": "FAIL",
        "failure_reason": "",
        "failure_detail": "",
        "exception_text": "",
        "host": str(args.host),
        "port": int(args.port),

        # Requested map info
        "requested_map_name": requested_town,
        "expected_map_name": expected_map_name,
        "expected_normalized": resolution["expected_normalized"],
        "acceptable_normalized_set": list(resolution["acceptable_normalized_set"]),
        "canonical_name": resolution["canonical_name"],
        "map_type": map_type,

        # Actual map info (filled after load)
        "actual_map_name_raw": "",
        "actual_map_name_normalized": "",

        # Match result
        "map_match": False,
        "mismatch": False,

        # Load details
        "timeout_s": float(timeout_s),
        "tick_timeout_s": float(tick_timeout_s),
        "use_current_world": bool(args.use_current_world),
        "map_load_attempted": False,
        "load_attempts": [],
        "load_candidates": [],
        "load_candidates_selected": [],
        "available_maps_count": 0,
        "available_maps_sample": [],
        "available_maps_hash": "",
        "available_maps_query_ok": False,
        "available_maps_query_error": "",
        "xodr_path": str(args.xodr_path) if args.xodr_path else "",

        # Probe result
        "map_name_before": "",
        "last_successful_world_name": "",
        "carla_rpc_after_load": None,
        "carla_log_path": "",
        "world_loaded": False,
        "correct_world_identity": False,
        "tick_ok": False,
    }

    try:
        from ultimate_pipeline.core.carla_utils import autostart_carla_if_needed

        client = autostart_carla_if_needed(str(args.host), int(args.port))
        try:
            client.set_timeout(float(timeout_s))
        except Exception:
            pass

        world = client.get_world()
        map_name_before = _capture_map_name(world)
        payload["map_name_before"] = str(map_name_before)
        payload["last_successful_world_name"] = str(map_name_before)

        actual_raw = map_name_before
        load_attempts: List[Dict[str, Any]] = []

        if not bool(args.use_current_world):
            # Check if current map already matches
            if map_names_match(map_name_before, expected_map_name):
                print(f"[probe] Map already matches: {map_name_before}")
                actual_raw = map_name_before
            else:
                payload["map_load_attempted"] = True

                if map_type == "xodr" and args.xodr_path:
                    # XODR loading
                    world, actual_raw = _load_xodr_map(
                        client, args.xodr_path, timeout_s
                    )
                    load_attempts.append({
                        "candidate": str(args.xodr_path),
                        "attempt": 1,
                        "success": True,
                        "actual_map_name_raw": actual_raw,
                        "mode": "xodr",
                    })
                else:
                    # Cooked map loading
                    candidates = get_load_world_candidates(requested_town)
                    payload["load_candidates"] = list(candidates)

                    available_info = safe_get_available_maps(
                        client,
                        query_timeout_s=min(timeout_s, 30.0),
                        restore_timeout_s=min(timeout_s, 30.0),
                    )
                    payload["available_maps_query_ok"] = bool(available_info.get("ok", False))
                    payload["available_maps_query_error"] = str(available_info.get("error", "") or "")
                    payload["available_maps_count"] = int(available_info.get("available_maps_count", 0) or 0)
                    payload["available_maps_sample"] = list(available_info.get("available_maps_sample", []) or [])
                    payload["available_maps_hash"] = str(available_info.get("available_maps_hash", "") or "")

                    resolved = resolve_available_load_world_targets(
                        requested_town,
                        list(available_info.get("maps", []) or []),
                    )
                    selected = list(resolved.get("matched_targets", []) or [])
                    payload["load_candidates_selected"] = selected

                    if not selected:
                        raise RuntimeError(
                            "MAP_NOT_AVAILABLE: requested "
                            f"'{requested_town}' is not advertised by CARLA; "
                            f"available_maps_count={int(payload['available_maps_count'])}"
                        )

                    world, actual_raw, load_attempts = _load_cooked_map_with_retry(
                        client,
                        selected,
                        retries=retries,
                        timeout_s=timeout_s,
                        settle_delay_s=settle_delay_s,
                        host=str(args.host),
                        port=int(args.port),
                    )

        payload["load_attempts"] = load_attempts
        payload["actual_map_name_raw"] = str(actual_raw)
        payload["actual_map_name_normalized"] = normalize_map_name(actual_raw)
        payload["last_successful_world_name"] = str(actual_raw)
        payload["world_loaded"] = True

        # Validate map identity
        map_match = map_names_match(actual_raw, expected_map_name)
        payload["map_match"] = map_match
        payload["mismatch"] = bool(not map_match)
        payload["correct_world_identity"] = bool(map_match)

        if not map_match:
            raise RuntimeError(
                f"WRONG_MAP_LOADED: expected '{expected_map_name}' "
                f"(normalized: '{resolution['expected_normalized']}'), "
                f"got '{actual_raw}' (normalized: '{normalize_map_name(actual_raw)}')"
            )

        # Tick verification
        settings = world.get_settings()
        if bool(getattr(settings, "synchronous_mode", False)):
            world.tick()
        else:
            world.wait_for_tick(seconds=float(tick_timeout_s))

        payload["tick_ok"] = True
        payload["ok"] = True
        payload["status"] = "PASS"
        payload["failure_reason"] = ""
        payload["failure_detail"] = ""
        payload["exception_text"] = ""
        payload["carla_rpc_after_load"] = bool(
            _tcp_port_open(str(args.host), int(args.port), timeout_s=0.8)
        )
        payload["ended_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(probe_result_path, payload)
        print(f"[probe] SUCCESS: map={actual_raw}, normalized={normalize_map_name(actual_raw)}")
        return 0

    except Exception as exc:
        rpc_after_load: Optional[bool] = None
        if bool(payload.get("map_load_attempted", False)):
            rpc_after_load = bool(
                _tcp_port_open(str(args.host), int(args.port), timeout_s=0.8)
            )
            payload["carla_rpc_after_load"] = bool(rpc_after_load)
            if rpc_after_load is False:
                payload["carla_log_path"] = copy_latest_carla_log(out_dir)

        failure_reason = _classify_exception(
            exc=exc,
            host=str(args.host),
            port=int(args.port),
            map_load_attempted=bool(payload.get("map_load_attempted", False)),
            rpc_after_load=rpc_after_load,
        )
        payload["ok"] = False
        payload["status"] = "FAIL"
        payload["failure_reason"] = str(failure_reason)
        payload["failure_detail"] = f"{exc.__class__.__name__}: {exc}"
        payload["exception_text"] = payload["failure_detail"]
        payload["ended_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(probe_result_path, payload)
        print(f"[probe] FAIL: {failure_reason} - {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
