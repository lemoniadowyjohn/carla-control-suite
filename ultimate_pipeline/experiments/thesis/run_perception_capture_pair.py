#!/usr/bin/env python3
"""
Thesis perception capture pair (manual vs auto) runner.

Minimal orchestration: load manual map/XODR, capture frames, then auto XODR with
the same LocalPerceptionRunner setup. Writes PNG/PLY outputs plus metadata.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from ultimate_pipeline.carla_tools.local_perception_runner import LocalPerceptionRunner
from ultimate_pipeline.experiments.thesis.manual_refs import resolve_manual_town
from ultimate_pipeline.utils.run_provenance import collect_provenance, write_provenance


from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def _resolve(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _resolve_calib_path(explicit_path: Optional[str]) -> str:
    """Resolve calibration JSON path with standardized fallback order."""
    standard_path = Path(__file__).parents[2] / "sensors" / "calib_data.json"
    legacy_path = Path("calib_data.json")

    if explicit_path:
        p = Path(explicit_path).expanduser()
        if p.is_file():
            print(f"Using explicit calib path: {p}")
            return str(p)
        print(f"Warning: Explicit calib path not found: {p}, trying fallbacks")

    if standard_path.is_file():
        print(f"Using standard calib path: {standard_path}")
        return str(standard_path)

    if legacy_path.is_file():
        print(f"Using legacy calib path (CWD): {legacy_path.resolve()}")
        return str(legacy_path)

    print(f"Calib path not found, using default: {standard_path}")
    return str(standard_path)


def _load_and_validate_protocol(protocol_path: str) -> dict:
    """Load and validate a protocol file, raising on error."""
    from ultimate_pipeline.experiments.thesis.protocol import (
        load_protocol,
        validate_protocol,
    )
    protocol = load_protocol(protocol_path)
    protocol["_source_path"] = str(Path(protocol_path).resolve())
    validate_protocol(protocol)
    return protocol


def _write_protocol_snapshot_with_provenance(
    out_dir: Path,
    protocol: dict,
    calib_path: str,
) -> None:
    """Write protocol snapshot and provenance to output directory."""
    from ultimate_pipeline.experiments.thesis.protocol import write_protocol_snapshot

    provenance = collect_provenance(extra={
        "calib_path": calib_path,
        "run_type": "perception_capture_pair",
    })
    write_protocol_snapshot(str(out_dir), protocol, provenance)


def _load_world_builtin(client: carla.Client, map_name: str) -> carla.World:
    _reload_ready_for_sensors(client, map_name=map_name, tm_port=8000)
    world = client.get_world()
    try:
        # CARLA 0.9.16: must use positional float, not keyword arg
        world.wait_for_tick(2.0)
    except Exception:
        pass
    return world


def _load_world_xodr(client: carla.Client, xodr_path: str) -> carla.World:
    xodr_text = Path(xodr_path).read_text(encoding="utf-8")
    from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

    world = load_opendrive_world(client, xodr_text, timeout_s=180.0, retries=1, do_reload=True)
    try:
        # CARLA 0.9.16: must use positional float, not keyword arg
        world.wait_for_tick(2.0)
    except Exception:
        pass
    return world


def _run_capture(
    client: carla.Client,
    world_loader,
    out_dir: Path,
    frames: int,
    calib_path: str,
) -> None:
    # Ensure pair-runner calibration resolution is actually applied by LocalPerceptionRunner.
    from ultimate_pipeline.config.settings import SETTINGS

    resolved_calib = str(Path(calib_path).expanduser().resolve())
    prev_settings_calib = str(getattr(SETTINGS, "SENSOR_CALIB_JSON", ""))
    prev_env_calib = os.environ.get("SENSOR_CALIB_JSON")
    SETTINGS.SENSOR_CALIB_JSON = resolved_calib
    os.environ["SENSOR_CALIB_JSON"] = resolved_calib
    try:
        world_loader()
        runner = LocalPerceptionRunner(client, duration_ticks=int(frames))
        out_dir.mkdir(parents=True, exist_ok=True)
        runner.output_dir = str(out_dir)
        runner.run()
    finally:
        SETTINGS.SENSOR_CALIB_JSON = prev_settings_calib
        if prev_env_calib is None:
            os.environ.pop("SENSOR_CALIB_JSON", None)
        else:
            os.environ["SENSOR_CALIB_JSON"] = prev_env_calib

def _write_load_failure(
    pair_root: Path,
    *,
    stage: str,
    map_or_xodr: str,
    exc: Exception,
    attempt_count: int,
    host: str,
    port: int,
) -> None:
    payload = {
        "stage": stage,
        "map_or_xodr": map_or_xodr,
        "exception": f"{type(exc).__name__}: {exc}",
        "attempt_count": int(attempt_count),
        "host": host,
        "port": int(port),
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (pair_root / "carla_load_failure.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _make_client(host: str, port: int) -> carla.Client:
    import carla

    client = carla.Client(host, port)
    client.set_timeout(30.0)
    return client


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _count_files(path: Path, suffix: str) -> int:
    try:
        return len([p for p in path.iterdir() if p.is_file() and p.name.lower().endswith(suffix)])
    except Exception:
        return 0


def _collect_runner_artifacts(path: Path) -> Dict[str, Optional[str]]:
    return {
        "perception_status": str(path / "perception_status.json"),
        "defects": str(path / "defects.json"),
        "run_meta": str(path / "run_meta.json"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Capture paired perception runs (manual vs auto) for thesis visuals.")
    parser.add_argument("--manual_map", choices=["Grid0821", "Grid0828"], help="Named manual map to load for the manual run.")
    parser.add_argument("--manual_xodr", help="Manual XODR path to load for the manual run.")
    parser.add_argument("--manual-via-xodr", action="store_true", help="Load manual map from XODR instead of cooked town.")
    parser.add_argument("--auto_xodr", required=True, help="Auto-generated XODR to load for the auto run.")
    parser.add_argument("--output_dir", required=True, help="Output directory (pair root).")
    parser.add_argument("--frames", type=int, default=50, help="Number of ticks/frames to capture for each arm.")
    parser.add_argument("--calib-json", default="", help="Calibration JSON path (defaults to ultimate_pipeline/sensors/calib_data.json)")
    parser.add_argument("--protocol", default="", help="Path to thesis protocol YAML for snapshot + validation")
    parser.add_argument("--cooldown-s", type=float, default=None, help="Cooldown seconds before map load (default: env UP_CARLA_COOLDOWN_S or 3.0)")
    args = parser.parse_args(argv)

    if not args.manual_map and not args.manual_xodr:
        parser.error("Provide --manual_map or --manual_xodr")
    if args.manual_map and args.manual_xodr:
        parser.error("Use only one of --manual_map or --manual_xodr")

    auto_xodr_path = Path(args.auto_xodr).expanduser()
    if not auto_xodr_path.is_file():
        parser.error(f"Auto XODR not found: {auto_xodr_path}")

    if args.manual_xodr:
        manual_source = {"type": "xodr", "value": _resolve(args.manual_xodr)}
        manual_loader_path = Path(args.manual_xodr).expanduser()
        if not manual_loader_path.is_file():
            parser.error(f"Manual XODR not found: {manual_loader_path}")
    else:
        if args.manual_via_xodr:
            manual_ref = resolve_manual_town(args.manual_map)
            manual_loader_path = Path(manual_ref["manual_xodr_path"]).expanduser()
            if not manual_loader_path.is_file():
                parser.error(f"Manual XODR not found: {manual_loader_path}")
            manual_source = {"type": "xodr", "value": _resolve(str(manual_loader_path))}
        else:
            manual_source = {"type": "map", "value": args.manual_map}

    # Resolve calibration path with standardized fallback
    calib_path = _resolve_calib_path(args.calib_json if args.calib_json else None)

    pair_root = Path(args.output_dir).expanduser()
    pair_root.mkdir(parents=True, exist_ok=True)

    # Handle protocol if provided
    protocol = None
    if args.protocol:
        print(f"Loading thesis protocol: {args.protocol}")
        protocol = _load_and_validate_protocol(args.protocol)
        _write_protocol_snapshot_with_provenance(pair_root, protocol, calib_path)
        print(f"Protocol snapshot written to: {pair_root}")

    host = os.environ.get("CARLA_HOST", "127.0.0.1")
    port = int(os.environ.get("CARLA_PORT", "2000"))
    cooldown_s = float(
        args.cooldown_s
        if args.cooldown_s is not None
        else os.environ.get("UP_CARLA_COOLDOWN_S", "3.0")
    )
    client = _make_client(host, port)

    manual_dir = pair_root / "manual"
    auto_dir = pair_root / "auto"

    def _load_with_retry(stage: str, map_or_xodr: str, loader) -> None:
        nonlocal client
        time.sleep(cooldown_s)
        try:
            loader()
            return
        except Exception as exc:
            time.sleep(cooldown_s)
            client = _make_client(host, port)
            try:
                loader()
                return
            except Exception as exc2:
                _write_load_failure(
                    pair_root,
                    stage=stage,
                    map_or_xodr=map_or_xodr,
                    exc=exc2,
                    attempt_count=2,
                    host=host,
                    port=port,
                )
                raise

    def _load_manual():
        if manual_source["type"] == "map":
            _load_with_retry("manual_load", manual_source["value"], lambda: _load_world_builtin(client, manual_source["value"]))
        else:
            _load_with_retry("manual_load", manual_source["value"], lambda: _load_world_xodr(client, manual_source["value"]))

    def _load_auto():
        _load_with_retry("auto_load", str(auto_xodr_path), lambda: _load_world_xodr(client, str(auto_xodr_path)))

    ok = True
    error = None
    manual_error = None
    auto_error = None
    try:
        _run_capture(client, _load_manual, manual_dir, args.frames, calib_path)
    except Exception as exc:
        ok = False
        manual_error = f"{type(exc).__name__}: {exc}"
        error = manual_error

    if ok:
        try:
            _run_capture(client, _load_auto, auto_dir, args.frames, calib_path)
        except Exception as exc:
            ok = False
            auto_error = f"{type(exc).__name__}: {exc}"
            error = auto_error

    metadata: Dict[str, Any] = {
        "timestamp_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "carla_host": host,
        "carla_port": port,
        "frames": int(args.frames),
        "manual_source": manual_source,
        "auto_xodr": _resolve(str(auto_xodr_path)),
        "calib_path": calib_path,
        "protocol_used": args.protocol if args.protocol else None,
        "outputs": {
            "pair_root": _resolve(str(pair_root)),
            "manual_dir": _resolve(str(manual_dir)),
            "auto_dir": _resolve(str(auto_dir)),
        },
        "commands": {
            "invocation": " ".join([sys.executable, "-m", "ultimate_pipeline.experiments.thesis.run_perception_capture_pair"] + sys.argv[1:]),
            "manual_run": f"LocalPerceptionRunner(duration_ticks={int(args.frames)}) -> {manual_dir}",
            "auto_run": f"LocalPerceptionRunner(duration_ticks={int(args.frames)}) -> {auto_dir}",
        },
    }
    (pair_root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    manual_status = _safe_read_json(manual_dir / "perception_status.json")
    auto_status = _safe_read_json(auto_dir / "perception_status.json")
    manual_png = _count_files(manual_dir, ".png")
    manual_ply = _count_files(manual_dir, ".ply")
    auto_png = _count_files(auto_dir, ".png")
    auto_ply = _count_files(auto_dir, ".ply")

    perception_metrics = {
        "frames_requested": int(args.frames),
        "frames_written_manual": int(manual_status.get("png_files", manual_png)),
        "frames_written_auto": int(auto_status.get("png_files", auto_png)),
        "file_counts": {
            "manual_png": int(manual_png),
            "manual_ply": int(manual_ply),
            "auto_png": int(auto_png),
            "auto_ply": int(auto_ply),
        },
    }
    (pair_root / "perception_metrics.json").write_text(
        json.dumps(perception_metrics, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    pair_manifest = {
        "ok": bool(ok) and bool(manual_status.get("ok", ok)) and bool(auto_status.get("ok", ok)),
        "error": error,
        "frames": int(args.frames),
        "carla_host": host,
        "carla_port": int(port),
        "manual_source": manual_source,
        "auto_xodr": _resolve(str(auto_xodr_path)),
        "calib_path": calib_path,
        "outputs": {
            "manual_dir": _resolve(str(manual_dir)),
            "auto_dir": _resolve(str(auto_dir)),
        },
        "runner_artifacts": {
            "manual": _collect_runner_artifacts(manual_dir),
            "auto": _collect_runner_artifacts(auto_dir),
        },
        "arm_status": {
            "manual": manual_status,
            "auto": auto_status,
            "manual_error": manual_error,
            "auto_error": auto_error,
        },
    }
    (pair_root / "pair_manifest.json").write_text(
        json.dumps(pair_manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
