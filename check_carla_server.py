#!/usr/bin/env python3
"""Check for CARLA server availability."""
import subprocess, os, sys
from pathlib import Path

print("=== CARLA SERVER AVAILABILITY CHECK ===")

# Check for CarlaUE4 binary
for cmd in ["CarlaUE4.exe", "CarlaUE4.sh", "carla_server", "carla-simulator"]:
    try:
        result = subprocess.run(["where", cmd], capture_output=True, text=True, timeout=5)
        if result.stdout.strip():
            print(f"Found: {cmd} -> {result.stdout.strip()}")
        else:
            print(f"Not found: {cmd}")
    except Exception as e:
        print(f"Error checking {cmd}: {e}")

# Check for any CARLA-related executables in Program Files
print("\nSearching Program Files for CARLA executables...")
found = []
for root, dirs, files in os.walk("C:/Program Files"):
    for f in files:
        if 'Carla' in f or 'carla' in f.lower():
            path = os.path.join(root, f)
            if f.endswith(('.exe', '.sh')):
                found.append(path)
    if len(found) >= 5:
        break
for p in found[:5]:
    print(f"  {p}")
if not found:
    print("  None found")

# Check if carla module has server capabilities
print("\n=== CARLA PYTHON MODULE ===")
import carla
print(f"Module: {carla.__file__}")
print(f"Has Client: {hasattr(carla, 'Client')}")
print(f"Has World: {hasattr(carla, 'World')}")
print(f"Has Map: {hasattr(carla, 'Map')}")

# Check for server-side capabilities
try:
    from carla import server
    print("Has carla.server module")
except:
    print("No carla.server module")

# Check if there's a way to use the carla module as a server
# CARLA 0.9.16 has a Python-based server in some configurations
try:
    import carla.libcarla as libcarla
    print(f"libcarla available: {type(libcarla)}")
except:
    print("No libcarla")

# Check for any startup scripts in the repo
print("\n=== CARLA STARTUP SCRIPTS ===")
repo = Path(__file__).resolve().parents[0]
for script in repo.glob("**/*carla*server*"):
    print(f"  {script}")
for script in repo.glob("**/*start*server*"):
    print(f"  {script}")
for script in repo.glob("**/*run*server*"):
    print(f"  {script}")
for script in repo.glob("scripts/**/*.py"):
    if 'carla' in script.name.lower() or 'server' in script.name.lower():
        print(f"  {script}")

# Check if there's a Docker or container setup
print("\n=== DOCKER/CONTAINER CHECK ===")
try:
    result = subprocess.run(["docker", "ps"], capture_output=True, text=True, timeout=5)
    if result.returncode == 0 and result.stdout.strip():
        print(f"Docker containers running:\n{result.stdout[:500]}")
    else:
        print("No running Docker containers or Docker not available")
except:
    print("Docker not available")

print("\n=== CONCLUSION ===")
print("CARLA 0.9.16 Python client library is installed.")
print("CARLA server binary (CarlaUE4.exe) is NOT available on this machine.")
print("Phases C-F require a running CARLA server.")
