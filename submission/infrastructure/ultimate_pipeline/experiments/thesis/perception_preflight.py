#!/usr/bin/env python3
"""Perception preflight CLI: TCP probe and optional CARLA map validation."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Sequence

from ultimate_pipeline.carla_tools.map_registry import normalize_map_name

TCP_TIMEOUT_S = 1.0
CARLA_TIMEOUT_S = 10.0


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CARLA perception preflight checks.")
    parser.add_argument("--config_path", required=True, help="Path to perception config JSON.")
    parser.add_argument(
        "--host",
        help="Optional CARLA host override (defaults to config host if present, else 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Optional CARLA port override (defaults to config port if present, else 2000).",
    )
    parser.add_argument("--expected_map", help="Optional expected CARLA map name.")
    parser.add_argument("--out_dir", help="Optional directory to write preflight.json.")
    parser.add_argument(
        "--carla-timeout-s",
        type=float,
        default=CARLA_TIMEOUT_S,
        help="CARLA client timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "--tcp_only",
        action="store_true",
        help="Only check TCP connectivity; skip CARLA import and map validation.",
    )
    return parser.parse_args(argv)


def _load_config(config_path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        text = config_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None, f"config not found: {config_path}"
    except OSError as exc:
        return None, str(exc)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "config JSON must be an object"
    return data, None


def _resolve_host_port(
    args: argparse.Namespace, config: Optional[Dict[str, Any]]
) -> Tuple[str, int, Optional[str]]:
    host = args.host
    port = args.port
    error: Optional[str] = None

    if config:
        if host is None and isinstance(config.get("host"), str):
            host = config.get("host")
        if port is None and "port" in config:
            try:
                port = int(config["port"])
            except (TypeError, ValueError):
                error = "config port must be an integer"

    if host is None:
        host = "127.0.0.1"
    if port is None:
        port = 2000

    try:
        port_int = int(port)
    except (TypeError, ValueError):
        return host, 0, error or "port must be an integer"

    return host, port_int, error


def _check_tcp(host: str, port: int, timeout: float = TCP_TIMEOUT_S) -> Tuple[bool, Optional[str]]:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, None
    except OSError as exc:
        return False, str(exc)


def _check_carla(host: str, port: int, timeout: float = CARLA_TIMEOUT_S) -> Tuple[bool, Optional[str]]:
    try:
        import carla  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        return False, f"carla import failed: {exc}"

    try:
        client = carla.Client(host, port)
        client.set_timeout(float(timeout))
        world = client.get_world()
        if world is None:
            return False, "CARLA world unavailable"
        carla_map = world.get_map()
        if carla_map is None:
            return False, "CARLA map unavailable"
        return True, carla_map.name
    except Exception as exc:  # pragma: no cover - runtime connection errors
        return False, str(exc)


def _write_report(out_dir: Path, report: Dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "preflight.json"
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)
        f.write("\n")


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    config_path = Path(args.config_path)
    config_data, config_error = _load_config(config_path)
    host, port, host_port_error = _resolve_host_port(args, config_data)

    tcp_ok = False
    carla_ok: Optional[bool] = None
    current_map: Optional[str] = None
    current_map_normalized: Optional[str] = None
    expected_map_normalized: Optional[str] = (
        normalize_map_name(args.expected_map) if args.expected_map else None
    )
    error = config_error or host_port_error
    exit_code = 1 if error else 0

    if exit_code == 0:
        tcp_ok, tcp_error = _check_tcp(host, port)
        if not tcp_ok:
            error = tcp_error or "TCP connection failed"
            exit_code = 2

    if args.tcp_only:
        exit_code = exit_code if exit_code not in (0, 2) else (0 if tcp_ok else 2)
    else:
        if exit_code == 0:
            carla_ok_result, carla_result = _check_carla(host, port, timeout=float(args.carla_timeout_s))
            carla_ok = carla_ok_result
            if carla_ok_result:
                current_map = carla_result
                current_map_normalized = normalize_map_name(current_map or "")
            else:
                error = carla_result or "CARLA handshake failed"
                exit_code = 3

            if carla_ok_result:
                if current_map is None:
                    error = "CARLA map unavailable"
                    carla_ok = False
                    exit_code = 3
                elif (
                    args.expected_map
                    and current_map_normalized != expected_map_normalized
                ):
                    error = (
                        f"expected map '{args.expected_map}' "
                        f"(normalized: '{expected_map_normalized}'), got '{current_map}' "
                        f"(normalized: '{current_map_normalized}')"
                    )
                    exit_code = 4

    if exit_code == 0:
        error = None

    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "host": host,
        "port": port,
        "tcp_ok": tcp_ok,
        "carla_ok": carla_ok,
        "current_map": current_map,
        "current_map_normalized": current_map_normalized,
        "expected_map": args.expected_map,
        "expected_map_normalized": expected_map_normalized,
        "exit_code": exit_code,
        "error": error,
    }

    if args.out_dir:
        _write_report(Path(args.out_dir), report)

    return exit_code


def validate_cooked_manual_maps(
    host: str,
    port: int,
    maps: Sequence[str] = ("Grid0821", "Grid0828"),
    out_dir: Optional[str] = None,
    timeout_s: float = 10.0,
) -> Dict[str, Any]:
    from ultimate_pipeline.diagnostics.validate_manual_maps import validate_maps, write_report

    report = validate_maps(maps, host, int(port), float(timeout_s))
    if out_dir:
        out_path = Path(out_dir) / "cooked_maps_report.json"
        write_report(out_path, report)
    return report


if __name__ == "__main__":
    raise SystemExit(main())
