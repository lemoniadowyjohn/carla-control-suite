# ultimate_pipeline/quality/check_xml_integrity.py

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import List, Dict, Any


class XMLIntegrityChecker:
    """
    Very lightweight structural check on the XODR file.

    Returns a list of issues; empty list means "no obvious problems".
    """

    @staticmethod
    def validate(path: str) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        if not os.path.isfile(path):
            issues.append({"type": "missing_file", "path": path})
            return issues

        try:
            tree = ET.parse(path)
            root = tree.getroot()
        except Exception as e:
            issues.append({"type": "parse_error", "error": str(e)})
            return issues

        if root.tag != "OpenDRIVE":
            issues.append({"type": "root_tag_mismatch", "tag": root.tag})

        roads = root.findall("road")
        if not roads:
            issues.append({"type": "no_roads"})

        header = root.find("header")
        if header is None:
            issues.append({"type": "missing_header"})
        else:
            for key in ("north", "south", "east", "west"):
                if key not in header.attrib:
                    issues.append({"type": "header_missing_attr", "attr": key})

        return issues
