import argparse
import os
import traceback
from pathlib import Path

import carla

#: NEW-259: the phase receipt path. Overridable so a caller can direct it into a
#: crash bundle rather than the process CWD.
_RECEIPT_ENV = "UP_DIAGNOSTIC_PROBE_RECEIPT"


def _phase_receipt_path():
    raw = os.environ.get(_RECEIPT_ENV, "").strip()
    if raw:
        return Path(raw)
    return Path.cwd() / "diagnostic_probe_phases.json"


def run_probe(
    host: str,
    port: int,
    ticks: int,
    tick_timeout_s: float,
    *,
    use_current_world: bool = False,
    builtin_map_test: bool = False,
) -> int:
    c = carla.Client(host, int(port))
    c.set_timeout(10)

    # Phase 1: confirm world is loaded
    world = c.get_world()
    map_name = str(world.get_map().name)
    spawn_count = len(world.get_map().get_spawn_points())
    print(f"[1] Map: {map_name}")
    print(f"[1] Spawn points: {spawn_count}")
    if use_current_world:
        print("[1] use_current_world=true")
    if builtin_map_test:
        map_name_norm = map_name.replace("\\", "/").lower()
        expected_ok = ("town10hd_opt" in map_name_norm) or ("town10" in map_name_norm)
        print(
            f"[1] builtin_map_test expected=Town10HD_Opt actual={map_name} "
            f"match={str(bool(expected_ok)).lower()}"
        )

    # Phase 2: spawn ego
    bp = world.get_blueprint_library().find("vehicle.tesla.model3")
    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        raise RuntimeError("no_spawn_points")
    sp = spawn_points[0]
    ego = world.try_spawn_actor(bp, sp)
    print(f"[2] Ego spawned: {ego}  id={ego.id if ego else None}")

    if not ego:
        print("[5] RESULT: FAIL_EGO_SPAWN")
        return 2

    cam = None
    frames = []
    settings = world.get_settings()
    original_settings = world.get_settings()

    # NEW-259: the phase receipt is written BEFORE any teardown. If cleanup is what
    # crashes the engine -- which it can be, via ASensor::EndPlay -- the receipt on
    # disk still says which phase actually succeeded, so the diagnosis is
    # unambiguous instead of "everything failed".
    phase_receipt: dict = {
        "schema": "diagnostic_probe_phases_v1",
        "map_name": map_name,
        "spawn_count": spawn_count,
        "phases": {
            "world": "PASS",
            "ego": "PASS" if ego else "FAIL",
            "camera": "PENDING",
            "ticks": "PENDING",
            "frames": "PENDING",
        },
        "frames_captured": 0,
        "tick_count": 0,
        "teardown": "NOT_STARTED",
        "teardown_errors": [],
    }
    receipt_path = _phase_receipt_path()

    def _persist() -> None:
        if receipt_path is None:
            return
        try:
            import json

            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic replace so a crash mid-write cannot leave a truncated receipt.
            tmp = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
            tmp.write_text(json.dumps(phase_receipt, indent=2), encoding="utf-8")
            tmp.replace(receipt_path)
        except Exception:
            pass

    _persist()

    try:
        # Phase 3: attach RGB camera
        cam_bp = world.get_blueprint_library().find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", "800")
        cam_bp.set_attribute("image_size_y", "600")
        cam_bp.set_attribute("fov", "90")
        cam_transform = carla.Transform(carla.Location(x=1.5, z=2.4))
        cam = world.spawn_actor(cam_bp, cam_transform, attach_to=ego)
        phase_receipt["phases"]["camera"] = "PASS" if cam else "FAIL"
        _persist()
        print(f"[3] Camera spawned: {cam}  id={cam.id if cam else None}")

        def on_frame(img):
            frames.append(img.frame)

        cam.listen(on_frame)

        # Phase 4: tick world
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        world.apply_settings(settings)
        print("[4] Sync mode ON")

        tick_failure = None
        for i in range(int(ticks)):
            try:
                world.tick(float(tick_timeout_s))
                phase_receipt["tick_count"] = i + 1
                phase_receipt["frames_captured"] = len(frames)
                _persist()
                print(f"[4] Tick {i + 1}: frames_captured={len(frames)}")
            except Exception as e:
                tick_failure = f"{type(e).__name__}: {e}"
                print(f"[4] Tick {i + 1} FAILED: {e}")
                traceback.print_exc()
                break

        phase_receipt["phases"]["ticks"] = "FAIL" if tick_failure else "PASS"
        phase_receipt["phases"]["frames"] = "PASS" if frames else "FAIL"
        phase_receipt["frames_captured"] = len(frames)
        phase_receipt["tick_error"] = tick_failure
    finally:
        # NEW-259: the outcome is now durably recorded BEFORE teardown begins, so a
        # crash during cleanup cannot erase the fact that the map, ego, camera and
        # ticks all succeeded.
        _persist()
        # Phase 5: cleanup.
        #
        # NEW-259: NO individual actor teardown. On the exact maps where
        # ASensor::EndPlay is unstable, destroying the camera or the ego one at a
        # time can crash the engine, which makes the diagnosis ambiguous: did the
        # map fail, the sensor fail, or only the cleanup? The listener is stopped
        # (safe, it does not destroy the actor) and the session is left for the
        # process to discard.
        try:
            original_settings.synchronous_mode = False
            original_settings.fixed_delta_seconds = None
            world.apply_settings(original_settings)
        except Exception as exc:
            phase_receipt["teardown_errors"].append(f"apply_settings: {exc}")
        try:
            if cam is not None:
                cam.stop()
        except Exception as exc:
            phase_receipt["teardown_errors"].append(f"cam.stop: {exc}")
        phase_receipt["teardown"] = "NON_DESTRUCTIVE"
        phase_receipt["teardown_policy"] = "actors_left_for_process_teardown"
        _persist()

    print(f"[5] CLEANUP (non-destructive). Total frames: {len(frames)}")
    print(
        f"[5] RESULT: {'PASS' if len(frames) > 0 else 'FAIL_NO_FRAMES'}"
        f" (receipt={receipt_path})"
    )
    return 0 if len(frames) > 0 else 3


def main() -> int:
    ap = argparse.ArgumentParser(description="Minimal CARLA sensor/tick diagnostic probe")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--ticks", type=int, default=10)
    ap.add_argument("--tick-timeout-s", type=float, default=2.0)
    ap.add_argument(
        "--use-current-world",
        action="store_true",
        help="Keep current loaded world (explicit flag for parity with other tools).",
    )
    ap.add_argument(
        "--builtin-map-test",
        action="store_true",
        help="Annotate output for built-in Town10HD_Opt probe diagnostics.",
    )
    args = ap.parse_args()
    return run_probe(
        args.host,
        args.port,
        args.ticks,
        args.tick_timeout_s,
        use_current_world=bool(args.use_current_world),
        builtin_map_test=bool(args.builtin_map_test),
    )


if __name__ == "__main__":
    raise SystemExit(main())
