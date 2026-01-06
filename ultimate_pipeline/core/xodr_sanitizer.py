#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Safe, NON-DESTRUCTIVE OpenDRIVE sanitizer for large real-world maps.

Design goals:
- "First, do no harm": never delete roads or laneSections.
- Only fix obviously invalid numeric values (NaN / inf / <= 0 lengths, <= 0 lane widths).
- Normalize header / geoReference / offset so CARLA & SUMO don't choke on whitespace.
- Remove only *clearly* invalid links:
    - self-links (road -> same road)
    - exact duplicates (same tag, same elementType, same elementId, same contactPoint)
- DO NOT:
    - Recompute road.length from geometry extents.
    - Clamp geometry s / length.
    - Move laneSection "s" positions.
    - Delete roads or junctions.
    - Remove links just because target road is missing (TopologyRepair / StructureScanner
      will do more informed repairs later).

This sanitizer is intentionally conservative and safe for large city-scale XODR.
"""

import os
import math
import subprocess
import logging
import xml.etree.ElementTree as ET
from typing import Optional
from ultimate_pipeline.core.repair_diff import diff_log
# =========================
# CONFIG & LOGGING
# =========================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("XODR_SANITIZER_SAFE")

DEFAULT_LANE_WIDTH = 3.5
SUMO_NETCONVERT = r"C:\Sumo\sumo-win64extra-1.24.0\sumo-1.24.0\bin\netconvert.exe"


class XODRSanitizer:
    """
    Lightweight / non-destructive OpenDRIVE sanitizer.

    What it does:
      - Ensures a sane <header>, <geoReference>, and <offset>.
      - Normalizes geoReference whitespace (avoids CARLA "cannot parse georeference" spam).
      - Fixes lane widths that are <= 0.0 by assigning DEFAULT_LANE_WIDTH.
      - Fills missing width polynomial coefficients (b, c, d, sOffset) with 0.0.
      - Fixes geometry elements with non-positive or NaN/inf length (sets to a tiny 0.01).
      - Removes only obviously broken links:
            * self-links (predecessor/successor pointing to same road)
            * exact duplicates under the same <link>.

    What it deliberately does NOT do:
      - No road deletion.
      - No junction deletion.
      - No laneSection deletion or clamping.
      - No rewriting of road "length".
      - No moving/clamping of laneSection "s".
      - No trimming of geometries based on road length.
      - No aggressive "clean invalid references by deleting them".

    The idea is: keep the original topology as intact as possible, and let
    higher-level tools (TopologyRepair, StructureScanner, SUMORepair) do the
    heavy surgery with more context.
    """

    # ---------- helpers ----------

    @staticmethod
    def _safe_float(value: Optional[str], default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            v = float(value)
            if math.isnan(v) or math.isinf(v):
                return default
            return v
        except Exception:
            return default

    # ---------- header / geoReference ----------

    @staticmethod
    def _ensure_header(root: ET.Element) -> None:
        """
        Ensure minimal <header>, <geoReference>, and <offset> exist.

        This is kept intentionally simple and non-destructive: we only create
        things if missing, and we don't overwrite existing numeric values
        (except normalizing geoReference whitespace).
        """
        header = root.find("header")
        if header is None:
            header = ET.SubElement(root, "header", {
                "revMajor": "1",
                "revMinor": "4",
                "name": "sanitized_map",
                "version": "1.00",
                "north": "100",
                "south": "-100",
                "east": "100",
                "west": "-100",
            })
            log.info("Created missing <header> element.")

        geo = header.find("geoReference")
        if geo is None:
            geo = ET.SubElement(header, "geoReference")
            geo.text = "+proj=utm +zone=32 +datum=WGS84 +units=m +no_defs"
            log.info("Created missing <geoReference> with default UTM32/WGS84.")
        else:
            if geo.text:
                # Normalize whitespace so CARLA's parser doesn't freak out.
                old = geo.text
                geo.text = " ".join(geo.text.split())
                if geo.text != old:
                    log.info("Normalized <geoReference> whitespace.")

        offset = header.find("offset")
        if offset is None:
            ET.SubElement(header, "offset", {
                "x": "0.0",
                "y": "0.0",
                "z": "0.0",
                "hdg": "0.0",
            })
            log.info("Created missing <offset> with zeros.")
        else:
            # Ensure required attributes exist, but don't override if present.
            for k in ("x", "y", "z", "hdg"):
                if k not in offset.attrib:
                    offset.set(k, "0.0")

    # ---------- lane & width fixes (non-destructive) ----------

    @staticmethod
    @staticmethod
    def _fix_lane_widths(road: ET.Element) -> int:
        """
        Guarantee that existing <width> elements have sane values:

        - If a <= 0.0 → set to DEFAULT_LANE_WIDTH.
        - If any of {b, c, d, sOffset} is missing → set to "0.0".
        """
        fixed = 0
        rid = road.get("id", "UNKNOWN")
        for width in road.findall(".//lane/width"):
            a_raw = width.get("a")
            a = XODRSanitizer._safe_float(a_raw, DEFAULT_LANE_WIDTH)
            if a <= 0.0:
                width.set("a", f"{DEFAULT_LANE_WIDTH:.3f}")
                fixed += 1
                diff_log.add(
                    "xodr_sanitizer",
                    rid,
                    {"fix": "lane_width_a_nonpositive", "original": a_raw},
                )

            # fill missing polynomial coeffs conservatively
            for k in ("b", "c", "d", "sOffset"):
                if k not in width.attrib:
                    width.set(k, "0.0")
                    diff_log.add(
                        "xodr_sanitizer",
                        rid,
                        {"fix": "lane_width_missing_coeff", "coeff": k},
                    )
        return fixed

    # ---------- geometry length sanity (non-destructive) ----------

    @staticmethod
    def _fix_geometries(road: ET.Element) -> int:
        """
        Ensure all <geometry> elements have a positive, finite "length".
        """
        fixed = 0
        rid = road.get("id", "UNKNOWN")
        for geo in road.findall(".//planView/geometry"):
            raw_len = geo.get("length")
            length = XODRSanitizer._safe_float(raw_len, 0.01)
            if length <= 0.0:
                length = 0.01
            if raw_len is None or float(raw_len) != length:
                geo.set("length", f"{length:.5f}")
                fixed += 1
                diff_log.add(
                    "xodr_sanitizer",
                    rid,
                    {"fix": "geometry_length_clamped", "old": raw_len, "new": length},
                )
        return fixed


    # ---------- links & junctions (very conservative cleanup) ----------

    @staticmethod
    def _fix_links(root: ET.Element) -> int:
        """
        Remove only *obviously* bad links:
          - self-links (predecessor/successor pointing to same road id)
          - exact duplicate entries under the same <link>

        We do NOT delete links just because target road is missing; higher-level
        tools have more context (e.g. StructureScanner, TopologyRepair).

        Returns the number of link elements removed.
        """
        removed = 0
        for road in root.findall("./road"):
            rid = road.get("id", "")
            link = road.find("link")
            if link is None:
                continue

            seen = set()
            for tag in ("predecessor", "successor"):
                for e in list(link.findall(tag)):
                    etype = e.get("elementType")
                    eid = e.get("elementId")
                    cpt = e.get("contactPoint", "")

                    key = (tag, etype, eid, cpt)

                    # Self-link is always nonsense.
                    if eid == rid:
                        link.remove(e)
                        removed += 1
                        continue

                    # Duplicate within same <link> is redundant.
                    if key in seen:
                        link.remove(e)
                        removed += 1
                    else:
                        seen.add(key)

        if removed > 0:
            log.info(f"Removed {removed} redundant/self link entries.")
        return removed

    @staticmethod
    def _fix_junctions(root: ET.Element) -> int:
        """
        Very conservative junction cleanup:

        We only remove:
          - connections where incomingRoad == connectingRoad
          - connections with missing incomingRoad or connectingRoad

        We do NOT delete connections just because the referenced road id is not
        present; that may be handled later by topology repair logic.

        Returns number of connections removed.
        """
        removed = 0
        for j in root.findall("./junction"):
            for conn in list(j.findall("connection")):
                incoming = conn.get("incomingRoad")
                connecting = conn.get("connectingRoad")

                bad = (
                    (incoming is None) or
                    (connecting is None) or
                    (incoming == "") or
                    (connecting == "") or
                    (incoming == connecting)
                )

                if bad:
                    j.remove(conn)
                    removed += 1

        if removed > 0:
            log.info(f"Removed {removed} invalid/self junction connections.")
        return removed

    # ---------- optional SUMO pass ----------

    @staticmethod
    def _sumo_validate(output_path: str) -> bool:
        """
        Optional: run SUMO netconvert as a sanity pass.

        We DO NOT modify the XODR based on SUMO output;
        this is purely a validation step, with logs only.
        """
        if not os.path.exists(SUMO_NETCONVERT):
            log.warning("SUMO not found — skipping SUMO validation.")
            return True

        temp_out = output_path + ".net.xml"
        cmd = [
            SUMO_NETCONVERT,
            "--opendrive", output_path,
            "-o", temp_out,
            "--ignore-errors",
            "--verbose",
            "--opendrive.ignore-widths",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if result.returncode == 0:
                log.info("SUMO validation passed.")
                return True
            tail = "\n".join(result.stderr.splitlines()[-25:])
            log.error("SUMO validation failed.\n" + tail)
            return False
        except Exception as e:
            log.warning(f"SUMO validation skipped due to error: {e}")
            return True
        finally:
            try:
                if os.path.exists(temp_out):
                    os.remove(temp_out)
            except Exception:
                pass

    # ---------- main entrypoint ----------

    @staticmethod
    def sanitize_xodr(input_path: str, output_path: str, run_sumo: bool = False) -> bool:
        """
        Non-destructive sanitization entrypoint.

        Steps:
          1. Parse XML.
          2. Ensure header / geoReference / offset.
          3. For each road:
               - fix lane widths and missing coeffs
               - fix degenerate geometry lengths
          4. Conservatively clean links and junctions.
          5. Write sanitized file.
          6. Optionally run SUMO validation (no modifications based on result).

        Returns True if we successfully wrote output_path.
        """
        log.info(f"🧹 [SAFE] Sanitizing {os.path.basename(input_path)}")

        if not os.path.isfile(input_path):
            log.error(f"Input XODR not found: {input_path}")
            return False

        try:
            tree = ET.parse(input_path)
            root = tree.getroot()
        except Exception as e:
            log.error(f"Failed to parse XML: {e}")
            return False

        # 0) header / geoReference / offset
        XODRSanitizer._ensure_header(root)

        # 1) per-road gentle fixes
        total_width_fixes = 0
        total_geom_fixes = 0

        for road in root.findall("road"):
            rid = road.get("id", "?")

            wfix = XODRSanitizer._fix_lane_widths(road)
            gfix = XODRSanitizer._fix_geometries(road)

            if wfix or gfix:
                log.debug(f"Road {rid}: fixed {wfix} widths, {gfix} geometries.")

            total_width_fixes += wfix
            total_geom_fixes += gfix

        log.info(f"Lane width fixes: {total_width_fixes}, geometry fixes: {total_geom_fixes}")

        # 2) top-level conservative link/junction cleanup
        links_removed = XODRSanitizer._fix_links(root)
        junc_removed = XODRSanitizer._fix_junctions(root)
        log.info(f"Links removed: {links_removed}, junction connections removed: {junc_removed}")

        # 3) write sanitized XODR
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        tree.write(output_path, encoding="utf-8", xml_declaration=True)
        log.info(f"✅ [SAFE] Sanitized file saved → {output_path}")

        # 4) optional SUMO pass (pure validation)
        if run_sumo:
            XODRSanitizer._sumo_validate(output_path)

        return True


# =========================
# SELF-TEST (optional)
# =========================

if __name__ == "__main__":
    from datetime import datetime

    base = os.path.dirname(os.path.abspath(__file__))
    test_in = os.path.join(base, "test_input.xodr")

    if not os.path.exists(test_in):
        print(f"❌ Input file not found for self-test:\n   {test_in}")
        print("   → Place a sample XODR as 'test_input.xodr' next to this script.")
        raise SystemExit(1)

    out_dir = os.path.join(base, "runtime_maps_safe")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    test_out = os.path.join(out_dir, f"sanitized_safe_{ts}.xodr")

    print("🔍 Running SAFE XODR sanitizer self-test…")
    ok = XODRSanitizer.sanitize_xodr(test_in, test_out, run_sumo=False)
    if ok:
        print(f"✅ Done. Safe-sanitized file:\n   → {test_out}")
    else:
        print("❌ Sanitization failed — see logs.")


# ==================
# COMPAT WRAPPER
# ==================
# Backwards compatibility for legacy modules
def _safe_float(value, default=0.0):
    return XODRSanitizer._safe_float(value, default)
