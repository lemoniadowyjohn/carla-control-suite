# ultimate_pipeline/quality/check_xodr_schema.py

from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import List, Tuple, Optional

try:
    from lxml import etree
except ImportError:
    etree = None


def check_xml_uniqueness(root: ET.Element) -> List[str]:
    """
    Checks for duplicate roadId and laneId combinations.

    Returns a list of human-readable issue strings.
    """
    issues: List[str] = []

    # Road ID uniqueness
    seen_roads = {}
    for r in root.findall("road"):
        rid = r.get("id")
        if rid is None:
            continue
        if rid in seen_roads:
            issues.append(f"Duplicate road id detected: {rid}")
        else:
            seen_roads[rid] = True

    # Lane ID uniqueness (per road + laneSection + side + lane)
    seen_lane_keys = set()
    for road in root.findall("road"):
        rid = road.get("id", "unknown")
        for lsec in road.findall(".//laneSection"):
            s = lsec.get("s", "0.0")
            for side in lsec.findall("./left") + lsec.findall("./right"):
                side_name = side.tag  # "left" or "right"
                for lane in side.findall("./lane"):
                    lid = lane.get("id")
                    if lid is None:
                        continue
                    key = (rid, s, side_name, lid)
                    if key in seen_lane_keys:
                        issues.append(
                            f"Duplicate lane id in road={rid}, s={s}, side={side_name}, laneId={lid}"
                        )
                    else:
                        seen_lane_keys.add(key)

    return issues


def validate_xodr_schema(xodr_path: str, xsd_path: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    If lxml + XSD available: validate against official OpenDRIVE schema.
    Returns (ok, error_message_or_None).
    """
    if etree is None or not xsd_path:
        return True, None  # schema check skipped

    try:
        schema = etree.XMLSchema(file=xsd_path)
        parser = etree.XMLParser(schema=schema)
        etree.parse(xodr_path, parser)
        return True, None
    except Exception as e:
        return False, str(e)
