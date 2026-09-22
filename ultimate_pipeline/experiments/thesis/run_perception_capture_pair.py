#!/usr/bin/env python3
"""
Thesis perception capture pair (manual vs auto) runner -- GOVERNED path.

This is the single AUTHORITATIVE paired-capture entrypoint for the RQ3
manual-vs-auto Ingolstadt perceptual comparison. It enforces the governed
contract (see ultimate_pipeline/perception/rq3_capture_contract.py and
ultimate_pipeline/perception/route_manifest.py, and
docs/runtime/PERCEPTION_CAPTURE_PROTOCOL.md):

* both arms share the same immutable route manifest (geographic poses, not
  "spawn index");
* THESIS_PAIRED_STRICT mode forbids hidden spawn recovery / shuffle and walks
  the route deterministically pose-by-pose;
* frame completeness is PASS only when every expected camera/lidar reaches its
  expected frame count;
* every identity equality (route, calibration, sensor rig, weather, timing,
  capture config) is decided by content digest;
* `paired_capture_manifest.json` carries `pair_valid`, the claim boundary
  `claim_level` and explicit `invalid_reasons`.

A Town10HD / control arm may satisfy SENSOR_SMOKE but can never be
`PAIRED_INGOLSTADT_CAPTURE`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover
    import carla  # noqa: F401  (used only in string annotations)

from ultimate_pipeline.carla_tools.local_perception_runner import LocalPerceptionRunner
from ultimate_pipeline.experiments.thesis.manual_refs import resolve_manual_town, sha256_file
from ultimate_pipeline.utils.run_provenance import collect_provenance


from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
from ultimate_pipeline.perception.capture_config import PairedCaptureConfig
from ultimate_pipeline.perception.route_manifest import (
    route_digest,
    validate_paired_route,
    validate_route_manifest,
    validate_route_on_map,
)
from ultimate_pipeline.perception.rq3_capture_contract import (
    COMPLETION_PASS,
    MODE_SMOKE_RECOVERY,
    MODE_THESIS_PAIRED_STRICT,
    build_pair_manifest,
    capture_config_identity,
    carla_client_version,
    carla_server_version,
    classify_claim_level,
    cooked_arm_map_identity,
    enforce_spawn_policy,
    git_sha_of_repo,
    is_ingolstadt_auto_arm,
    is_ingolstadt_manual_arm,
    sensor_rig_from_calib,
    sha256_file as contract_sha256_file,
    sim_timing_identity,
    validate_pair_manifest,
    weather_from_world,
    xodr_arm_map_identity,
)

_FPS = 20


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
    *,
    route_manifest,
    route_mode: str,
    expected_cameras: Dict[str, int],
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
        runner = LocalPerceptionRunner(
            client,
            duration_ticks=int(frames),
            route_manifest=route_manifest,
            route_mode=route_mode,
            expected_cameras=expected_cameras,
        )
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


class _CarlaRouteProbeAdapter:
    """Duck-typed route_manifest.RouteMapAdapter backed by a live CARLA world."""

    def __init__(self, world):
        self._world = world
        self._map = world.get_map()

    def resolve_drivable_waypoint(self, pose: Dict[str, Any]):
        import carla  # type: ignore

        loc = carla.Location(x=float(pose["x"]), y=float(pose["y"]), z=float(pose["z"]))
        wp = self._map.get_waypoint(loc, project_to_road=True)
        if wp is None:
            raise RuntimeError("no_waypoint_for_pose")
        is_driving = True
        try:
            is_driving = wp.lane_type == carla.LaneType.Driving
        except Exception:
            is_driving = True
        dist = wp.transform.location.distance(loc)
        from types import SimpleNamespace

        return SimpleNamespace(
            x=wp.transform.location.x,
            y=wp.transform.location.y,
            z=wp.transform.location.z,
            yaw=wp.transform.rotation.yaw,
            road_id=wp.road_id,
            lane_id=wp.lane_id,
            projection_distance_m=float(dist),
            is_driving=bool(is_driving),
        )


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
        "arm_report": str(path / "arm_report.json"),
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
    parser.add_argument("--fps", type=int, default=_FPS, help="Target FPS (fixed delta = 1/fps).")
    parser.add_argument("--front-only", action="store_true", help="Effective rig = front cameras + primary lidar only.")
    parser.add_argument(
        "--mode",
        choices=[MODE_SMOKE_RECOVERY, MODE_THESIS_PAIRED_STRICT],
        default=os.environ.get("UP_RQ3_MODE", MODE_THESIS_PAIRED_STRICT),
        help="THESIS_PAIRED_STRICT (default) forbids hidden spawn recovery and requires "
        "--route-manifest for any paired claim.",
    )
    parser.add_argument("--route-manifest", default="", help="Path to a paired_route_manifest_v1 JSON shared by both arms.")
    parser.add_argument(
        "--auto-artifact-sha256",
        default=os.environ.get("UP_AUTO_ARTIFACT_SHA256", ""),
        help="final_artifact_authority sha256 of the auto map-of-record pin (verification).",
    )
    parser.add_argument(
        "--auto-ingolstadt-xodr-sha256",
        default=os.environ.get("UP_AUTO_INGOLSTADT_XODR_SHA256", ""),
        help="Map-of-record Ingolstadt XODR sha256; if the auto arm matches it, it is an "
        "Ingolstadt auto arm for claim-level purposes.",
    )
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
    calib_sha256 = contract_sha256_file(calib_path)

    route_mode = str(args.mode)
    route_manifest = None
    route_manifest_sha256 = ""
    if args.route_manifest:
        try:
            route_manifest = json.loads(Path(args.route_manifest).read_text(encoding="utf-8"))
        except Exception as exc:
            parser.error(f"failed to read --route-manifest: {exc}")
        route_errors = validate_route_manifest(route_manifest)
        if route_errors:
            parser.error(f"--route-manifest invalid: {route_errors}")
        route_manifest_sha256 = route_digest(route_manifest)

    if route_mode == MODE_THESIS_PAIRED_STRICT and not route_manifest:
        print(
            "WARNING: THESIS_PAIRED_STRICT mode without a route manifest -- no geographic "
            "route authority supplied, so only an UNPAIRED/CONTROL claim can be made "
            "regardless of frame counts."
        )

    config = PairedCaptureConfig(
        frames=int(args.frames),
        fps=int(args.fps),
        rig="thesis",
        front_only=bool(args.front_only),
        seg=True,
    )
    capture_config_sha256 = capture_config_identity(config)["capture_config_sha256"]
    rig_identity = sensor_rig_from_calib(calib_path, front_only=bool(args.front_only))
    if not rig_identity["sensor_rig_sha256"]:
        print("WARNING: could not build effective sensor-rig identity from calib file.")
    expected_cameras: Dict[str, int] = {
        name: int(args.frames)
        for name in rig_identity["camera_names"] + rig_identity["lidar_names"]
    }

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
        except Exception:
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
    manual_world = None
    auto_world = None
    try:
        manual_world = _load_manual()
        _run_capture(
            client,
            lambda: None,
            manual_dir,
            args.frames,
            calib_path,
            route_manifest=route_manifest,
            route_mode=route_mode,
            expected_cameras=expected_cameras,
        )
    except Exception as exc:
        ok = False
        manual_error = f"{type(exc).__name__}: {exc}"
        error = manual_error

    if ok:
        try:
            auto_world = _load_auto()
            _run_capture(
                client,
                lambda: None,
                auto_dir,
                args.frames,
                calib_path,
                route_manifest=route_manifest,
                route_mode=route_mode,
                expected_cameras=expected_cameras,
            )
        except Exception as exc:
            ok = False
            auto_error = f"{type(exc).__name__}: {exc}"
            error = auto_error

    metadata: Dict[str, Any] = {
        "timestamp_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "carla_host": host,
        "carla_port": port,
        "frames": int(args.frames),
        "fps": int(args.fps),
        "front_only": bool(args.front_only),
        "route_mode": route_mode,
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
            "manual_run": f"LocalPerceptionRunner(duration_ticks={int(args.frames)}, route_mode={route_mode}) -> {manual_dir}",
            "auto_run": f"LocalPerceptionRunner(duration_ticks={int(args.frames)}, route_mode={route_mode}) -> {auto_dir}",
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

    # ------------------------------------------------------------------
    # Governed contract: identities, mandatory equalities, claim boundary.
    # ------------------------------------------------------------------
    manual_weather = weather_from_world(manual_world) if manual_world is not None else {"weather_sha256": "", "parameters": {}}
    auto_weather = weather_from_world(auto_world) if auto_world is not None else {"weather_sha256": "", "parameters": {}}
    timing = sim_timing_identity(
        synchronous_mode=True,
        fixed_delta_seconds=1.0 / float(args.fps),
        traffic_manager_sync=True,
        fps_target=float(args.fps),
        warmup_ticks=0,
        capture_ticks=int(args.frames),
    )

    manual_spawn_record = _safe_read_json(manual_dir / "ego_spawn_report.json")
    auto_spawn_record = _safe_read_json(auto_dir / "ego_spawn_report.json")
    spawn_policy_manual = enforce_spawn_policy(route_mode, manual_spawn_record or {})
    spawn_policy_auto = enforce_spawn_policy(route_mode, auto_spawn_record or {})

    manual_completion = (
        manual_status.get("completion_status")
        if route_mode == MODE_THESIS_PAIRED_STRICT
        else None
    ) or {
        "status": "PASS" if manual_status.get("ok") else "FAIL",
        "per_sensor": [],
        "missing_sensors": [],
    }
    auto_completion = (
        auto_status.get("completion_status")
        if route_mode == MODE_THESIS_PAIRED_STRICT
        else None
    ) or {
        "status": "PASS" if auto_status.get("ok") else "FAIL",
        "per_sensor": [],
        "missing_sensors": [],
    }

    invalid_reasons: List[str] = []
    invalid_reasons += [f"manual:{r}" for r in spawn_policy_manual]
    invalid_reasons += [f"auto:{r}" for r in spawn_policy_auto]

    if manual_source["type"] == "map":
        try:
            manual_ref = resolve_manual_town(manual_source["value"])
            manual_map_identity = cooked_arm_map_identity(
                requested_map_name=str(manual_source["value"]),
                resolved_carla_map_name=str(manual_ref["cooked_town"]),
                registry_identity="ultimate_pipeline.experiments.thesis.manual_refs.MANUAL_INGOLSTADT_REFS",
                manual_source_xodr_sha256=sha256_file(manual_ref["manual_xodr_path"]),
                cooked_package_identity=str(manual_ref["cooked_town"]),
            )
        except Exception as exc:
            manual_map_identity = cooked_arm_map_identity(
                requested_map_name=str(manual_source["value"]),
                resolved_carla_map_name=str(manual_source["value"]),
                registry_identity="",
                manual_source_xodr_sha256="",
                cooked_package_identity=None,
            )
            invalid_reasons.append(f"manual_map_identity_failed:{type(exc).__name__}")
    else:
        manual_map_identity = xodr_arm_map_identity(
            xodr_path=str(manual_source["value"]),
            xodr_sha256=sha256_file(manual_source["value"]),
        )

    auto_map_identity = xodr_arm_map_identity(
        xodr_path=_resolve(str(auto_xodr_path)),
        xodr_sha256=sha256_file(auto_xodr_path),
        final_artifact_authority_sha256=args.auto_artifact_sha256 or None,
    )

    route_validation = None
    if route_manifest is not None and manual_world is not None and auto_world is not None:
        try:
            manual_probe = _CarlaRouteProbeAdapter(manual_world)
            auto_probe = _CarlaRouteProbeAdapter(auto_world)
            manual_route_validation = validate_route_on_map(
                route_manifest, manual_probe, map_name="manual"
            )
            auto_route_validation = validate_route_on_map(
                route_manifest, auto_probe, map_name="auto"
            )
            route_validation = validate_paired_route(
                route_manifest_sha256, manual_route_validation, auto_route_validation
            )
            (pair_root / "route_correspondence.json").write_text(
                json.dumps(route_validation, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            invalid_reasons.append(f"route_probe_failed:{type(exc).__name__}")
    elif route_manifest is None:
        invalid_reasons.append("route_manifest_absent")
    else:
        invalid_reasons.append("route_correspondence_unverified_live_carla_unavailable")

    manual_arm = {
        "calibration_sha256": calib_sha256,
        "sensor_rig_sha256": rig_identity["sensor_rig_sha256"],
        "weather_sha256": manual_weather.get("weather_sha256", ""),
        "sim_timing_sha256": timing["sim_timing_sha256"],
        "capture_config_sha256": capture_config_sha256,
        "route_manifest_sha256": route_manifest_sha256,
        "completion_status": manual_completion.get("status"),
        "frame_counts": dict(manual_status.get("sensor_frame_counts", {})),
        "expected_frames": int(args.frames),
        "pair_frame_index": list(range(int(args.frames))),
    }
    auto_arm = {
        "calibration_sha256": calib_sha256,
        "sensor_rig_sha256": rig_identity["sensor_rig_sha256"],
        "weather_sha256": auto_weather.get("weather_sha256", ""),
        "sim_timing_sha256": timing["sim_timing_sha256"],
        "capture_config_sha256": capture_config_sha256,
        "route_manifest_sha256": route_manifest_sha256,
        "completion_status": auto_completion.get("status"),
        "frame_counts": dict(auto_status.get("sensor_frame_counts", {})),
        "expected_frames": int(args.frames),
        "pair_frame_index": list(range(int(args.frames))),
    }

    if manual_arm["sensor_rig_sha256"] != auto_arm["sensor_rig_sha256"]:
        invalid_reasons.append("sensor_rig_sha256_mismatch_manual_vs_auto")
    if manual_arm["weather_sha256"] != auto_arm["weather_sha256"]:
        invalid_reasons.append("weather_sha256_mismatch_manual_vs_auto")
    if manual_arm["sim_timing_sha256"] != auto_arm["sim_timing_sha256"]:
        invalid_reasons.append("sim_timing_sha256_mismatch_manual_vs_auto")
    if manual_arm["capture_config_sha256"] != auto_arm["capture_config_sha256"]:
        invalid_reasons.append("capture_config_sha256_mismatch_manual_vs_auto")
    if route_manifest_sha256 and manual_arm["route_manifest_sha256"] != auto_arm["route_manifest_sha256"]:
        invalid_reasons.append("route_manifest_mismatch_manual_vs_auto")
    if manual_arm["completion_status"] != COMPLETION_PASS:
        invalid_reasons.append(f"manual_arm_incomplete:{manual_arm['completion_status']}")
    if auto_arm["completion_status"] != COMPLETION_PASS:
        invalid_reasons.append(f"auto_arm_incomplete:{auto_arm['completion_status']}")
    if route_validation is not None and not route_validation.get("valid"):
        invalid_reasons.extend([f"route:{r}" for r in route_validation.get("errors", [])])

    # Canonical route closure.
    pair_route_closure = (
        "PAIR_ROUTE_VALID"
        if (route_validation or {}).get("valid")
        else ("PAIR_ROUTE_INVALID" if route_validation is not None else "ROUTE_UNSUPPLIED")
    )

    is_pair = bool(route_manifest is not None and route_manifest_sha256)
    pair_valid = bool(not invalid_reasons and is_pair)
    if not is_pair:
        invalid_reasons.append("not_a_paired_route_claim")
    if manual_error or auto_error:
        invalid_reasons.append("arm_exception")

    both_ingolstadt = is_ingolstadt_manual_arm(manual_map_identity) and is_ingolstadt_auto_arm(
        auto_map_identity, ingolstadt_xodr_sha256=args.auto_ingolstadt_xodr_sha256 or None
    )
    claim_data = classify_claim_level(
        is_pair=is_pair,
        pair_valid=bool(
            pair_valid
            and ((route_validation or {}).get("valid") if route_validation is not None else True)
        ),
        route_valid=bool(
            (route_validation or {}).get("valid", bool(route_manifest_sha256))
            if route_validation is not None
            else bool(route_manifest_sha256)
        ),
        both_arms_ingolstadt=both_ingolstadt,
    )
    claim_level = claim_data["claim_level"]
    invalid_reasons_ids = list(claim_data["reasons"])

    git_sha = git_sha_of_repo()
    client_version = carla_client_version(client) if client is not None else "unavailable"
    server_version = carla_server_version(client) if client is not None else "unavailable"
    pair_id = f"rq3-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"

    pair_manifest_governed = build_pair_manifest(
        pair_id=pair_id,
        software_git_sha=git_sha,
        carla_client_version=client_version,
        carla_server_version=server_version,
        manual_map_identity=manual_map_identity,
        auto_map_identity=auto_map_identity,
        route_manifest_path=_resolve(args.route_manifest) if args.route_manifest else "",
        route_manifest_sha256=route_manifest_sha256,
        calibration_sha256=calib_sha256,
        sensor_rig_sha256=rig_identity["sensor_rig_sha256"],
        weather_sha256=manual_arm["weather_sha256"],
        capture_config_sha256=capture_config_sha256,
        manual_arm=manual_arm,
        auto_arm=auto_arm,
        pair_valid=pair_valid,
        invalid_reasons=invalid_reasons + invalid_reasons_ids,
        claim_level=claim_level,
        route_mode=route_mode,
        pair_route_closure=pair_route_closure,
    )
    validation_result = validate_pair_manifest(pair_manifest_governed)
    pair_manifest_governed["_validation"] = validation_result
    (pair_root / "paired_capture_manifest.json").write_text(
        json.dumps(pair_manifest_governed, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    pair_manifest = {
        "ok": bool(ok) and bool(manual_status.get("ok", ok)) and bool(auto_status.get("ok", ok)),
        "error": error,
        "pair_valid": bool(pair_valid),
        "claim_level": claim_level,
        "invalid_reasons": pair_manifest_governed.get("invalid_reasons"),
        "frames": int(args.frames),
        "fps": int(args.fps),
        "route_mode": route_mode,
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

    return 0 if (ok and manual_status.get("ok", ok) and auto_status.get("ok", ok) and pair_valid) else 1


if __name__ == "__main__":
    sys.exit(main())
