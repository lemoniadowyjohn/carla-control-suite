#!/usr/bin/env python3
# ultimate_pipeline/carla_tools/carla_final_test.py

import time
from typing import Dict, Any, Optional

import carla
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

class CarlaFinalTest:
    """
    Final CARLA validation stage for the ultimate pipeline.

    Checks:
        - XODR loads without crash
        - Waypoints can be generated
        - A vehicle can be spawned (optional)
        - Spectator is moved over the tile for visual inspection
    """

    @staticmethod
    def run(
        xodr_path: str,
        host: str = "localhost",
        port: int = 2000,
        timeout: float = 60.0,
        timeout_s: Optional[float] = None,
        retries: int = 0,
        spawn_vehicle: bool = True,
        do_reload: bool = True,
        auto_fix_s: bool = True,
        client: Optional[carla.Client] = None,
    ) -> Dict[str, Any]:
        print("\n🚦 Running final CARLA validation...")
        report: Dict[str, Any] = {
            "map_loaded": False,
            "waypoints": 0,
            "vehicle_spawned": False,
            "spawn_reason": None,
        }

        # ---------------- Ensure CARLA is up, then connect ----------------
        try:
            from ultimate_pipeline.core.carla_utils import autostart_carla_if_needed
            autostart_carla_if_needed()

            eff_timeout = float(timeout_s if timeout_s is not None else timeout)

            if client is None:
                client = carla.Client(host, port)
            client.set_timeout(eff_timeout)

        except Exception as e:
            print(f"❌ CARLA connection / pre-reset failed: {e}")
            report["spawn_reason"] = "carla_connection_failed"
            return report

        # ---------------- Load XODR ----------------
        try:
            with open(xodr_path, encoding="utf-8") as f:
                data = f.read()

            # QA-only preflight: reduce known CARLA importer crash patterns.
            if auto_fix_s:
                try:
                    import xml.etree.ElementTree as ET
                    from ultimate_pipeline.quality.check_carla_import_s import CarlaImportSChecker

                    root = ET.fromstring(data)
                    issues = CarlaImportSChecker.validate(root)
                    if issues:
                        fixes, after = CarlaImportSChecker.auto_fix_in_place(root)
                        data = ET.tostring(root, encoding="unicode")
                        print(
                            f"⚠ CARLA import s-preflight: issues_before={len(issues)} fixes={fixes} issues_after={len(after)}"
                        )
                except Exception:
                    pass

            params = carla.OpendriveGenerationParameters()
            params.map_layers = carla.MapLayer.NONE  # stable for CARLA 0.9.16

            world = load_opendrive_world(
                client,
                data,
                params=params,
                timeout_s=float(timeout_s if timeout_s is not None else 180.0),
                retries=int(retries),
                do_reload=bool(do_reload),
                # QA must not silently switch to a built-in map.
                fallback_enabled=False,
            )
            time.sleep(0.5)
            report["map_loaded"] = True
            print("✓ Map loaded successfully!")

        except Exception as e:
            print(f"❌ Map failed to load: {e}")
            report["spawn_reason"] = "map_load_failed"
            return report

        # ---------------- Move spectator to tile center ----------------
        try:
            world = client.get_world()
            amap = world.get_map()
            waypoints = amap.generate_waypoints(5.0)

            if waypoints:
                xs = [wp.transform.location.x for wp in waypoints]
                ys = [wp.transform.location.y for wp in waypoints]
                zs = [wp.transform.location.z for wp in waypoints]

                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                cz = sum(zs) / len(zs)

                spectator = world.get_spectator()

                # Oblique view slightly “behind” and above the center
                cam_loc = carla.Location(
                    x=cx,
                    y=cy - 80.0,
                    z=cz + 60.0,
                )
                cam_rot = carla.Rotation(
                    pitch=-35.0,  # look downward
                    yaw=0.0,
                    roll=0.0,
                )

                spectator.set_transform(carla.Transform(cam_loc, cam_rot))
                print(f"👁 Spectator moved to tile center: ({cx:.1f}, {cy:.1f}, {cz:.1f})")

                # Extra visibility: lift camera if tile is too flat or too small
                try:
                    if len(waypoints) < 20:
                        # Tiny tile → move camera higher
                        top_cam = carla.Location(x=cx, y=cy, z=cz + 120.0)
                        spectator.set_transform(
                            carla.Transform(top_cam, carla.Rotation(pitch=-90.0))
                        )
                        print("📸 Auto-adjusted to top-down view for small tile.")
                except Exception as e2:
                    print(f"⚠ Camera auto-adjust failed: {e2}")

                # Optional: top-down “inspection” view (briefly toggle)
                # Uncomment this block if you prefer pure top-down:
                #
                # top_cam_loc = carla.Location(x=cx, y=cy, z=cz + 150.0)
                # spectator.set_transform(
                #     carla.Transform(top_cam_loc, carla.Rotation(pitch=-90.0))
                # )
                # print("📸 Top-down camera applied for tile inspection.")

        except Exception as e:
            print(f"⚠ Could not reposition camera: {e}")

        # ---------------- Waypoint Test ----------------
        try:
            amap = world.get_map()
            waypoints_2m = amap.generate_waypoints(2.0)
            report["waypoints"] = len(waypoints_2m)

            if len(waypoints_2m) == 0:
                print("❌ No waypoints found — topology broken.")
                report["spawn_reason"] = "no_waypoints"
                # still return; no need to try spawns
                return report
            else:
                print(f"✓ {len(waypoints_2m)} waypoints generated.")

        except Exception as e:
            print(f"❌ Failed to generate waypoints: {e}")
            report["waypoints"] = 0
            report["spawn_reason"] = "waypoint_generation_failed"
            return report

        # ---------------- Vehicle Spawn Test (robust) ----------------
        if not spawn_vehicle:
            report["vehicle_spawned"] = False
            report["spawn_reason"] = "spawn_skipped"
            return report

        try:
            bp_lib = world.get_blueprint_library()
            veh_bp = bp_lib.find("vehicle.audi.tt")

            spawn_points = list(amap.get_spawn_points())

            # Fallback: use waypoints as spawn origins if spawn_points empty
            if not spawn_points:
                print("⚠ No spawn points; falling back to waypoints for spawn origins.")
                wps = amap.generate_waypoints(5.0)
                for wp in wps[:20]:
                    spawn_points.append(wp.transform)

            if not spawn_points:
                print("❌ No valid spawn candidates in this tile.")
                report["spawn_reason"] = "no_spawn_candidates"
                return report

            vehicle = None
            last_error: Optional[str] = None

            # Try multiple spawn locations with z adjustments
            for idx, sp in enumerate(spawn_points[:20]):
                try:
                    # 1) Try as-is
                    vehicle = world.try_spawn_actor(veh_bp, sp)
                    if vehicle is not None:
                        print(f"✓ Vehicle spawned (candidate {idx}, id={vehicle.id})")
                        break

                    # 2) Try with small vertical offsets
                    for dz in (1.0, 2.5, 4.0):
                        sp2 = carla.Transform(
                            location=carla.Location(
                                x=sp.location.x,
                                y=sp.location.y,
                                z=sp.location.z + dz,
                            ),
                            rotation=sp.rotation,
                        )
                        vehicle = world.try_spawn_actor(veh_bp, sp2)
                        if vehicle is not None:
                            print(
                                f"✓ Vehicle spawned after dz={dz} "
                                f"(candidate {idx}, id={vehicle.id})"
                            )
                            break

                    if vehicle is not None:
                        break

                except Exception as e:
                    last_error = str(e)
                    continue

            if vehicle is None:
                print("❌ Vehicle spawn failed across all candidates.")
                report["vehicle_spawned"] = False
                report["spawn_reason"] = last_error or "all_spawn_attempts_failed"
                return report

            # Minimal sanity drive (optional; keep short)
            try:
                control = carla.VehicleControl(throttle=0.3)
                vehicle.apply_control(control)
                world.tick()
            except Exception:
                pass

            report["vehicle_spawned"] = True
            report["spawn_reason"] = "ok"
            print(f"✓ Vehicle spawned successfully (id={vehicle.id})")

        except Exception as e:
            print(f"❌ Vehicle spawn error: {e}")
            report["vehicle_spawned"] = False
            report["spawn_reason"] = str(e)
        finally:
            # Clean up vehicle
            try:
                if "vehicle" in locals() and vehicle is not None:
                    vehicle.destroy()
            except Exception:
                pass

        return report


def _cli() -> None:
    import argparse
    import json

    from ultimate_pipeline.utils.timestamped_print import enable_timestamped_print
    enable_timestamped_print()

    ap = argparse.ArgumentParser(description="Run CARLA OpenDRIVE load/spawn validation")
    ap.add_argument("--xodr", required=True, help="Path to .xodr")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout_s", type=float, default=180.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--no_spawn", action="store_true", help="Skip vehicle spawn test")
    ap.add_argument("--no_reload", action="store_true", help="Do not reload base world before generation")
    ap.add_argument("--no_fix_s", action="store_true", help="Disable s-preflight auto-fix")
    ap.add_argument("--json_out", default=None, help="Write report JSON to this path")
    args = ap.parse_args()
    from pathlib import Path
    import time

    tile_path = Path(args.xodr).resolve()
    tile_name = tile_path.stem

    report_path = Path(args.json_out).resolve() if getattr(args, "json_out", None) else None
    if report_path is None:
        try:
            # Expected: .../<run>/tiles/<tile>.xodr
            if tile_path.parent.name.lower() == "tiles":
                pipeline_out = tile_path.parent.parent
            else:
                pipeline_out = tile_path.parent
            report_dir = pipeline_out / "logs" / "tile_reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / f"tile_report_{tile_name}.json"
        except Exception:
            report_path = tile_path.with_suffix(".tile_report.json")

    # Pre-write a marker so even a native crash leaves an artifact on disk.
    pre = {
        "tile": tile_name,
        "tile_path": str(tile_path),
        "status": "started",
        "ts_start": time.time(),
        "host": args.host,
        "port": args.port,
        "timeout_s": args.timeout_s,
        "retries": args.retries,
    }
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(pre, indent=2), encoding="utf-8")
    except Exception:
        pass


    rep = CarlaFinalTest.run(
        args.xodr,
        host=args.host,
        port=args.port,
        timeout_s=args.timeout_s,
        retries=args.retries,
        spawn_vehicle=(not args.no_spawn),
        do_reload=(not args.no_reload),
        auto_fix_s=(not args.no_fix_s),
    )

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
    else:
        print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    _cli()
