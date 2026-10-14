# ultimate_pipeline/quality/check_xml_integrity.py

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import List, Dict, Any


class XMLIntegrityChecker:
    """
    Very lightweight structural check on the XODR file.

    Returns a list of issues; empty list means "no obvious problems".

    OC-59 §16: this is XML_BASIC_INTEGRITY only (well-formed XML, root tag,
    road/header presence). An empty issue list MUST NOT be read as full
    OpenDRIVE validity -- every issue dict carries the honest validator name.
    """

    VALIDATOR_NAME = "XML_BASIC_INTEGRITY"

    @staticmethod
    def _issue(issue_type: str, **fields: Any) -> Dict[str, Any]:
        return {"validator": XMLIntegrityChecker.VALIDATOR_NAME,
                "type": issue_type, **fields}

    @staticmethod
    def validate(path: str) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        if not os.path.isfile(path):
            issues.append(XMLIntegrityChecker._issue("missing_file", path=path))
            return issues

        try:
            tree = ET.parse(path)
            root = tree.getroot()
        except Exception as e:
            issues.append(XMLIntegrityChecker._issue("parse_error", error=str(e)))
            return issues

        if root.tag != "OpenDRIVE":
            issues.append(XMLIntegrityChecker._issue("root_tag_mismatch", tag=root.tag))

        roads = root.findall("road")
        if not roads:
            issues.append(XMLIntegrityChecker._issue("no_roads"))

        header = root.find("header")
        if header is None:
            issues.append(XMLIntegrityChecker._issue("missing_header"))
        else:
            for key in ("north", "south", "east", "west"):
                if key not in header.attrib:
                    issues.append(XMLIntegrityChecker._issue("header_missing_attr", attr=key))

        return issues
