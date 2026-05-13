#!/usr/bin/env python3
import os, sys
from ultimate_pipeline.diagnostics.xodr_cropper_gps import XODRCropperGPS
from ultimate_pipeline.config.settings import SETTINGS

if len(sys.argv) < 2:
    print("Usage: python tools/debug_crop.py <xodr>")
    sys.exit()

gps = SETTINGS.load_gps_bounds()
lat_center = (gps["lat_min"] + gps["lat_max"]) / 2
lon_center = (gps["lon_min"] + gps["lon_max"]) / 2

out = "debug_crop.xodr"
XODRCropperGPS().crop_gps(sys.argv[1], out, lat_center, lon_center, 800.0)

print("Saved crop →", out)
