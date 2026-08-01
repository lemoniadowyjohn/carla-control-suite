#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick CARLA environment sanity checker.

Run:
  python -m ultimate_pipeline.tools.env_check_carla
"""

from __future__ import annotations

import sys
import importlib


def main() -> int:
    print("[CARLA ENV CHECK]")
    print(f"  python: {sys.version.replace(chr(10), ' ')}")
    print(f"  executable: {sys.executable}")

    try:
        carla = importlib.import_module("carla")
    except Exception as exc:
        print("  import carla: FAILED")
        print(f"    error: {exc}")
        print("    hint: ensure CARLA egg matches your Python version and is on PYTHONPATH.")
        return 1

    print("  import carla: OK")
    path = getattr(carla, "__file__", None)
    if path:
        print(f"  carla.__file__: {path}")
        lowered = str(path).lower()
        for tag in ("cp36", "cp37", "cp38", "cp39", "cp310", "cp311"):
            if tag in lowered and tag not in sys.executable.lower():
                print(f"    warning: egg tag {tag} may not match your Python version.")
                break

    version = getattr(carla, "__version__", None) or getattr(carla, "version", None)
    if callable(version):
        try:
            version = version()
        except Exception:
            pass
    if version:
        print(f"  carla version: {version}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
