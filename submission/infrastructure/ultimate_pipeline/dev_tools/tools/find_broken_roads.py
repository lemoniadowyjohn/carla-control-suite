#!/usr/bin/env python3
import sys
from ultimate_pipeline.geometry.mesh_continuity_repairer import MeshContinuityRepairer

if len(sys.argv) < 2:
    print("Usage: python tools/find_broken_roads.py <xodr>")
    sys.exit()

repairer = MeshContinuityRepairer(sys.argv[1])
broken = repairer.scan_for_discontinuities()

for r in broken:
    print("⚠ Broken road:", r)
