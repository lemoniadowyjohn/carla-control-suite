from __future__ import annotations

import xml.etree.ElementTree as ET


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
    ):
        print("Starting LaneRepair...")

        DRIVING = {"driving", "parking", "mwyEntry", "mwyExit", "entry", "exit", "onRamp", "offRamp", "stop"}
        SHOULDERS = {"shoulder", "border", "sidewalk", "curb"}

        for road in root.findall("road"):
            rid = road.get("id", "?")
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
                                target = driving_width
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
                                print(f"  Road {rid}, Lane {lane_id_str} ({lane_type}): added width={target:.2f}")
                                continue

                            w = widths[0]

                            a = LaneRepair._sanitize_numeric(w, "a", target)

                            if lane_type in DRIVING and abs(a) < 0.1:
                                a = driving_width

                            w.set("a", f"{a:.3f}")
                            w.set("b", "0.0")
                            w.set("c", "0.0")
                            w.set("d", "0.0")
                            w.set("sOffset", "0.0")

                            if lane_type in DRIVING:
                                w.set("a", f"{driving_width:.3f}")

                        except Exception as e:
                            print(f"  ⚠️ LaneRepair skipped lane on road {rid}: {e!r}")
                            continue

        print("LaneRepair complete.")

    # --- API expected by main_pipeline.py ---

    @staticmethod
    def standardize(root: ET.Element):
        """Wrapper used by the pipeline."""
        LaneRepair.standardize_lanes(root)

    @staticmethod
    def enforce_width_continuity(root: ET.Element):
        """
        For now, this can be a no-op or a future extension.
        MeshContinuityRepairer.fix_lane_widths already fixes width continuity.
        """
        # You can leave this empty, or later implement advanced continuity logic.
        return
