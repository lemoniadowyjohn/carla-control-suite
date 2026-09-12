"""Source-to-output completeness measurements for semantic map objects.

The metric is intentionally descriptive.  A source count can establish that a
writer produced no objects, but it cannot by itself prove placement or semantic
correctness.  Every metric therefore carries an explicit comparability label.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.regulatory_sign_writer import SIGN_TABLE


def _tags(element: ET.Element) -> dict[str, str]:
    return {
        str(tag.get("k")): str(tag.get("v"))
        for tag in element.findall("tag")
        if tag.get("k") and tag.get("v")
    }


def _osm_source_counts(osm_path: str | Path) -> dict[str, int]:
    """Count the exact source shapes supported by the current writers."""
    root = ET.parse(osm_path).getroot()
    counts = {"traffic_lights": 0, "crosswalks": 0, "regulatory_signs": 0}
    for element in root:
        if element.tag.rsplit("}", 1)[-1] not in {"node", "way"}:
            continue
        tags = _tags(element)
        if tags.get("highway") == "traffic_signals":
            counts["traffic_lights"] += 1
        # crosswalk_writer.py currently consumes only footway=crossing ways.
        if element.tag.rsplit("}", 1)[-1] == "way" and tags.get("footway") == "crossing":
            counts["crosswalks"] += 1
        if tags.get("traffic_sign"):
            counts["regulatory_signs"] += 1
    return counts


def _generated_counts(xodr_path: str | Path) -> dict[str, int]:
    root = ET.parse(xodr_path).getroot()
    known_regulatory_types = {entry[0] for entry in SIGN_TABLE.values()}
    regulatory = 0
    for obj in root.findall(".//object"):
        if (
            obj.get("type") in known_regulatory_types
            and (obj.get("name") or "").strip().lower().startswith("de:")
        ):
            regulatory += 1
    return {
        "traffic_lights": len(root.findall(".//object[@type='traffic_light']")),
        "crosswalks": len(root.findall(".//object[@type='crosswalk']")),
        "regulatory_signs": regulatory,
    }


_COMPARABILITY = {
    "traffic_lights": "COUNT_ONLY: OSM locations versus topology-inferred approach objects are not one-to-one.",
    "crosswalks": "DIRECT_FEATURE_COUNT: one writer object is expected per eligible OSM footway=crossing way, subject to geometric matching.",
    "regulatory_signs": "COUNT_ONLY: current writer maps a street-level OSM traffic_sign value to XODR segments; placement is not yet spatially one-to-one.",
}


def measure_semantic_completeness(
    xodr_path: str | Path,
    osm_path: str | Path,
) -> dict[str, Any]:
    """Measure generated/source counts without mutating either input artifact."""
    try:
        source = _osm_source_counts(osm_path)
        generated = _generated_counts(xodr_path)
    except (OSError, ET.ParseError) as exc:
        return {
            "status": "INCOMPLETE",
            "ok": False,
            "reason": f"source_or_xodr_parse_failed:{exc}",
            "object_types": {},
        }

    object_types: dict[str, dict[str, Any]] = {}
    for name in sorted(source):
        source_count = source[name]
        generated_count = generated[name]
        ratio = None if source_count == 0 else generated_count / source_count
        object_types[name] = {
            "source_count": source_count,
            "generated_count": generated_count,
            "generated_to_source_ratio": ratio,
            "comparability": _COMPARABILITY[name],
            "status": "NOT_APPLICABLE" if source_count == 0 else "MEASURED",
        }
    return {
        "status": "MEASURED",
        "ok": True,
        "object_types": object_types,
    }
