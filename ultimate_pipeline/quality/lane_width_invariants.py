# file: ultimate_pipeline/quality/lane_width_invariants.py
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from typing import Union


def default_report_path(out_dir: Union[str, Path], stage: str) -> str:
    """
    Standardizes where lane-width invariant reports are written.

    Matches your pipeline convention:
      <out_dir>/qa_stage_reports/<stage>__lane_width_invariants.json
    """
    out_dir = Path(out_dir)
    qa_dir = out_dir / "qa_stage_reports"
    qa_dir.mkdir(parents=True, exist_ok=True)

    safe_stage = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stage).strip("_")
    filename = f"{safe_stage}__lane_width_invariants.json"
    return str(qa_dir / filename)


__all__ = [
    # ... keep your existing exports here ...
    "default_report_path",
]

DEFAULT_LANE_WIDTH_M = float(os.getenv("UP_DEFAULT_LANE_WIDTH_M", "3.5"))


def _iter_lane_contexts(root: ET.Element) -> List[Tuple[str, str, str, ET.Element]]:
    """
    Yield lane contexts as tuples:
      (road_id, lane_section_s, lane_id, lane_element)
    """
    out: List[Tuple[str, str, str, ET.Element]] = []
    for road in root.findall("./road"):
        road_id = road.get("id", "")
        lanes = road.find("lanes")
        if lanes is None:
            continue
        for lane_section in lanes.findall("./laneSection"):
            ls_s = lane_section.get("s", "0")
            for lane in lane_section.findall(".//lane"):
                lane_id = lane.get("id", "")
                out.append((road_id, ls_s, lane_id, lane))
    return out


def _lane_needs_width(lane: ET.Element) -> bool:
    """
    CARLA import stability: non-center lanes (id != 0) should have at least one <width>.
    We enforce for any lane except center lane id=0.
    """
    lane_id = lane.get("id")
    if lane_id is None:
        return False
    try:
        if int(lane_id) == 0:
            return False
    except Exception:
        # If it's not an int, be conservative: enforce
        pass
    return True


def _has_any_width(lane: ET.Element) -> bool:
    return lane.find("./width") is not None


def _insert_default_width(lane: ET.Element, width_m: float) -> None:
    """
    Insert a default width record at sOffset=0.
    OpenDRIVE: <width sOffset="0" a="w" b="0" c="0" d="0" />
    """
    ET.SubElement(
        lane,
        "width",
        attrib={
            "sOffset": "0",
            "a": f"{width_m:.3f}",
            "b": "0",
            "c": "0",
            "d": "0",
        },
    )


def enforce_lane_width_invariants_on_root(
    root: ET.Element,
    *,
    default_width_m: float = DEFAULT_LANE_WIDTH_M,
    lane_types: Tuple[str, ...] = (
        "driving",
        "shoulder",
        "sidewalk",
        "border",
        "parking",
        "biking",
        "restricted",
        "none",
    ),
    max_examples: int = 25,
) -> Dict[str, Any]:
    """
    Enforce lane width invariants in-place on an already-loaded XODR root.

    Rule (CARLA-stability oriented):
      - For every lane where id != 0 (non-center) and lane type is in lane_types,
        ensure at least one <width> element exists.
      - If missing, insert a default <width> at sOffset=0 with a=default_width_m.

    Returns a report dict (thesis-friendly).
    """
    contexts = _iter_lane_contexts(root)

    missing_found = 0
    missing_fixed = 0
    examples: List[Dict[str, str]] = []

    for road_id, ls_s, lane_id, lane in contexts:
        if not _lane_needs_width(lane):
            continue

        lane_type = (lane.get("type") or "").strip()
        if lane_type and lane_type not in lane_types:
            continue

        if _has_any_width(lane):
            continue

        missing_found += 1
        if len(examples) < max_examples:
            examples.append(
                {
                    "road_id": road_id,
                    "lane_section_s": str(ls_s),
                    "lane_id": str(lane_id),
                    "lane_type": lane_type or "UNKNOWN",
                }
            )

        try:
            _insert_default_width(lane, default_width_m)
            missing_fixed += 1
        except Exception:
            # keep going; report will show unfixed
            pass

    unfixed = max(missing_found - missing_fixed, 0)

    severity: str
    if missing_found == 0:
        severity = "pass"
    elif unfixed == 0:
        severity = "warn"  # fixed but noteworthy
    else:
        severity = "fail"

    return {
        "ok": severity != "fail",
        "severity": severity,
        "defaults": {
            "default_width_m": default_width_m,
            "lane_types": list(lane_types),
        },
        "totals": {
            "missing_width_lanes_found": missing_found,
            "missing_width_lanes_fixed": missing_fixed,
            "missing_width_lanes_unfixed": unfixed,
        },
        "examples": examples,
    }


def write_lane_width_invariants_report(report: Dict[str, Any], out_dir: Path) -> str:
    """
    Persist lane width invariant report. Returns absolute path.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "lane_width_invariants_report.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True, default=str)
    return str(path)


# Optional: path-based helper (only if you want it here too)
def enforce_lane_width_invariants(
    xodr_path: str,
    *,
    report_path: Optional[str] = None,
    stage: str = "lane_width_invariants",
    default_width_m: float = DEFAULT_LANE_WIDTH_M,
) -> Dict[str, Any]:
    """
    File-based version: loads XODR, applies invariants, writes back if fixed.
    Keeps interface similar to what your STEP10 code expects.
    """
    tree = ET.parse(xodr_path)
    root = tree.getroot()

    rep = enforce_lane_width_invariants_on_root(
        root,
        default_width_m=default_width_m,
    )
    rep["stage"] = stage
    rep["xodr_path"] = xodr_path

    # Write back only if we actually fixed anything.
    if int(rep["totals"]["missing_width_lanes_fixed"]) > 0:
        tree.write(xodr_path, encoding="utf-8", xml_declaration=True)

    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=True, default=str)

    return rep


__all__ = [
    "enforce_lane_width_invariants_on_root",
    "write_lane_width_invariants_report",
    "enforce_lane_width_invariants",
]
