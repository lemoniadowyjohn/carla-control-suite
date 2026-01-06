# ultimate_pipeline/core/xodr_lightener.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
XODR Lightener (CARLA-safe)

Creates a lightweight OpenDRIVE file by removing heavy, non-drivable layers.
Used for fast CARLA loading and spawn-point validation.

IMPORTANT:
- Controllers are kept by default because CARLA may rely on them
  to resolve junction transitions.
"""

import xml.etree.ElementTree as ET


def strip_heavy_xodr_layers(
    input_xodr: str,
    output_xodr: str,
    *,
    drop_objects: bool = True,
    drop_signals: bool = False,
    drop_controllers: bool = False,     # ✅ CARLA-safe default
    drop_junction_groups: bool = True,
) -> None:
    """
    Create a lightweight OpenDRIVE copy by removing heavy XML sections.

    Notes:
    - This does NOT touch roads/lanes/planView/elevationProfile.
    - Controllers are kept by default for CARLA stability.
    """

    tree = ET.parse(input_xodr)
    root = tree.getroot()

    # ElementTree has no getparent(), build a parent map once
    parent_map = {child: parent for parent in root.iter() for child in list(parent)}

    def _remove_xpath(xpath: str) -> int:
        removed = 0
        for elem in list(root.findall(xpath)):
            parent = parent_map.get(elem)
            if parent is not None:
                parent.remove(elem)
                removed += 1
        return removed

    removed_summary = {}

    if drop_objects:
        # In OpenDRIVE, <objects> is usually a direct child of <OpenDRIVE>,
        # but we still use // for robustness.
        removed_summary["objects"] = _remove_xpath(".//objects")

    if drop_signals:
        # Signals can be heavy, but dropping them is usually safe for spawn QA.
        removed_summary["signals"] = _remove_xpath(".//signals")

    if drop_controllers:
        # ⚠ Potentially unsafe in CARLA for some junction graphs; default is False.
        removed_summary["controllers"] = _remove_xpath(".//controller")

    if drop_junction_groups:
        removed_summary["junction_groups"] = _remove_xpath(".//junctionGroup")

    tree.write(output_xodr, encoding="utf-8", xml_declaration=True)

    print(
        f"🪶 XODR lightener: {input_xodr} → {output_xodr} | removed={removed_summary}"
    )
