#!/usr/bin/env python3
"""
Validate that manual CARLA maps are present and loadable.

Usage (PowerShell):
  python -m ultimate_pipeline.diagnostics.validate_manual_maps --maps Grid0821 Grid0828
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence, Any, Optional, Dict

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.carla_tools.carla_server import (
    DEFAULT_FLAGS,
    ensure_carla_server,
    load_map_with_timeout,
    enable_no_rendering,
    get_carla_client,
    available_map_names,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate manual CARLA maps.")
    p.add_argument(
        "--maps",
        nargs="+",
        default=list(getattr(SETTINGS, "MANUAL_CARLA_MAPS", ("Grid0821", "Grid0828"))),
        help="CARLA map names to validate.",
    )
    p.add_argument("--host", default=SETTINGS.CARLA_HOST, help="CARLA host")
    p.add_argument("--port", type=int, default=SETTINGS.CARLA_PORT, help="CARLA port")
    p.add_argument(
        "--carla-exe",
        default=SETTINGS.CARLA_EXE,
        help="Path to CarlaUE4.exe (0.9.16).",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Timeout seconds for map load.",
    )
    p.add_argument(
        "--no-start",
        action="store_true",
        help="Assume CARLA already running; skip restart.",
    )
    p.add_argument(
        "--out",
        default=str(Path(SETTINGS.BASE_OUTPUT_DIR) / "validation" / "manual_maps_report.json"),
        help="Where to write validation JSON report.",
    )
    return p.parse_args()


def _get_client_versions(client: Any) -> tuple[Optional[str], Optional[str]]:
    server_version = None
    client_version = None
    try:
        server_version = client.get_server_version()
    except Exception:
        server_version = None
    try:
        client_version = client.get_client_version()
    except Exception:
        client_version = None
    return server_version, client_version


def _safe_current_map_name(client: Any) -> Optional[str]:
    try:
        world = client.get_world()
        if world is None:
            return None
        carla_map = world.get_map()
        return carla_map.name if carla_map is not None else None
    except Exception:
        return None


def write_report(out_path: Path, payload: Dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def normalize_map_name(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    # Normalize /Game/Carla/Maps/Grid0828 -> Grid0828
    return name.split("/")[-1]


def validate_maps(maps: Sequence[str], host: str, port: int, timeout: float) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "requested_maps": list(maps),
        "available_maps": [],
        "results": [],
        "carla": {
            "host": host,
            "port": int(port),
            "client_version": None,
            "server_version": None,
            "current_world_map_before_load": None,
            "timeouts": {
                "client_timeout_s": float(timeout),
                "map_load_timeout_s": float(timeout),
            },
        },
        "ok": False,
    }
    ok = True
    try:
        client = get_carla_client(host, port, timeout_s=timeout)
        server_version, client_version = _get_client_versions(client)
        report["carla"]["server_version"] = server_version
        report["carla"]["client_version"] = client_version
        report["carla"]["current_world_map_before_load"] = _safe_current_map_name(client)

        available = available_map_names(client)
        report["available_maps"] = available
        available_set = {normalize_map_name(m) for m in available}
    except Exception as exc:
        report["error"] = str(exc)
        report["ok"] = False
        return report

    for m in maps:
        m_norm = normalize_map_name(m)
        entry: Dict[str, Any] = {
            "requested": m,
            "available": bool(m_norm in available_set),
            "loaded_name": None,
            "ok": False,
            "error": None,
            "no_rendering": False,
        }
        if not entry["available"]:
            entry["error"] = "missing"
            ok = False
            report["results"].append(entry)
            print(f"[ERROR] {m} (normalized: {m_norm}) missing from available_maps")
            continue
        try:
            world = load_map_with_timeout(client, m, timeout_s=timeout)
            enable_no_rendering(world)
            map_name = world.get_map().name
            entry["loaded_name"] = map_name
            entry["no_rendering"] = True
            entry["ok"] = (m_norm == normalize_map_name(map_name))
            if not entry["ok"]:
                entry["error"] = f"loaded_map_mismatch:{map_name}"
            print(f"[OK] {m} -> {map_name}")
        except Exception as exc:
            entry["error"] = str(exc)
            print(f"[ERROR] {m} load failed: {exc}")
        if not entry["ok"]:
            ok = False
        report["results"].append(entry)

    report["ok"] = bool(ok)
    return report


def main() -> int:
    args = parse_args()
    startup_error = None
    if not args.no_start:
        try:
            ensure_carla_server(
                host=args.host,
                port=args.port,
                carla_exe=args.carla_exe,
                extra_flags=DEFAULT_FLAGS,
                timeout_s=120.0,
            )
        except Exception as exc:
            startup_error = str(exc)

    report = validate_maps(args.maps, args.host, args.port, args.timeout)
    if startup_error:
        report["startup_error"] = startup_error
        report["ok"] = False
    out_path = Path(args.out)
    report["carla"]["exe"] = str(args.carla_exe)
    report["carla"]["timeouts"]["server_start_timeout_s"] = 120.0
    write_report(out_path, report)
    print(f"[DONE] Wrote validation report to {out_path}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
