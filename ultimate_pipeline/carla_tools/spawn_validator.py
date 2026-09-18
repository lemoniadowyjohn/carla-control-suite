#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SpawnValidator — CARLA world readiness validator.

Checks:
  • client is a carla.Client
  • world + map are responsive
  • spawn points appear after stabilization
"""

from __future__ import annotations
import time


class SpawnValidator:
    @staticmethod
    def _wait_for_spawn_points(world, timeout: float = 90.0, poll: float = 1.0):
        start = time.time()
        last_print = 0.0

        while time.time() - start < timeout:
            try:
                carla_map = world.get_map()
                spawn_points = carla_map.get_spawn_points()
                if spawn_points:
                    return spawn_points
            except Exception:
                # World/map not fully ready yet
                spawn_points = []

            now = time.time()
            if now - last_print > 5.0:
                print("[SpawnValidator] Waiting for spawn points…")
                last_print = now

            time.sleep(poll)

        return []

    @staticmethod
    def check(client) -> bool:
        # HARD GUARD — fail fast
        if not hasattr(client, "get_world"):
            raise TypeError(
                "SpawnValidator.check() expects a carla.Client, "
                f"got {type(client)}"
            )

        try:
            print("[SpawnValidator] Checking spawn points…")

            world = client.get_world()  # if this fails, CARLA is not stable
            spawns = SpawnValidator._wait_for_spawn_points(world, timeout=120.0)

            if not spawns:
                print("❌ No spawn points after stabilization — map likely NOT drivable.")
                return False

            print(f"✓ SpawnValidator: {len(spawns)} spawn points detected.")
            return True

        except Exception as e:
            print(f"❌ SpawnValidator failed: {e}")
            return False
