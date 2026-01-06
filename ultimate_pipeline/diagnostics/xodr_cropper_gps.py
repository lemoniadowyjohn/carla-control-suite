#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os

# ---------------------------------------------------------------------
# Make project root importable when running this file directly
# ---------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(__file__, "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import xml.etree.ElementTree as ET
import math

from pyproj import Transformer
from ultimate_pipeline.config.settings import SETTINGS


class XODRCropperGPS:
    """
    Crop an OpenDRIVE file around a GPS lat/lon center.

    Uses the same tmerc projection as <geoReference>, configured
    via coordinates.json through config.settings.SETTINGS.
    """

    def __init__(self):
        gps = SETTINGS.load_gps_bounds()

        # Fallbacks, just in case
        lat0 = gps.get("lat_min", 48.75)
        lon0 = gps.get("lon_min", 11.42)

        proj_string = (
            f"+proj=tmerc +lat_0={lat0} +lon_0={lon0} "
            "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )

        self.transformer = Transformer.from_crs(
            "EPSG:4326",
            proj_string,
            always_xy=True,
        )

    def crop_gps(
        self,
        input_xodr: str,
        output_xodr: str,
        lat_center: float,
        lon_center: float,
        r: float = 300.0,
    ) -> None:
        """
        Crop around GPS center within radius r (meters).
        """

        # GPS → local x/y
        cx, cy = self.transformer.transform(lon_center, lat_center)

        tree = ET.parse(input_xodr)
        root = tree.getroot()

        roads = root.findall("road")
        keep = []

        for road in roads:
            planview = road.find("planView")
            if planview is None:
                continue

            inside = False
            for geom in planview.findall("geometry"):
                x = float(geom.get("x", "0"))
                y = float(geom.get("y", "0"))

                if math.hypot(x - cx, y - cy) <= r:
                    inside = True
                    break

            if inside:
                keep.append(road)

        # Replace road set
        for r_node in roads:
            root.remove(r_node)
        for r_node in keep:
            root.append(r_node)

        tree.write(output_xodr, encoding="utf-8", xml_declaration=True)
        print(f"🗂 GPS-based XODR crop created → {output_xodr} (roads kept: {len(keep)})")
