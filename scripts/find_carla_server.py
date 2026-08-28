#!/usr/bin/env python3
"""
Corrected CARLA server detection — searches all drives, not just C:/D:
Returns the first working CarlaUE4.exe found.
"""
import subprocess
import os
from pathlib import Path

COMMON_CARLA_PATHS = [
    r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe",
    r"E:\CARLA\CarlaUE4.exe",
    r"D:\CARLA\CARLA_0.9.16\CarlaUE4.exe",
    r"D:\CARLA\CarlaUE4.exe",
    r"C:\CARLA\CARLA_0.9.16\CarlaUE4.exe",
    r"C:\CARLA\CarlaUE4.exe",
    r"C:\Program Files\CARLA\CARLA_0.9.16\CarlaUE4.exe",
    r"C:\Program Files\Epic Games\CARLA_0.9.16\CarlaUE4.exe",
    os.path.join(os.environ.get("USERPROFILE", ""), "CARLA", "CARLA_0.9.16", "CarlaUE4.exe"),
    os.path.join(os.environ.get("USERPROFILE", ""), "CARLA", "CarlaUE4.exe"),
    os.path.join(os.environ.get("USERPROFILE", ""), "carla_simulator", "CarlaUE4.exe"),
]

def find_carla_server():
    """Return (exe_path, version_str) or (None, None) if not found."""
    for p in COMMON_CARLA_PATHS:
        if not p or not os.path.exists(p):
            continue
        try:
            # Quick version check via --help (fast, non-interactive)
            r = subprocess.run([p, "--help"], capture_output=True, timeout=15)
            if r.returncode in (0, 1):  # 0 or 1 both mean executable runs
                # Try to extract version from help output or just return path
                return p, "0.9.16"
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue
    # Fallback: search all drive letters
    for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        candidate = f"{drive}:\\CARLA\\CARLA_0.9.16\\CarlaUE4.exe"
        if os.path.exists(candidate):
            return candidate, "0.9.16"
    return None, None

def get_carla_root():
    exe, _ = find_carla_server()
    if exe:
        return str(Path(exe).parent)
    return os.environ.get("CARLA_ROOT")

if __name__ == "__main__":
    exe, ver = find_carla_server()
    root = get_carla_root()
    print(f"CarlaUE4.exe: {exe}")
    print(f"Version: {ver}")
    print(f"CARLA_ROOT: {root}")
    if exe:
        print("SERVER_AVAILABLE")
    else:
        print("SERVER_UNAVAILABLE")