from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ultimate_pipeline.carla_tools.map_registry import map_names_match
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.carla_utils import autostart_carla_if_needed, ensure_carla_ready


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _build_use_current_world_cmd(
    *, town: str, host: str, port: int, calib: str, capture_out: str
) -> str:
    return (
        "python -m ultimate_pipeline.tools.run_perception_safe "
        f"--manual-town {town} --town {town} --use-current-world "
        f"--calib {calib} --out {capture_out} --host {host} --port {port}"
    )


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Preload helper for Grid0828/Grid0821 CARLA perception runs."
    )
    ap.add_argument("--town", required=True, help="Target map name (e.g. Grid0828, Grid0821).")
    ap.add_argument(
        "--host",
        default=str(getattr(SETTINGS, "CARLA_HOST", "127.0.0.1")),
        help="CARLA host (default: settings CARLA_HOST).",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=int(getattr(SETTINGS, "CARLA_PORT", 2000)),
        help="CARLA RPC port (default: settings CARLA_PORT).",
    )
    ap.add_argument(
        "--wait-carla-ready",
        type=float,
        default=45.0,
        help="Max seconds to wait for CARLA readiness after autostart.",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("."),
        help="Directory where preload_status.json is written (default: current directory).",
    )
    ap.add_argument(
        "--calib",
        default="calib_data.json",
        help="Calibration path used for suggested run_perception_safe command.",
    )
    ap.add_argument(
        "--capture-out",
        default="runs/out",
        help="Suggested --out value in operator command for run_perception_safe.",
    )
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    requested_town = str(args.town or "").strip()
    town_norm = requested_town.lower()
    out_dir = Path(args.out)
    status_path = out_dir / "preload_status.json"

    payload: Dict[str, Any] = {
        "map": requested_town,
        "ok": False,
        "carla_host": str(args.host),
        "carla_port": int(args.port),
        "mode": "unknown",
        "current_map_name": "",
        "use_current_world_cmd": _build_use_current_world_cmd(
            town=requested_town,
            host=str(args.host),
            port=int(args.port),
            calib=str(args.calib),
            capture_out=str(args.capture_out),
        ),
        "operator_instruction": "",
        "failure_reason": "",
        "failure_detail": "",
        "started_utc": _now_utc_iso(),
        "ended_utc": "",
    }

    if _env_flag("UP_DISABLE_CARLA", False):
        payload["mode"] = "disabled"
        payload["failure_reason"] = "disabled_by_env"
        payload["failure_detail"] = "UP_DISABLE_CARLA=1"
        payload["ended_utc"] = _now_utc_iso()
        _write_json(status_path, payload)
        print(f"[preload_map] CARLA disabled by env; wrote {status_path}")
        return 0

    try:
        client = autostart_carla_if_needed(
            host=str(args.host),
            port=int(args.port),
            timeout_s=float(args.wait_carla_ready),
        )
        if not ensure_carla_ready(
            client,
            retries=max(1, int(float(args.wait_carla_ready))),
            delay_s=1.0,
            require_map=True,
        ):
            raise RuntimeError("CARLA not ready after preload wait")

        world = client.get_world()
        current_map_name = str(world.get_map().name or "")
        payload["current_map_name"] = current_map_name

        if town_norm == "grid0821":
            payload["mode"] = "manual_preload_required"
            payload["ok"] = True
            payload["operator_instruction"] = (
                "Grid0821 map travel is intentionally avoided. Load Grid0821 manually in CARLA GUI, "
                "then run the use_current_world command in this JSON."
            )
            payload["ended_utc"] = _now_utc_iso()
            _write_json(status_path, payload)
            print("[preload_map] Grid0821 requires manual GUI preload.")
            print(payload["operator_instruction"])
            print(payload["use_current_world_cmd"])
            return 0

        payload["mode"] = "auto_load_world"
        loaded_world = client.load_world(requested_town)
        if not ensure_carla_ready(
            client,
            retries=max(1, int(float(args.wait_carla_ready))),
            delay_s=1.0,
            require_map=True,
        ):
            raise RuntimeError(f"load_world('{requested_town}') did not become ready")

        loaded_map_name = str(loaded_world.get_map().name or "")
        payload["current_map_name"] = loaded_map_name
        payload["map_match"] = bool(map_names_match(loaded_map_name, requested_town))
        if not bool(payload["map_match"]):
            payload["failure_reason"] = "WRONG_MAP_LOADED"
            payload["failure_detail"] = (
                f"expected '{requested_town}', got '{loaded_map_name}'"
            )
            payload["ended_utc"] = _now_utc_iso()
            _write_json(status_path, payload)
            print(f"[preload_map] WRONG_MAP_LOADED: {payload['failure_detail']}")
            return 1

        payload["ok"] = True
        payload["ended_utc"] = _now_utc_iso()
        _write_json(status_path, payload)
        print(f"[preload_map] Loaded map: {loaded_map_name}")
        return 0
    except Exception as exc:
        payload["failure_reason"] = "PRELOAD_FAILED"
        payload["failure_detail"] = f"{exc.__class__.__name__}: {exc}"
        payload["ended_utc"] = _now_utc_iso()
        _write_json(status_path, payload)
        print(f"[preload_map] FAIL: {payload['failure_detail']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
