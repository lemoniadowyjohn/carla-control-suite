#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSM2World Smoke Test

Quick standalone test of OSM2World integration without running the full pipeline.
Useful for validating Java/OSM2World installation and generating test artifacts.

Usage:
    python -m ultimate_pipeline.tools.smoke_osm2world --osm file.osm --out ./output
    python -m ultimate_pipeline.tools.smoke_osm2world --osm file.osm --out ./output --strict

Exit codes:
    0: Success or skipped (unless --strict)
    1: Failure (always) or skipped (with --strict)

Environment Variables:
    OSM2WORLD_HOME: Path to OSM2World binary folder
    OSM2WORLD_TIMEOUT: Timeout in seconds (default: 300)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OSM2World smoke test - generate 3D scene artifacts from OSM"
    )
    parser.add_argument(
        "--osm",
        required=True,
        help="Path to input OSM file (.osm, .osm.xml, or .pbf)",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output directory for artifacts",
    )
    parser.add_argument(
        "--home",
        help="OSM2World home directory (default: uses OSM2WORLD_HOME env or built-in default)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 on skip (not just on failure)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    args = parser.parse_args()

    # Validate input
    osm_path = Path(args.osm)
    if not osm_path.exists():
        print(f"Error: OSM file not found: {osm_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)

    # Import runner (do this after arg parsing for faster --help)
    try:
        from ultimate_pipeline.enrichment.osm2world_runner import OSM2WorldRunner
    except ImportError as e:
        print(f"Error: Could not import OSM2WorldRunner: {e}", file=sys.stderr)
        print("Make sure you're running from the repository root.", file=sys.stderr)
        return 1

    # Run
    print(f"OSM2World Smoke Test")
    print(f"  Input: {osm_path}")
    print(f"  Output: {out_dir}")
    if args.home:
        print(f"  Home: {args.home}")
    print()

    runner = OSM2WorldRunner(
        osm_path=str(osm_path),
        output_dir=str(out_dir),
        osm2world_home=args.home,
        timeout_sec=args.timeout,
    )
    result = runner.run()

    # Output
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_result(result)

    # Exit code logic
    if result.status == "ok":
        return 0
    elif result.status == "skipped":
        return 1 if args.strict else 0
    else:  # failed
        return 1


def _print_result(result) -> None:
    """Print human-readable result summary."""
    status_icons = {"ok": "[OK]", "skipped": "[SKIP]", "failed": "[FAIL]"}
    icon = status_icons.get(result.status, "[?]")

    print(f"Result: {icon} {result.status}")
    print(f"Reason: {result.reason}")
    print(f"Duration: {result.duration_sec:.1f}s")
    print()

    if result.java_version:
        print(f"Java: {result.java_version}")

    if result.osm2world_version:
        print(f"OSM2World: {result.osm2world_version}")

    if result.command_line:
        print(f"Command: {' '.join(result.command_line)}")

    if result.outputs:
        print("\nOutputs generated:")
        for name, path in result.outputs.items():
            hash_val = result.hashes.get(name, "")[:16]
            print(f"  {name}: {path}")
            if hash_val:
                print(f"    SHA256: {hash_val}...")

    if result.hashes.get("input_osm"):
        print(f"\nInput hash: {result.hashes['input_osm'][:16]}...")

    if result.exit_code is not None and result.exit_code != 0:
        print(f"\nExit code: {result.exit_code}")

    if result.exception:
        print(f"\nException: {result.exception}")

    if result.stderr and result.status == "failed":
        print(f"\nStderr (truncated):\n{result.stderr[:500]}")


if __name__ == "__main__":
    sys.exit(main())
