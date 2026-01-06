# ultimate_pipeline/diagnostics/pipeline_diagnostics.py

import xml.etree.ElementTree as ET

from ultimate_pipeline.core.xodr_sanitizer import _safe_float


class PipelineDiagnostics:
    @staticmethod
    def check_elevation(root: ET.Element, label: str):
        print(f"\n🏔 Elevation Diagnostics: {label}")
        bad = 0
        for road in root.findall("road"):
            elevs = road.findall("elevationProfile/elevation")
            for ev in elevs:
                a = _safe_float(ev.get("a", "0"), 0.0)
                if abs(a) > 50:
                    bad += 1
        if bad:
            print(f"   ⚠ {bad} suspicious elevation entries.")
        else:
            print("   ✔ Elevation coefficients look reasonable.")

    @staticmethod
    def check_lane_widths(root: ET.Element, label: str):
        print(f"\n🚗 Lane Width Diagnostics: {label}")
        invalid = 0
        for w in root.findall(".//lane/width"):
            a = _safe_float(w.get("a", "0"), 0.0)
            if a <= 0:
                invalid += 1
        if invalid:
            print(f"   ⚠ {invalid} lanes have non-positive width.")
        else:
            print("   ✔ All lane widths positive.")
