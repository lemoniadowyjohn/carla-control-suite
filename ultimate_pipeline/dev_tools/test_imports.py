#!/usr/bin/env python3

"""
Recursively scan and test-import every module inside ultimate_pipeline.

This will:
  • walk the directory
  • detect *.py files
  • convert paths → dotted package names
  • attempt imports using importlib
  • report failures clearly

Run from project root:
    python test_imports.py
"""

import os
import sys
import importlib

PACKAGE_DIR = "ultimate_pipeline"

def find_python_modules(base_dir):
    modules = []

    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, base_dir)

                mod = rel_path.replace("\\", "/").replace("/", ".")
                mod = mod[:-3]  # strip .py

                modules.append(f"{PACKAGE_DIR}.{mod}")

    return modules


def test_import(module_name):
    try:
        importlib.import_module(module_name)
        print(f"✅ IMPORT OK   {module_name}")
        return True
    except Exception as e:
        print(f"❌ IMPORT FAIL {module_name}")
        print(f"   ↳ {type(e).__name__}: {e}")
        return False


def main():
    # Ensure project root is on sys.path
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    print("\n🔍 Scanning for modules inside ultimate_pipeline...\n")

    modules = find_python_modules(PACKAGE_DIR)

    print(f"Found {len(modules)} modules.\n")
    print("Testing imports:\n")

    failures = 0
    for m in sorted(modules):
        ok = test_import(m)
        if not ok:
            failures += 1

    print("\n=================== SUMMARY ===================")
    print(f"Total modules : {len(modules)}")
    print(f"Import OK     : {len(modules) - failures}")
    print(f"Import FAIL   : {failures}")
    print("================================================\n")

    if failures > 0:
        print("⚠️ Some imports failed. Fix them and run again.")
    else:
        print("🎉 All imports successful! Pipeline structure consistent.")


if __name__ == "__main__":
    main()
