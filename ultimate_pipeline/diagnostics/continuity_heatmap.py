import xml.etree.ElementTree as ET
import json
import math
import os
from typing import Dict, Any, Tuple, List

import matplotlib.pyplot as plt
from ultimate_pipeline.diagnostics.continuity_metrics import compute_severity_per_road


def _load_severity_from_debug(debug_json: str) -> Dict[str, float]:
    with open(debug_json, "r", encoding="utf-8") as f:
        report = json.load(f)
    return compute_severity_per_road(report)


def _collect_road_polylines(xodr_path: str) -> Dict[str, List[Tuple[float, float]]]:
    tree = ET.parse(xodr_path)
    root = tree.getroot()

    roads = {}
    for road in root.findall("road"):
        rid = road.get("id", "?")
        geoms = list(road.findall("./planView/geometry"))
        if not geoms:
            continue

        # sort by s, then take (x,y) anchors
        try:
            geoms.sort(key=lambda g: float(g.get("s", "0")))
        except Exception:
            pass

        pts = []
        for g in geoms:
            try:
                x = float(g.get("x", 0.0))
                y = float(g.get("y", 0.0))
            except Exception:
                continue
            pts.append((x, y))

        if len(pts) >= 2:
            roads[rid] = pts

    return roads


def generate_anomaly_heatmap(
    xodr_path: str,
    continuity_debug_json: str,
    out_png: str,
    title: str = "Continuity Anomaly Heatmap",
):
    severity = _load_severity_from_debug(continuity_debug_json)
    roads = _collect_road_polylines(xodr_path)

    if not roads:
        print("⚠ No road polylines collected; heatmap skipped.")
        return

    # normalize severity into [0,1] for coloring
    if severity:
        max_s = max(severity.values())
    else:
        max_s = 0.0

    plt.figure(figsize=(10, 10))
    ax = plt.gca()

    for rid, pts in roads.items():
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

        s = severity.get(rid, 0.0)
        if max_s > 0:
            norm = max(0.0, min(1.0, s / max_s))
        else:
            norm = 0.0

        # simple grayscale mapping: 0=light, 1=dark
        # you can swap this for a colormap if you like
        color_val = 0.9 - 0.7 * norm  # high severity → darker
        ax.plot(xs, ys, linewidth=0.8, color=(color_val, color_val, color_val))

    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title)
    ax.invert_yaxis()  # OpenDRIVE usually has y-axis inverted vis-à-vis screen

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=200)
    plt.close()

    print(f"🖼 Anomaly heatmap saved → {out_png}")
