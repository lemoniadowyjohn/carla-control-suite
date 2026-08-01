import argparse
import traceback

import carla


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

    try:
        # Phase 3: attach RGB camera
        cam_bp = world.get_blueprint_library().find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", "800")
        cam_bp.set_attribute("image_size_y", "600")
        cam_bp.set_attribute("fov", "90")
        cam_transform = carla.Transform(carla.Location(x=1.5, z=2.4))
        cam = world.spawn_actor(cam_bp, cam_transform, attach_to=ego)
        print(f"[3] Camera spawned: {cam}  id={cam.id if cam else None}")

        def on_frame(img):
            frames.append(img.frame)

        cam.listen(on_frame)

        # Phase 4: tick world
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        world.apply_settings(settings)
        print("[4] Sync mode ON")

        for i in range(int(ticks)):
            try:
                world.tick(float(tick_timeout_s))
                print(f"[4] Tick {i + 1}: frames_captured={len(frames)}")
            except Exception as e:
                print(f"[4] Tick {i + 1} FAILED: {e}")
                traceback.print_exc()
                break
    finally:
        # Phase 5: cleanup
        try:
            original_settings.synchronous_mode = False
            original_settings.fixed_delta_seconds = None
            world.apply_settings(original_settings)
        except Exception:
            pass
        try:
            if cam is not None:
                cam.stop()
        except Exception:
            pass
        try:
            if cam is not None:
                cam.destroy()
        except Exception:
            pass
        try:
            ego.destroy()
        except Exception:
            pass

    print(f"[5] CLEANUP OK. Total frames: {len(frames)}")
    print(f"[5] RESULT: {'PASS' if len(frames) > 0 else 'FAIL_NO_FRAMES'}")
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
