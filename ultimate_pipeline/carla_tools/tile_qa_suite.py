"""
CLI TOOL:
Tile QA suite wrapper.

Uses the same validators as MainPipeline._step10_tile_qa().
Not imported by core pipeline.
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unified Tile QA Suite
---------------------

Runs all tile-level quality checks:

1) Tile validation (CarlaFinalTest)
2) Seam analysis (LaneSeamChecker)
3) Spawn Probe (TileSpawnProbe)
4) Dynamic Stress Test (TileStressTester)
5) Screenshot generator

Outputs:
- seam_statistics.json
- tile_validation.json
- tile_spawn_probe.json
- stress_results/*.json
- screenshots/*.png
"""

import os
import json
from glob import glob
from typing import Dict, List, Any

import carla

# Individual QA modules
from ultimate_pipeline.carla_tools.carla_final_test import CarlaFinalTest
from ultimate_pipeline.tile_validation.lane_seam_checker import LaneSeamChecker
from ultimate_pipeline.carla_tools.qa_tile_spawn_probe import TileSpawnProbe
from ultimate_pipeline.tile_validation.tile_stress_tester import TileStressTester
from ultimate_pipeline.carla_tools.screenshot_generator import ScreenshotGenerator


class TileQASuite:

    def __init__(
        self,
        client: carla.Client,
        out_dir: str,
        tiles_dir: str,
        settings,
    ):
        self.client = client
        self.out_dir = out_dir
        self.tiles_dir = tiles_dir
        self.settings = settings

        self.tiles = sorted(
            f for f in os.listdir(self.tiles_dir) if f.endswith(".xodr")
        )

        self.results = {
            "tile_validation": [],
            "seam_statistics": [],
            "spawn_probe": {},
            "stress": {},
        }

        self.qa_dir = os.path.join(self.out_dir, "qa")
        os.makedirs(self.qa_dir, exist_ok=True)

    # ======================================================================
    # STEP 1 — CARLA TILE VALIDATION + SEAM ANALYSIS
    # ======================================================================
    def run_tile_validation(self):
        print("\n🧭 Running tile-by-tile CARLA validation...")

        # Spawning an actor is the most common trigger for native CARLA crashes on Windows
        # (e.g., 0xC0000409). The suite defaults to *no-spawn* unless explicitly enabled.
        no_spawn = bool(getattr(self.settings, "TILE_QA_NO_SPAWN", True))

        prev_tile = None

        for tname in self.tiles:
            tile_path = os.path.join(self.tiles_dir, tname)

            print(f"\n   ▶ Validating tile: {tname}")
            report = CarlaFinalTest.run(
                tile_path,
                spawn_vehicle=not no_spawn,
            )

            # Pass criterion:
            # - If spawning is enabled, require a successful spawn.
            # - If spawning is disabled, require successful load + non-zero waypoints.
            if not no_spawn:
                passed = bool(report.get("vehicle_spawned", False))
            else:
                passed = bool(report.get("map_loaded", False)) and int(report.get("waypoints", 0) or 0) > 0

            self.results["tile_validation"].append({
                "tile": tname,
                "passed": bool(passed),
                "report": report,
            })

            # seam check (compare with previous)
            if prev_tile:
                seam = LaneSeamChecker.analyze(prev_tile, tile_path)
                self.results["seam_statistics"].append({
                    "from_tile": os.path.basename(prev_tile),
                    "to_tile": tname,
                    "lat": seam.max_lateral_offset,
                    "hdg": seam.max_heading_error,
                    "dz": seam.max_elevation_jump,
                    "warnings": seam.warnings,
                })

            prev_tile = tile_path

        # Write seam stats
        with open(os.path.join(self.qa_dir, "seam_statistics.json"), "w") as f:
            json.dump(self.results["seam_statistics"], f, indent=2)

        print("   ✓ Seam statistics written.")

    # ======================================================================
    # STEP 2 — SPAWN PROBE
    # ======================================================================
    def run_spawn_probe(self):
        if not self.settings.ENABLE_SPAWN_QA:
            print("⏭ Spawn QA disabled.")
            return

        print("\n🚦 Running Spawn Probe...")

        spawn_probe = TileSpawnProbe(
            client=self.client,
            tiles_dir=self.tiles_dir,
            tile_names=self.tiles,
            out_dir=self.qa_dir,
            max_spawns_per_tile=25,
            offset_m=1.3,
        )
        spawn_probe.run()

        # Load results
        probe_json = os.path.join(self.qa_dir, "tile_spawn_probe.json")
        with open(probe_json, "r") as f:
            self.results["spawn_probe"] = json.load(f)

        print("   ✓ Spawn probe complete.")

    # ======================================================================
    # STEP 3 — DYNAMIC STRESS TEST
    # ======================================================================
    def run_stress_test(self):
        if not self.settings.ENABLE_TILE_STRESS_TEST:
            print("⏭ Tile stress test disabled.")
            return

        print("\n🔥 Running Dynamic Tile Stress Test...")

        stress_root = os.path.join(self.qa_dir, "stress_results")
        os.makedirs(stress_root, exist_ok=True)

        for tname in self.tiles:
            tile_path = os.path.join(self.tiles_dir, tname)

            print(f"   ▶ Stress testing tile: {tname}")

            result_path = os.path.join(stress_root, f"{tname}.json")

            agg = TileStressTester.run(
                xodr_path=tile_path,
                duration=self.settings.TILE_STRESS_DURATION,
                save_json_to=result_path,
                tile_meta={"map_name": "Ingolstadt"},
            )

            self.results["stress"][tname] = agg
            print(f"      → Saved {result_path}")

        print("   ✓ Stress testing complete.")

    # ======================================================================
    # STEP 4 — SCREENSHOTS
    # ======================================================================
    def generate_screenshots(self):
        if not self.settings.ENABLE_SCREENSHOTS:
            print("⏭ Screenshot generation disabled.")
            return

        print("\n📸 Generating Screenshots...")

        ss_dir = os.path.join(self.qa_dir, "screenshots")
        os.makedirs(ss_dir, exist_ok=True)

        sg = ScreenshotGenerator(self.client, ss_dir)
        sg.capture_topdown("map_topdown.png")
        sg.batch_random(6)

        print("   ✓ Screenshots written.")

    # ======================================================================
    # MAIN ORCHESTRATOR
    # ======================================================================
    def run_all(self):
        print("\n==================== TILE QA SUITE ====================")

        self.run_tile_validation()
        self.run_spawn_probe()
        self.run_stress_test()
        self.generate_screenshots()

        summary_path = os.path.join(self.qa_dir, "qa_summary.json")
        with open(summary_path, "w") as f:
            json.dump(self.results, f, indent=2)

        print(f"\n🏁 QA Suite finished → {summary_path}")
