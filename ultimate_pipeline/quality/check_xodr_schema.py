# ultimate_pipeline/quality/check_xodr_schema.py

from __future__ import annotations
import hashlib
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple, Optional

try:
    from lxml import etree
except ImportError:
    etree = None

try:
    import lxml as _lxml_pkg
    _LXML_VERSION = getattr(_lxml_pkg, "__version__", "unknown")
except Exception:
    _LXML_VERSION = "unavailable"


def _sha256_file(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except Exception:
        return None


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
    Legacy wrapper: (ok, error_message_or_None).

    Unavailable/unconfigured schema validation is NOT a pass: it returns
    (False, <explicit reason>) so no caller can mistake "not checked" for
    "valid". Use validate_xodr_schema_structured() for the full envelope.
    """
    result = validate_xodr_schema_structured(xodr_path, xsd_path)
    if result["status"] == "PASS":
        return True, None
    detail = result["status"]
    if result["errors"]:
        detail += ": " + "; ".join(str(e.get("message", e)) for e in result["errors"])
    return False, detail


def validate_xodr_schema_structured(
    xodr_path: str, xsd_path: Optional[str]
) -> Dict[str, Any]:
    """XSD validation with honest status (§14) and schema identity (§15).

    Status is one of PASS / FAIL / INCOMPLETE_DEPENDENCY (lxml missing or
    XSD unreadable) / NOT_CONFIGURED (no xsd_path). The last two carry full
    identity context and must never be interpreted as PASS.
    """
    # Status vocabulary (§14): PASS / FAIL / INCOMPLETE_DEPENDENCY /
    # NOT_CONFIGURED. "envelope_status" maps onto the shared §17 envelope
    # (PASS / FAIL / INCOMPLETE / NOT_RUN): anything but PASS must never be
    # read as valid.
    evidence: Dict[str, Any] = {
        "validator": "XSD_SCHEMA",
        "schema_version": "xsd_envelope_v1",
        "input_xodr_sha256": _sha256_file(xodr_path),
        "xsd_path": xsd_path,
        "xsd_sha256": _sha256_file(xsd_path) if xsd_path else None,
        "lxml_version": _LXML_VERSION,
        "errors": [],
        "warnings": [],
        "statistics": {},
    }
    if not xsd_path:
        evidence["status"] = "NOT_CONFIGURED"
        evidence["envelope_status"] = "NOT_RUN"
        evidence["errors"] = [{
            "code": "xsd_not_configured",
            "message": "No XSD configured (XODR_XSD_PATH unset): schema "
                       "conformance NOT CHECKED. This is not a pass.",
        }]
        return evidence
    if etree is None:
        evidence["status"] = "INCOMPLETE_DEPENDENCY"
        evidence["envelope_status"] = "INCOMPLETE"
        evidence["errors"] = [{
            "code": "xsd_lxml_unavailable",
            "message": "lxml is not installed: schema conformance NOT "
                       "CHECKED. This is not a pass.",
        }]
        return evidence

    import os
    if not os.path.isfile(xsd_path):
        evidence["status"] = "INCOMPLETE_DEPENDENCY"
        evidence["envelope_status"] = "INCOMPLETE"
        evidence["errors"] = [{
            "code": "xsd_file_missing",
            "message": f"XSD file not found: {xsd_path}. NOT CHECKED.",
        }]
        return evidence

    # OpenDRIVE revision/profile claimed by the file under test (§15).
    try:
        probe = ET.parse(xodr_path).getroot()
        header = probe.find("header") if probe is not None else None
        evidence["statistics"]["header_revision"] = {
            "revMajor": header.get("revMajor") if header is not None else None,
            "revMinor": header.get("revMinor") if header is not None else None,
        } if probe is not None and probe.tag == "OpenDRIVE" else None
    except Exception as exc:
        evidence["status"] = "FAIL"
        evidence["envelope_status"] = "FAIL"
        evidence["errors"] = [{
            "code": "xsd_input_unparseable",
            "message": f"Input XODR is not parseable XML: {exc}",
        }]
        return evidence

    try:
        schema = etree.XMLSchema(file=xsd_path)
        parser = etree.XMLParser(schema=schema)
        etree.parse(xodr_path, parser)
        evidence["status"] = "PASS"
        evidence["envelope_status"] = "PASS"
        return evidence
    except Exception as e:
        evidence["status"] = "FAIL"
        evidence["envelope_status"] = "FAIL"
        evidence["errors"] = [{
            "code": "xsd_conformance",
            "message": str(e),
        }]
        return evidence
