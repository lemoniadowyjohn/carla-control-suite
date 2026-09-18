# ultimate_pipeline/topology/roundabout_rebuilder.py

import xml.etree.ElementTree as ET
from typing import Dict, List, Set, Tuple

from ultimate_pipeline.core.xodr_sanitizer import _safe_float


class RoundaboutRebuilder:
    """
    Detect and tag roundabouts in the XODR network.

    Heuristics:
      * junction with >= 3 connecting roads
      * those roads are all one-way in the same direction
      * roads are short and curved
    We don't aggressively rewrite geometry; we just:
      * tag <road><type type="roundabout"> when detected
      * tag <junction> with attribute isRoundabout="true"
      * return a metadata dict for downstream modules
    """

    @staticmethod
    def _get_road_center_hdg(road: ET.Element) -> float:
        """Approximate average heading to distinguish 'circle-ish' from pure straight roads."""
        geoms = road.findall("./planView/geometry")
        if not geoms:
            return 0.0
        hdgs = [_safe_float(g.get("hdg", "0.0"), 0.0) for g in geoms]
        if not hdgs:
            return 0.0
        return sum(hdgs) / len(hdgs)

    @staticmethod
    def _road_is_short_and_curvy(road: ET.Element) -> bool:
        length = _safe_float(road.get("length", "0.0"), 0.0)
        if length > 80.0:
            return False

        geoms = road.findall("./planView/geometry")
        arc_count = sum(1 for g in geoms if g.find("arc") is not None)

        return arc_count >= 2

    @staticmethod
    def _road_is_one_way(road: ET.Element) -> bool:
        """
        Treat road as one-way if all non-zero lanes are on only one side.
        """
        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            return False

        has_left = False
        has_right = False

        for section in lanes_elem.findall("laneSection"):
            left = section.find("left")
            right = section.find("right")
            if left is not None:
                for lane in left.findall("lane"):
                    lid = lane.get("id")
                    if lid is None:
                        continue
                    if int(lid) != 0 and lane.get("type", "driving") == "driving":
                        has_left = True
            if right is not None:
                for lane in right.findall("lane"):
                    lid = lane.get("id")
                    if lid is None:
                        continue
                    if int(lid) != 0 and lane.get("type", "driving") == "driving":
                        has_right = True

        # one-way if only one side has driving lanes
        return has_left ^ has_right

    @staticmethod
    def detect_roundabouts(root: ET.Element) -> Dict[str, Dict]:
        """
        Return metadata:
        {
          junction_id: {
             "roads": [road_id, ...],
             "center": (x, y),
          },
          ...
        }
        """
        roads: Dict[str, ET.Element] = {
            r.get("id"): r
            for r in root.findall("road")
            if r.get("id") is not None
        }

        roundabout_meta: Dict[str, Dict] = {}

        for junc in root.findall("junction"):
            j_id = junc.get("id", "")
            conns = junc.findall("connection")
            if len(conns) < 3:
                continue  # not enough to be a real roundabout

            road_ids: Set[str] = set()
            for c in conns:
                r_in = c.get("incomingRoad")
                r_con = c.get("connectingRoad")
                if r_in in roads:
                    road_ids.add(r_in)
                if r_con in roads:
                    road_ids.add(r_con)

            if len(road_ids) < 3:
                continue

            # Heuristic: at least 3 short, one-way, curvy roads → likely roundabout core
            candidate_roads = [
                rid for rid in road_ids
                if RoundaboutRebuilder._road_is_short_and_curvy(roads[rid])
                and RoundaboutRebuilder._road_is_one_way(roads[rid])
            ]

            if len(candidate_roads) < 3:
                continue

            # Rough "center": average first geometry coordinates of candidate roads
            xs, ys = [], []
            for rid in candidate_roads:
                geoms = roads[rid].findall("./planView/geometry")
                if not geoms:
                    continue
                g0 = geoms[0]
                xs.append(_safe_float(g0.get("x", "0.0"), 0.0))
                ys.append(_safe_float(g0.get("y", "0.0"), 0.0))

            if not xs or not ys:
                continue

            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)

            roundabout_meta[j_id] = {
                "roads": list(candidate_roads),
                "center": (cx, cy),
            }

        return roundabout_meta

    @staticmethod
    def tag_roundabouts(root: ET.Element) -> Dict[str, Dict]:
        """
        Tag detected roundabouts in-place and return metadata.
        """
        meta = RoundaboutRebuilder.detect_roundabouts(root)

        roads_by_id = {
            r.get("id"): r for r in root.findall("road") if r.get("id") is not None
        }

        for j_id, info in meta.items():
            # Tag junction
            for junc in root.findall("junction"):
                if junc.get("id") == j_id:
                    junc.set("isRoundabout", "true")

            # Tag roads
            for rid in info["roads"]:
                r = roads_by_id.get(rid)
                if r is None:
                    continue
                r_type = r.find("type")
                if r_type is None:
                    r_type = ET.SubElement(r, "type", {"s": "0.0", "type": "roundabout"})
                else:
                    r_type.set("type", "roundabout")

        return meta
