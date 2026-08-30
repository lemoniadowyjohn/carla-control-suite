from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Optional


class LaneLinkBuilder:
    """
    A robust, CARLA-safe laneLink generator.

    Key principles:
    - Only rebuild laneLinks INSIDE <junction>.
    - Never touch non-junction roads.
    - Match lanes by:
        * side (left/right)
        * |id| ordering (inner first)
        * direction (positive to positive, negative to negative)
    - Only 'driving' lanes are linked.
    """

    DRIVING_TYPES = {"driving"}

    @staticmethod
    def regenerate_lane_links(root: ET.Element, verbose: bool = True) -> None:

        def _safe_float(x: str | None, default: float = 0.0) -> float:
            try:
                if x is None:
                    return default
                return float(str(x).strip())
            except Exception:
                return default

        # ---------- PREP: Build Road Index ----------
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
        if verbose:
            print("🔁 Rebuilding junction laneLinks...")

        # road_id → sorted list of laneSections
        lane_sections = {}
        for rid, road in roads.items():
            sections = list(road.findall("./lanes/laneSection"))
            sections.sort(key=lambda s: _safe_float(s.get("s"), 0.0))
            lane_sections[rid] = sections

        def get_edge_section(road_id: str, at_start: bool) -> Optional[ET.Element]:
            secs = lane_sections.get(road_id)
            if not secs:
                return None
            return secs[0] if at_start else secs[-1]

        # ---------- Lane extraction helpers ----------

        def extract_lanes(section: ET.Element, side: str) -> Dict[int, ET.Element]:
            """Return only driving lanes: {id: elem}."""
            side_elem = section.find(side)
            if side_elem is None:
                return {}

            out: Dict[int, ET.Element] = {}
            for lane in side_elem.findall("lane"):
                lane_id_str = lane.get("id")
                if lane_id_str is None:
                    continue

                try:
                    lane_id = int(lane_id_str)
                except ValueError:
                    continue

                lane_type = lane.get("type", "driving").lower()
                if lane_type not in LaneLinkBuilder.DRIVING_TYPES:
                    continue

                out[lane_id] = lane

            return out


        def ordered_ids(ids: List[int]) -> List[int]:
            """Sort by distance from center: -1, -2, +1, +2."""
            return sorted(ids, key=lambda x: abs(x))

        def match_by_direction(inc_ids: List[int], con_ids: List[int]) -> List[Tuple[int, int]]:
            """
            Match lanes by side + sign:
              - positive → positive
              - negative → negative
            Inner lanes first (|id| small → closer to center).
            """

            # separate by sign
            inc_pos = sorted([i for i in inc_ids if i > 0], key=abs)
            con_pos = sorted([c for c in con_ids if c > 0], key=abs)

            inc_neg = sorted([i for i in inc_ids if i < 0], key=abs)
            con_neg = sorted([c for c in con_ids if c < 0], key=abs)

            pairs: List[Tuple[int, int]] = []

            # match positive-positive
            for i_id, c_id in zip(inc_pos, con_pos):
                pairs.append((i_id, c_id))

            # match negative-negative
            for i_id, c_id in zip(inc_neg, con_neg):
                pairs.append((i_id, c_id))

            return pairs


        # ---------- MAIN LOOP ----------
        total_links = 0
        conn_count = 0

        for junc in root.findall("junction"):
            junc_id = junc.get("id", "?")

            for conn in junc.findall("connection"):
                incoming = conn.get("incomingRoad")
                connecting = conn.get("connectingRoad")
                point = conn.get("contactPoint", "start")

                if incoming not in roads or connecting not in roads:
                    if verbose:
                        print(f"⚠️ Junction {junc_id}: invalid road reference.")
                    continue

                # wipe old laneLinks
                for ll in list(conn.findall("laneLink")):
                    conn.remove(ll)

                # incoming road always uses END (OpenDRIVE junction semantics)
                inc_sec = get_edge_section(incoming, at_start=False)

                # connecting road obeys contactPoint
                if point == "end":
                    con_sec = get_edge_section(connecting, at_start=False)
                else:
                    con_sec = get_edge_section(connecting, at_start=True)

                if inc_sec is None or con_sec is None:
                    if verbose:
                        print(f"⚠️ Junction {junc_id}, conn {incoming}->{connecting}: missing laneSections.")
                    continue

                # extract driving lanes
                in_left = extract_lanes(inc_sec, "left")
                in_right = extract_lanes(inc_sec, "right")
                con_left = extract_lanes(con_sec, "left")
                con_right = extract_lanes(con_sec, "right")

                # pair right/right & left/left
                right_pairs = match_by_direction(list(in_right.keys()), list(con_right.keys()))
                left_pairs = match_by_direction(list(in_left.keys()), list(con_left.keys()))

                count = 0
                for from_id, to_id in right_pairs + left_pairs:
                    from_lane = in_right.get(from_id)
                    if from_lane is None:
                        from_lane = in_left.get(from_id)
                    to_lane = con_right.get(to_id)
                    if to_lane is None:
                        to_lane = con_left.get(to_id)

                    if from_lane is None or to_lane is None:
                        continue

                    # skip lanes without width or non-driving types
                    if not from_lane.findall("width"):
                        continue
                    if not to_lane.findall("width"):
                        continue
                    # by here, both lanes are known driving + have width
                    ET.SubElement(conn, "laneLink", {
                        "from": str(from_id),
                        "to": str(to_id),
                    })

                    count += 1

                total_links += count
                conn_count += 1

                if verbose:
                    print(f"   ✓ Junction {junc_id}: {incoming}->{connecting} → {count} laneLinks")

        if verbose:
            print(f"✅ LaneLinkBuilder: {total_links} laneLinks across {conn_count} connections.")

    # ⭐⭐ THE WRAPPER THE PIPELINE EXPECTS ⭐⭐
    @staticmethod
    def regenerate(root: ET.Element, verbose: bool = True) -> None:
        LaneLinkBuilder.regenerate_lane_links(root, verbose=verbose)

    @staticmethod
    def sanitize_junction_lane_links(root: ET.Element, label: str = "unlabeled", *args, **kwargs) -> dict:
        """Stub for laneLink sanity check."""
        print(f"   [INFO] LaneLink Sanity Check: {label} (STUB)")
        return {"status": "ok", "summary_metrics": {}}