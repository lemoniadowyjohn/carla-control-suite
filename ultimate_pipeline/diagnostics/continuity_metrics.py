import json
import math
from typing import Dict, Any


def load_continuity_report(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_severity_per_road(report: Dict[str, Any],
                              gap_scale: float = 3.0,
                              hdg_scale_deg: float = 10.0,
                              len_scale: float = 1500.0) -> Dict[str, float]:
    """
    Compute a normalized severity score per road.

    severity = w_gap * (max_gap / gap_scale)
             + w_hdg * (max_hdg_deg / hdg_scale_deg)
             + w_len * (max_len / len_scale)

    You can adjust the weights below.
    """

    w_gap = 1.0
    w_hdg = 1.0
    w_len = 0.0   # length rarely a problem vs real world

    scores = {}

    for rid, info in report.items():
        max_gap = float(info.get("max_gap", 0.0))
        max_hdg = float(info.get("max_hdg", 0.0))    # radians
        max_len = float(info.get("max_len", 0.0))

        max_hdg_deg = abs(math.degrees(max_hdg))

        score = (
            w_gap * (max_gap / gap_scale) +
            w_hdg * (max_hdg_deg / hdg_scale_deg) +
            w_len * (max_len / len_scale)
        )

        scores[rid] = score

    return scores


def save_severity(scores: Dict[str, float], out_path: str):
    # sort by severity descending
    items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    out = [{"road_id": rid, "severity": s} for rid, s in items]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"📄 continuity_severity.json written → {out_path}")
