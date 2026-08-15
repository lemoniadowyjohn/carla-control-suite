from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Mapping

from ultimate_pipeline.enrichment.lane_width_policy import target_driving_width_m


class LaneRepair:
    """
    Robust, CARLA-stable lane width normalizer.
    """

    @staticmethod
    def _new_width(width: float) -> ET.Element:
        return ET.Element("width", {
            "sOffset": "0.0",
            "a": f"{width:.3f}",
            "b": "0.0",
            "c": "0.0",
            "d": "0.0",
        })

    @staticmethod
    def _sanitize_numeric(elem: ET.Element, key: str, fallback: float) -> float:
        raw = elem.get(key)
        if raw is None:
            return fallback
        try:
            val = float(raw.strip())
        except Exception:
            return fallback
        if val != val:
            return fallback
        if abs(val) > 1e5:
            return fallback
        return val

    @staticmethod
    def standardize_lanes(
        root: ET.Element,
        driving_width: float = 3.5,
        shoulder_width: float = 1.0,
        fallback_width: float = 0.5,
        osm_meta: Mapping[str, Mapping[str, Any]] | None = None,
        max_examples: int = 25,
    ) -> dict:
        print("Starting LaneRepair...")

        DRIVING = {"driving", "parking", "mwyEntry", "mwyExit", "entry", "exit", "onRamp", "offRamp", "stop"}
        SHOULDERS = {"shoulder", "border", "sidewalk", "curb"}
        source_counts: dict[str, int] = {}
        examples: list[dict[str, Any]] = []
        checked = 0
        updated = 0
        missing_added = 0
        six_meter_found = 0

        for road in root.findall("road"):
            rid = road.get("id", "?")
            width_decision = target_driving_width_m(
                road,
                osm_meta=osm_meta,
                fallback_width_m=driving_width,
            )
            source_counted = False
            lanes_elem = road.find("lanes")
            if lanes_elem is None:
                continue

            for section in lanes_elem.findall("laneSection"):

                for side in ("left", "right"):
                    side_elem = section.find(side)
                    if side_elem is None:
                        continue

                    for lane in side_elem.findall("lane"):
                        try:
                            lane_id_str = lane.get("id")
                            if lane_id_str is None:
                                continue

                            try:
                                lane_id_int = int(lane_id_str)
                            except ValueError:
                                lane_id_int = None

                            lane_type = (lane.get("type", "unknown") or "unknown").strip().lower()

                            # never give lane 0 a width on left/right
                            if lane_id_int == 0:
                                for w_extra in list(lane.findall("width")):
                                    lane.remove(w_extra)
                                continue

                            if lane_type in DRIVING:
                                target = width_decision.width_m
                                checked += 1
                                if not source_counted:
                                    source_counts[width_decision.source] = (
                                        source_counts.get(width_decision.source, 0) + 1
                                    )
                                    source_counted = True
                            elif lane_type in SHOULDERS:
                                target = shoulder_width
                            else:
                                for w_extra in list(lane.findall("width")):
                                    lane.remove(w_extra)
                                continue

                            widths = list(lane.findall("width"))

                            for w_extra in widths[1:]:
                                lane.remove(w_extra)

                            if not widths:
                                lane.append(LaneRepair._new_width(target))
                                if lane_type in DRIVING:
                                    missing_added += 1
                                    updated += 1
                                    if len(examples) < max_examples:
                                        examples.append(
                                            {
                                                "road_id": rid,
                                                "lane_id": lane_id_str,
                                                "old_width_m": None,
                                                "new_width_m": target,
                                                "source": width_decision.source,
                                                "highway": width_decision.highway,
                                            }
                                        )
                                print(f"  Road {rid}, Lane {lane_id_str} ({lane_type}): added width={target:.2f}")
                                continue

                            w = widths[0]

                            a = LaneRepair._sanitize_numeric(w, "a", target)
                            original_a = a

                            if lane_type in DRIVING and abs(a) < 0.1:
                                a = target

                            w.set("a", f"{a:.3f}")
                            w.set("b", "0.0")
                            w.set("c", "0.0")
                            w.set("d", "0.0")
                            w.set("sOffset", "0.0")

                            if lane_type in DRIVING:
                                if abs(original_a - 6.0) <= 1e-6:
                                    six_meter_found += 1
                                if abs(original_a - target) > 1e-6:
                                    updated += 1
                                    if len(examples) < max_examples:
                                        examples.append(
                                            {
                                                "road_id": rid,
                                                "lane_id": lane_id_str,
                                                "old_width_m": round(original_a, 3),
                                                "new_width_m": target,
                                                "source": width_decision.source,
                                                "highway": width_decision.highway,
                                            }
                                        )
                                w.set("a", f"{target:.3f}")

                        except Exception as e:
                            print(f"  ⚠️ LaneRepair skipped lane on road {rid}: {e!r}")
                            continue

        print("LaneRepair complete.")
        return {
            "ok": True,
            "totals": {
                "driving_lanes_checked": checked,
                "driving_widths_updated": updated,
                "missing_widths_added": missing_added,
                "six_meter_placeholders_found": six_meter_found,
                "source_counts": source_counts,
            },
            "examples": examples,
        }

    # --- API expected by main_pipeline.py ---

    @staticmethod
    def standardize(
        root: ET.Element,
        osm_meta: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict:
        """Wrapper used by the pipeline."""
        return LaneRepair.standardize_lanes(root, osm_meta=osm_meta)

    @staticmethod
    def enforce_width_continuity(root: ET.Element):
        """
        For now, this can be a no-op or a future extension.
        MeshContinuityRepairer.fix_lane_widths already fixes width continuity.
        """
        # You can leave this empty, or later implement advanced continuity logic.
        return
