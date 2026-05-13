# ultimate_pipeline/topology/missing_junction_link_repair.py
# -*- coding: utf-8 -*-
"""
Deterministic repair for roads referencing non-existent junctions.

Problem:
    Many XODR files have <link><predecessor|successor elementType="junction" elementId="X">
    where junction X does not exist in the <junction> list. These invalid refs cause
    TL-003 errors and crash strict validation.

Solution:
    Before running TopologyLinter, scan all roads and remove any junction links that
    reference non-existent junction IDs. This is safe because:
    - A road linking to a missing junction is effectively unlinked anyway
    - Removing the invalid ref makes the topology consistent with reality
    - The repair is deterministic and auditable via the report

This module does NOT loosen any quality gates - it fixes the data so gates pass.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set


def repair_missing_junction_links(
    root: ET.Element,
    *,
    logs_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Remove road link references to non-existent junctions.

    Parameters
    ----------
    root : ET.Element
        The OpenDRIVE root element (modified in-place).
    logs_dir : str, optional
        Directory to write the repair report JSON.

    Returns
    -------
    dict
        Report with counts and examples of removed references.
    """
    # Build set of existing junction IDs
    junction_ids: Set[str] = set()
    for junc in root.findall("junction"):
        jid = (junc.get("id") or "").strip()
        if jid:
            junction_ids.add(jid)

    # Track removals
    removed: List[Dict[str, Any]] = []
    roads_affected: Set[str] = set()

    # Scan all roads for invalid junction references
    for road in root.findall("road"):
        rid = (road.get("id") or "").strip()
        if not rid:
            continue

        link = road.find("link")
        if link is None:
            continue

        for tag in ("predecessor", "successor"):
            elements_to_remove: List[ET.Element] = []

            for elem in link.findall(tag):
                etype = (elem.get("elementType") or "").strip()
                eid = (elem.get("elementId") or "").strip()

                if etype == "junction" and eid and eid not in junction_ids:
                    # This is an invalid reference - mark for removal
                    elements_to_remove.append(elem)
                    removed.append({
                        "road_id": rid,
                        "link_type": tag,
                        "missing_junction_id": eid,
                        "contact_point": elem.get("contactPoint"),
                    })
                    roads_affected.add(rid)

            # Remove invalid elements
            for elem in elements_to_remove:
                link.remove(elem)

        # If link element is now empty, remove it too (cleaner XML)
        if len(link) == 0:
            road.remove(link)

    report: Dict[str, Any] = {
        "ok": True,
        "repair_type": "missing_junction_link_repair",
        "num_removed": len(removed),
        "num_roads_affected": len(roads_affected),
        "num_junctions_in_file": len(junction_ids),
        "missing_junction_ids_referenced": sorted(set(r["missing_junction_id"] for r in removed)),
        "roads_affected": sorted(roads_affected),
        "removals": removed[:100],  # Cap examples for readability
        "removals_truncated": len(removed) > 100,
    }

    # Persist report if logs_dir provided
    if logs_dir:
        try:
            os.makedirs(logs_dir, exist_ok=True)
            report_path = os.path.join(logs_dir, "missing_junction_link_repair.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, sort_keys=True)
        except Exception:
            pass  # Reporting must never crash the pipeline

    return report


def repair_missing_junction_links_file(
    xodr_path: str,
    *,
    logs_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    File-based wrapper: load XODR, repair, save back.

    Parameters
    ----------
    xodr_path : str
        Path to the XODR file (modified in-place).
    logs_dir : str, optional
        Directory to write the repair report JSON.

    Returns
    -------
    dict
        Repair report.
    """
    tree = ET.parse(xodr_path)
    root = tree.getroot()

    report = repair_missing_junction_links(root, logs_dir=logs_dir)

    if report["num_removed"] > 0:
        tree.write(xodr_path, encoding="utf-8", xml_declaration=True)
        report["file_modified"] = True
    else:
        report["file_modified"] = False

    return report
