#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Simple CARLA session sanity check.
Run it when you suspect CARLA is stuck or unstable.
"""

import argparse
import carla


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CARLA session sanity check.")
    parser.add_argument("--host", default="localhost", help="CARLA host (default: localhost)")
    parser.add_argument("--port", type=int, default=2000, help="CARLA port (default: 2000)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Client timeout seconds (default: 10)")
    parser.add_argument("--ticks", type=int, default=10, help="Number of ticks (default: 10)")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    client = carla.Client(args.host, int(args.port))
    client.set_timeout(float(args.timeout))

    world = client.get_world()
    carla_map = world.get_map()

    print("Connected to CARLA.")
    print(f"Map name: {carla_map.name}")
    print(f"Ticking world {int(args.ticks)} times...")

    for i in range(int(args.ticks)):
        world.tick()
        print(f"Tick {i + 1}/{int(args.ticks)} OK")

    print("CARLA session stable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
