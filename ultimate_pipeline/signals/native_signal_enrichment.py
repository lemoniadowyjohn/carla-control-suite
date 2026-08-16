from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def apply_native_signal_enrichment(
    *,
    xodr_path: str | os.PathLike[str],
    osm_path: str | os.PathLike[str],
    report_path: Optional[str | os.PathLike[str]] = None,
    min_signals: int = 1,
) -> Dict[str, Any]:
    """
    Apply governed Phase-H native OpenDRIVE signal enrichment in-place.

    This writes <signal> elements from OSM maxspeed / traffic_sign tags and
    never fabricates signal evidence. If matching yields fewer than
    ``min_signals`` native signals, the function raises.
    """
    xodr = Path(xodr_path)
    osm = Path(osm_path)
    if not xodr.exists():
        raise FileNotFoundError(f"XODR missing for native signal enrichment: {xodr}")
    if not osm.exists():
        raise FileNotFoundError(f"OSM missing for native signal enrichment: {osm}")

    from ultimate_pipeline.tools.phase_h0_osm_signal_extract import OSMSignalExtractor
    from ultimate_pipeline.tools.phase_h1_osm_road_match import match_candidate_to_roads
    from ultimate_pipeline.tools.phase_h2_signal_writer import (
        remove_legacy_speeds,
        write_speed_limits,
        write_turn_lanes,
        write_zone_signs,
    )
    from ultimate_pipeline.tools.phase_h3_signal_integrity import audit_clean

    root = ET.parse(xodr).getroot()
    survey = OSMSignalExtractor(str(osm), str(xodr)).extract()
    matches = match_candidate_to_roads(root, survey["candidates"])

    legacy_removed = remove_legacy_speeds(root)
    speed = write_speed_limits(root, survey["candidates"], matches["matched"])
    zone = write_zone_signs(root, survey["candidates"], matches["matched"])
    turn = write_turn_lanes(root, survey["candidates"], matches["matched"])
    audit = audit_clean(root)
    signal_count = len(root.findall(".//signal"))

    report: Dict[str, Any] = {
        "producer": "ultimate_pipeline.signals.native_signal_enrichment",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "xodr_path": str(xodr),
        "osm_path": str(osm),
        "survey_counters": survey.get("counters", {}),
        "matching": {
            "matched": len(matches.get("matched", [])),
            "ambiguous": len(matches.get("ambiguous", [])),
            "unmapped": len(matches.get("unmapped", [])),
        },
        "legacy_speed_removed": int(legacy_removed),
        "speed_limits": speed,
        "zone_signs": zone,
        "turn_lanes": turn,
        "signals_after": int(signal_count),
        "min_signals": int(min_signals),
        "integrity": audit,
        "ok": bool(signal_count >= int(min_signals) and audit.get("clean")),
    }

    if report_path is not None:
        rp = Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True), encoding="utf-8")

    if signal_count < int(min_signals):
        raise RuntimeError(
            "Native signal enrichment produced too few signals: "
            f"{signal_count} < {int(min_signals)}"
        )
    if not audit.get("clean"):
        raise RuntimeError("Native signal enrichment failed integrity audit")

    ET.ElementTree(root).write(xodr, encoding="utf-8", xml_declaration=True)
    return report
