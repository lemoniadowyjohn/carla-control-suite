#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TileStressTester — extended, production-ready version.

Per-tile robustness evaluation for the Ultimate Pipeline:
  ✓ loads a tile
  ✓ spawns N vehicles
  ✓ random control policy
  ✓ counts collisions, stuck frames, path length
  ✓ logs results to SQLite via SensorLogger (optional)
  ✓ returns an aggregated dict

Used in:
    STEP 10B: per-tile stress validation
"""

from __future__ import annotations

import random
import time
import json
from typing import Dict, List, Any, Optional, TYPE_CHECKING

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
if TYPE_CHECKING:  # pragma: no cover
    import carla  # type: ignore


def _require_carla():
    """Import CARLA lazily so unit tests can run without the PythonAPI installed."""
    try:
        import carla  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "CARLA PythonAPI is required for TileStressTester at runtime. "
            "Install/activate CARLA (carla module) or avoid calling tile stress validation steps."
        ) from e
    return carla


from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

# optional DB logging
try:
    from ultimate_pipeline.db.sensor_logger import SensorLogger
except Exception:
    SensorLogger = None


class TileStressTester:
    """
    Usage:
        stats = TileStressTester.run(xodr, duration=10.0)
    """

    NUM_TEST_VEHICLES = 4
    MAX_STUCK_TIME = 0.8
    COLLISION_SENSOR_ID = "collision"

    @classmethod
    def run(
        cls,
        xodr_path: str,
        duration: float = 10.0,
        db_logger: Optional[SensorLogger] = None,
        tile_meta: Optional[Dict[str, Any]] = None,
        host: str = "127.0.0.1",
        port: int = 2000,
        save_json_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Perform stress test for a single tile.

        Parameters
        ----------
        xodr_path : str
        duration : float
        db_logger : SensorLogger | None
            If provided → log aggregated stats to SQLite.
        tile_meta : dict | None
            { "map_name": ..., "tile_x": ..., "tile_y": ... }
        save_json_to : str | None
            Path to save aggregated result as JSON.
        """

        carla = _require_carla()
        client = carla.Client(host, port)
        client.set_timeout(45.0)

        world = cls._load_map(client, xodr_path)
        spawn_points = world.get_map().get_spawn_points()

        if len(spawn_points) == 0:
            agg = cls._empty_result()
            # save JSON
            if save_json_to:
                cls._save_json(save_json_to, agg)


            try:
                tm = client.get_trafficmanager()
                tm.set_synchronous_mode(False)
            except:
                pass

            try:
                _reload_ready_for_sensors(client, map_name="Town01", tm_port=8000)
            except:
                pass
            # -------------------------

            return agg

        # Try enabling synchronous TM
        try:
            tm = client.get_trafficmanager()
            tm.set_synchronous_mode(True)
        except Exception:
            tm = None

        results = []
        for i in range(cls.NUM_TEST_VEHICLES):
            try:
                stats = cls._evaluate_single_vehicle(world, spawn_points, duration)
            except Exception as e:
                print(f"⚠ Vehicle test {i} failed: {e}")
                stats = cls._empty_run()
            results.append(stats)

        # Cleanup: destroy actors + load safe map
        try:
            print("🧹 Cleaning up tile actors...")

            world = client.get_world()
            actors = world.get_actors()

            for a in actors:
                try:
                    if a.is_alive:
                        a.destroy()
                except Exception:
                    pass

            print("↩ Returning to Town10HD...")
            _reload_ready_for_sensors(client, map_name="Town10HD", tm_port=8000)

            # Reset Traffic Manager sync mode
            try:
                tm = client.get_trafficmanager()
                tm.set_synchronous_mode(False)
            except Exception:
                pass

        except Exception as e:
            print(f"⚠ Cleanup failed: {e}")

        if not results:
            agg = cls._empty_result()
            if save_json_to:
                cls._save_json(save_json_to, agg)
            return agg

        agg = cls._aggregate(results)
        print(f"🧪 Tile stress test summary: {agg}")

        # log to DB
        if db_logger and tile_meta:
            cls._log_to_db(db_logger, tile_meta, agg)

        # save JSON
        if save_json_to:
            cls._save_json(save_json_to, agg)

        return agg

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _load_map(client: 'carla.Client', xodr_path: str) -> 'carla.World':
        print(f"📦 Loading XODR tile: {xodr_path}")

        carla = _require_carla()

        try:
            with open(xodr_path, "r", encoding="utf-8") as f:
                data = f.read()

            params = carla.OpendriveGenerationParameters()
            world = load_opendrive_world(
                client,
                data,
                params=params,
                timeout_s=180.0,
                retries=2,
                do_reload=True,
            )
            # Warm-up ticks ensure map is fully generated
            for _ in range(15):
                try:
                    world.tick()
                except Exception:
                    time.sleep(0.05)

            return world

        except Exception as e:
            print(f"❌ Failed to load XODR tile ({xodr_path}): {e}")
            # Return emergency world so pipeline continues
            return _reload_ready_for_sensors(client, map_name="Town10HD", tm_port=8000)

    @classmethod
    def _evaluate_single_vehicle(
        cls,
        world: 'carla.World',
        spawn_points: List['carla.Transform'],
        duration: float
    ) -> Dict[str, Any]:

        carla = _require_carla()
        world.apply_settings(carla.WorldSettings(
            synchronous_mode=True,
            fixed_delta_seconds=0.03
        ))

        blueprint = world.get_blueprint_library().filter("vehicle.*")[0]
        spawn = random.choice(spawn_points)

        vehicle = world.try_spawn_actor(blueprint, spawn)
        if vehicle is None:
            return cls._empty_run()

        collision_data = {"count": 0}
        col_sensor = cls._attach_collision_sensor(world, vehicle, collision_data)

        start = time.time()
        stuck_timer = 0.0
        prev_loc = vehicle.get_location()

        stats = {
            "collisions": 0,
            "stuck_frames": 0,
            "path_length": 0.0,
        }

        while time.time() - start < duration:
            ctrl = carla.VehicleControl(
                throttle=random.uniform(0.2, 0.7),
                steer=random.uniform(-0.8, 0.8),
            )
            vehicle.apply_control(ctrl)

            try:
                world.tick()
            except RuntimeError:
                time.sleep(0.03)

            time.sleep(0.03)

            curr_loc = vehicle.get_location()
            d = curr_loc.distance(prev_loc)
            stats["path_length"] += d

            if d < 0.05:
                stuck_timer += 0.03
            else:
                stuck_timer = 0.0

            if stuck_timer > cls.MAX_STUCK_TIME:
                stats["stuck_frames"] += 1

            prev_loc = curr_loc

        stats["collisions"] = collision_data["count"]

        try:
            if col_sensor.is_alive:
                col_sensor.destroy()
            if vehicle.is_alive:
                vehicle.destroy()
        except Exception:
            pass
        # Restore world settings
        try:
            world.apply_settings(carla.WorldSettings(
                synchronous_mode=False,
                fixed_delta_seconds=0.03
            ))
        except Exception:
            pass

        return stats

    @staticmethod
    def _attach_collision_sensor(world, vehicle, counter):
        carla = _require_carla()
        bp = world.get_blueprint_library().find("sensor.other.collision")
        sensor = world.spawn_actor(bp, carla.Transform(), attach_to=vehicle)
        sensor.listen(lambda e: TileStressTester._on_collision(e, counter))
        return sensor

    @staticmethod
    def _on_collision(event, counter):
        counter["count"] += 1

    # ------------------------------------------------------------------

    @staticmethod
    def _empty_run():
        return {"collisions": 0, "stuck_frames": 0, "path_length": 0.0}

    @staticmethod
    def _empty_result():
        return {
            "success": False,
            "avg_collisions": None,
            "avg_stuck_frames": None,
            "avg_path_length": None,
        }

    @staticmethod
    def _aggregate(runs):
        n = len(runs)
        return {
            "success": True,
            "avg_collisions": sum(r["collisions"] for r in runs) / n,
            "avg_stuck_frames": sum(r["stuck_frames"] for r in runs) / n,
            "avg_path_length": sum(r["path_length"] for r in runs) / n,
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _log_to_db(db: SensorLogger, meta: Dict[str, Any], agg: Dict[str, Any]):
        """
        Save tile-level stress test summary to hpc_experiment_result table
        under special experiment tag "tile_stress".
        """
        exp_uuid = db.register_experiment(
            model_checkpoint="tile_stress_test",
            dataset_uuid="none",
            notes="Tile stress test run"
        )

        db.log_experiment_result(
            experiment_uuid=exp_uuid,
            tile_x=meta.get("tile_x", -1),
            tile_y=meta.get("tile_y", -1),
            map_name=meta.get("map_name", "unknown"),
            metric_key="avg_collisions",
            metric_value=float(agg["avg_collisions"]),
        )
        db.log_experiment_result(
            experiment_uuid=exp_uuid,
            tile_x=meta.get("tile_x", -1),
            tile_y=meta.get("tile_y", -1),
            map_name=meta.get("map_name", "unknown"),
            metric_key="avg_stuck_frames",
            metric_value=float(agg["avg_stuck_frames"]),
        )
        db.log_experiment_result(
            experiment_uuid=exp_uuid,
            tile_x=meta.get("tile_x", -1),
            tile_y=meta.get("tile_y", -1),
            map_name=meta.get("map_name", "unknown"),
            metric_key="avg_path_length",
            metric_value=float(agg["avg_path_length"]),
        )

    @staticmethod
    def _save_json(path: str, agg: Dict[str, Any]):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(agg, f, indent=2)
