#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Fast CARLA XODR preview loader with automatic map cropping.

- Prevents CARLA from loading the full city during pipeline steps
- Extracts a small 300m radius slice for visualization
- Loads cropped XODR instantly (1–2 sec)
- Keeps the real full map untouched for the pipeline
"""

from __future__ import annotations

import os
import time

# CARLA is optional in many environments (unit tests, CI, offline analysis).
# Never fail at import time.
try:  # pragma: no cover
    import carla  # type: ignore
    _CARLA_AVAILABLE = True
except Exception:  # pragma: no cover
    carla = None  # type: ignore
    _CARLA_AVAILABLE = False
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world
import xml.etree.ElementTree as ET
import math

from ultimate_pipeline.config.settings import SETTINGS


# ============================================================
# SMALL, FAST XODR CROPPER (local helper; no external imports)
# ============================================================
def crop_xodr(input_xodr: str, output_xodr: str, radius_m: float = 300.0) -> None:
    """
    Crops the OpenDRIVE file to keep only roads whose planView geometry is within
    a given radius around (0,0). Works because your maps are local-metric after geoReference.

    NOTE: This is intentionally conservative: it keeps roads if ANY geometry point is close.
    """
    tree = ET.parse(input_xodr)
    root = tree.getroot()

    # Estimate road centroid by sampling planView geometry start points.
    # Keep roads with at least one geometry start within radius.
    keep_road_ids = set()

    for road in root.findall("road"):
        rid = road.get("id")
        pv = road.find("planView")
        if pv is None:
            continue

        keep = False
        for geom in pv.findall("geometry"):
            try:
                x = float(geom.get("x", "nan"))
                y = float(geom.get("y", "nan"))
                if math.isfinite(x) and math.isfinite(y):
                    if (x * x + y * y) <= (radius_m * radius_m):
                        keep = True
                        break
            except Exception:
                continue

        if keep and rid is not None:
            keep_road_ids.add(rid)

    # Remove roads not in keep set
    removed = 0
    for road in list(root.findall("road")):
        rid = road.get("id")
        if rid not in keep_road_ids:
            root.remove(road)
            removed += 1

    # Remove junctions that have no remaining roads referencing them (best-effort)
    # (Safe even if missed; CARLA is tolerant to unused junction elements.)
    existing_road_ids = {r.get("id") for r in root.findall("road") if r.get("id") is not None}
    junctions = root.find("junctions")
    if junctions is not None:
        for j in list(junctions.findall("junction")):
            # If no road references this junction id, drop it.
            jid = j.get("id")
            if not jid:
                continue
            referenced = False
            for r in root.findall("road"):
                if r.get("junction") == jid:
                    referenced = True
                    break
            if not referenced:
                try:
                    junctions.remove(j)
                except Exception:
                    pass

    os.makedirs(os.path.dirname(output_xodr), exist_ok=True)
    tree.write(output_xodr, encoding="utf-8", xml_declaration=True)


class CarlaValidator:
    """
    QA loader for optional *manual* visualization.

    IMPORTANT:
    - By default this must NOT load CARLA during pipeline steps.
    - To explicitly enable quick preview loading, set:
        UP_ENABLE_CARLA_QUICK_LOAD=1
    """

    @staticmethod
    def quick_visual_check(xodr_path: str, message: str = "") -> None:
        """
        QA visualization stub.

        CARLA loading is intentionally DISABLED here by default.
        All CARLA loads should happen ONLY:
          - after STEP 8 (final map)
          - during tile QA
        """
        print(f"[QA] Visualization checkpoint reached → {message}")
        # By default, this hook must NOT load CARLA during early pipeline stages.
        # To explicitly enable quick preview loading, set environment variable:
        #   UP_ENABLE_CARLA_QUICK_LOAD=1
        enable = os.environ.get("UP_ENABLE_CARLA_QUICK_LOAD", "0").strip().lower() in ("1", "true", "yes", "y")
        if not enable:
            print("     (CARLA load skipped for safety)")
            return
        print("     (CARLA preview load ENABLED via UP_ENABLE_CARLA_QUICK_LOAD=1)")

        if not _CARLA_AVAILABLE:
            raise RuntimeError(
                "CARLA PythonAPI not found on PYTHONPATH. "
                "Install/activate CARLA PythonAPI to use quick preview loading."
            )

        if not _CARLA_AVAILABLE:
            print("     (CARLA PythonAPI not available; preview load skipped)")
            return

        try:
            # ---------------------
            # 1. Crop to a tiny area
            # ---------------------
            crop_path = xodr_path.replace(".xodr", "_QA_CROP.xodr")
            crop_xodr(xodr_path, crop_path, radius_m=300.0)

            # ---------------------
            # 2. Load cropped XODR
            # ---------------------
            client = carla.Client(SETTINGS.CARLA_HOST, SETTINGS.CARLA_PORT)
            client.set_timeout(60.0)

            with open(crop_path, "r", encoding="utf-8", errors="ignore") as f:
                xodr_text = f.read()

            world = load_opendrive_world(
                client=client,
                xodr_text=xodr_text,
                timeout_s=60.0,
                retries=1,
                do_reload=True,
            )

            # settle a bit
            time.sleep(0.5)

            # ----------------------------------------------
            # 3. Move spectator to a closer top-down position
            # ----------------------------------------------
            spectator = world.get_spectator()
            spectator.set_transform(
                carla.Transform(
                    carla.Location(x=0.0, y=0.0, z=50.0),
                    carla.Rotation(pitch=-90.0)
                )
            )

            print(f"\n👁 QA VISUAL CHECK → {message}")
            print(f"   Loaded preview slice: {crop_path}\n")

        except Exception as e:
            print(f"❌ CARLA QA load failed ({message}): {e}")
