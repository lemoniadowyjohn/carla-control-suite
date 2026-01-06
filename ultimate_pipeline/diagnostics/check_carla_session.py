#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Simple CARLA session sanity check.
Run it when you suspect CARLA is stuck or unstable.
"""

import carla


def main():
    client = carla.Client("localhost", 2000)
    client.set_timeout(10.0)

    world = client.get_world()
    carla_map = world.get_map()

    print("✅ Connected to CARLA.")
    print(f"   Map name: {carla_map.name}")
    print("   Ticking world 10 times…")

    for i in range(10):
        world.tick()
        print(f"   Tick {i + 1}/10 OK")

    print("🎉 CARLA session stable.")


if __name__ == "__main__":
    main()
