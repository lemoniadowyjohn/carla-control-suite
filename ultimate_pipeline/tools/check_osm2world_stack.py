#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSM2World + Blender Stack Sanity Check

Runs the full chain:
  1. Java version check
  2. OSM2World export (OBJ + PNG)
  3. Optional Blender OBJ → FBX conversion

Exits 0 on success, nonzero on failure.
Prints a compact summary and points to logs/artifacts.

Usage:
    python -m ultimate_pipeline.tools.check_osm2world_stack --osm path/to/file.osm --out ./test_out

    # With Blender FBX conversion:
    python -m ultimate_pipeline.tools.check_osm2world_stack --osm path/to/file.osm --out ./test_out --blender

    # With custom timeouts:
    python -m ultimate_pipeline.tools.check_osm2world_stack --osm path/to/file.osm --out ./test_out \
        --osm2world-timeout 1800 --blender-timeout 600
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def check_java() -> Tuple[bool, str]:
    """Check Java availability and version."""
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stderr or result.stdout or ""
        for line in output.strip().split("\n"):
            if "version" in line.lower():
                return True, line.strip()
        return True, output.split("\n")[0].strip() if output else "unknown"
    except FileNotFoundError:
        return False, "Java not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "Java check timed out"
    except Exception as e:
        return False, f"Java check failed: {e}"


def run_osm2world_check(
    osm_path: str,
    output_dir: str,
    osm2world_home: Optional[str] = None,
    timeout_sec: int = 1800,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Run OSM2World and return (success, result_dict).
    """
    from ultimate_pipeline.enrichment.osm2world_runner import OSM2WorldRunner

    runner = OSM2WorldRunner(
        osm_path=osm_path,
        output_dir=output_dir,
        osm2world_home=osm2world_home,
        timeout_sec=timeout_sec,
    )
    result = runner.run()

    success = result.status in ("ok", "cached")
    return success, result.to_dict()


def run_blender_check(
    obj_path: str,
    output_dir: str,
    blender_exe: Optional[str] = None,
    timeout_sec: int = 600,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Run Blender OBJ → FBX conversion and return (success, result_dict).
    """
    from ultimate_pipeline.enrichment.blender_runner import BlenderRunner

    runner = BlenderRunner(
        obj_path=obj_path,
        output_dir=output_dir,
        blender_exe=blender_exe,
        timeout_sec=timeout_sec,
    )
    result = runner.run()

    success = result.status in ("ok",)
    return success, result.to_dict()


def main():
    parser = argparse.ArgumentParser(
        description="OSM2World + Blender Stack Sanity Check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic check (OSM2World only):
  python -m ultimate_pipeline.tools.check_osm2world_stack --osm city.osm --out ./test_out

  # With Blender FBX conversion:
  python -m ultimate_pipeline.tools.check_osm2world_stack --osm city.osm --out ./test_out --blender

  # Strict mode (fail on any warning):
  python -m ultimate_pipeline.tools.check_osm2world_stack --osm city.osm --out ./test_out --strict
        """
    )
    parser.add_argument("--osm", required=True, help="Path to OSM file")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--osm2world-home", help="OSM2World installation directory")
    parser.add_argument("--osm2world-timeout", type=int, default=1800,
                        help="OSM2World timeout in seconds (default: 1800)")
    parser.add_argument("--blender", action="store_true",
                        help="Also run Blender OBJ → FBX conversion")
    parser.add_argument("--blender-exe", help="Path to Blender executable")
    parser.add_argument("--blender-timeout", type=int, default=600,
                        help="Blender timeout in seconds (default: 600)")
    parser.add_argument("--strict", action="store_true",
                        help="Fail on any warning (e.g., partial outputs)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")

    args = parser.parse_args()

    start_time = time.time()
    results: Dict[str, Any] = {
        "start_time": datetime.now().isoformat(),
        "osm_path": args.osm,
        "output_dir": args.out,
        "stages": {},
        "success": False,
    }

    # Ensure output directory exists
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("OSM2World + Blender Stack Sanity Check")
    print("=" * 60)
    print(f"OSM file: {args.osm}")
    print(f"Output:   {args.out}")
    print()

    all_ok = True

    # ---------- Stage 1: Java Check ----------
    print("[1/3] Checking Java...")
    java_ok, java_version = check_java()
    results["stages"]["java"] = {
        "ok": java_ok,
        "version": java_version,
    }

    if java_ok:
        print(f"      ✅ Java: {java_version}")
    else:
        print(f"      ❌ Java: {java_version}")
        all_ok = False

    if not java_ok:
        results["success"] = False
        results["end_time"] = datetime.now().isoformat()
        results["duration_sec"] = round(time.time() - start_time, 3)
        _write_summary(output_dir, results, args.json)
        print("\n❌ FAILED: Java not available")
        sys.exit(1)

    # ---------- Stage 2: OSM2World ----------
    print(f"\n[2/3] Running OSM2World (timeout: {args.osm2world_timeout}s)...")
    osm2world_dir = output_dir / "osm2world"
    osm2world_ok, osm2world_result = run_osm2world_check(
        osm_path=args.osm,
        output_dir=str(osm2world_dir),
        osm2world_home=args.osm2world_home,
        timeout_sec=args.osm2world_timeout,
    )
    results["stages"]["osm2world"] = osm2world_result

    # Print debug info
    print(f"      OSM (abs):    {osm2world_result.get('abs_osm_path', 'N/A')}")
    print(f"      Config (abs): {osm2world_result.get('abs_config_path', 'N/A')}")
    print(f"      Config hex:   {osm2world_result.get('config_header_hex', 'N/A')}")
    print(f"      Working dir:  {osm2world_result.get('working_dir', 'N/A')}")

    if osm2world_ok:
        outputs = osm2world_result.get("outputs", {})
        variant = osm2world_result.get("successful_variant", 0)
        print(f"      ✅ OSM2World: {osm2world_result.get('reason', 'ok')} (variant {variant})")
        for name, path in outputs.items():
            size_str = ""
            if Path(path).exists():
                size_mb = Path(path).stat().st_size / (1024 * 1024)
                size_str = f" ({size_mb:.2f} MB)"
            print(f"         -> {name}: {path}{size_str}")
    elif osm2world_result.get("status") == "skipped":
        print(f"      [SKIP] OSM2World skipped: {osm2world_result.get('reason', '')}")
        if args.strict:
            all_ok = False
    else:
        print(f"      [FAIL] OSM2World: {osm2world_result.get('reason', 'failed')}")
        # Print last command attempted
        cmd_lines = osm2world_result.get("command_lines", [])
        if cmd_lines:
            print(f"      Last cmd: {' '.join(cmd_lines[-1])}")
        # Print stderr log path
        stderr_log = osm2world_result.get("stderr_log", "")
        if stderr_log:
            print(f"      Stderr log: {stderr_log}")
        all_ok = False

    print(f"      Logs dir: {osm2world_dir}")

    # Check for config failure
    if "config_not_loaded" in osm2world_result.get("reason", ""):
        print("      [WARN] CONFIG FAILURE: OSM2World did not load the config file!")
        all_ok = False

    # ---------- Stage 3: Blender (optional) ----------
    obj_path = osm2world_result.get("outputs", {}).get("scene.obj")

    if args.blender:
        if obj_path and Path(obj_path).exists():
            print(f"\n[3/3] Running Blender OBJ → FBX (timeout: {args.blender_timeout}s)...")
            blender_ok, blender_result = run_blender_check(
                obj_path=obj_path,
                output_dir=str(osm2world_dir),  # Same dir as OSM2World
                blender_exe=args.blender_exe,
                timeout_sec=args.blender_timeout,
            )
            results["stages"]["blender"] = blender_result

            if blender_ok:
                fbx_path = blender_result.get("output_fbx", "")
                size_str = ""
                if fbx_path and Path(fbx_path).exists():
                    size_mb = Path(fbx_path).stat().st_size / (1024 * 1024)
                    size_str = f" ({size_mb:.2f} MB)"
                print(f"      ✅ Blender: {blender_result.get('reason', 'ok')}")
                print(f"         → FBX: {fbx_path}{size_str}")
            elif blender_result.get("status") == "skipped":
                print(f"      ⏭️ Blender skipped: {blender_result.get('reason', '')}")
                if args.strict:
                    all_ok = False
            else:
                print(f"      ❌ Blender: {blender_result.get('reason', 'failed')}")
                all_ok = False

            print(f"      📁 Logs: {blender_result.get('stdout_log', osm2world_dir)}")
        else:
            print("\n[3/3] Blender skipped: No OBJ file available from OSM2World")
            results["stages"]["blender"] = {"status": "skipped", "reason": "No OBJ available"}
            if args.strict:
                all_ok = False
    else:
        print("\n[3/3] Blender: skipped (use --blender to enable)")
        results["stages"]["blender"] = {"status": "disabled"}

    # ---------- Summary ----------
    duration = round(time.time() - start_time, 3)
    results["success"] = all_ok
    results["end_time"] = datetime.now().isoformat()
    results["duration_sec"] = duration

    _write_summary(output_dir, results, args.json)

    print()
    print("=" * 60)
    if all_ok:
        print(f"✅ SUCCESS ({duration:.1f}s)")
        print(f"   Artifacts: {output_dir}")
    else:
        print(f"❌ FAILED ({duration:.1f}s)")
        print(f"   Check logs in: {output_dir}")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


def _write_summary(output_dir: Path, results: Dict[str, Any], as_json: bool):
    """Write summary to file and optionally print as JSON."""
    summary_path = output_dir / "check_osm2world_stack_summary.json"
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
    except Exception as e:
        print(f"Warning: Could not write summary: {e}")

    if as_json:
        print()
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
