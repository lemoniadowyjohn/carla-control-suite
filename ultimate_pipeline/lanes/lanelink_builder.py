from __future__ import annotations

import xml.etree.ElementTree as ET
import math
from typing import Dict, List, Tuple, Optional
from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint, pose_at_s


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
    - NO fallback pairing: an incoming driving lane whose (side, order) has no
      connector driving lane is left unlinked, never cross-sign or cross-edge
      guessed (GAP-048 policy; ambiguous forges stay unlinked).
    - Failure modes are classified and counted in ``last_failure_report``
      (see ``_classify_lane_failures``) so generator deficiencies are
      observable instead of silent.
    """

    DRIVING_TYPES = {"driving"}

    #: aggregated output of the last regenerate_lane_links call:
    #: {"summary": {reason: n, ...}, "records": [ ... up to 500 ... ],
    #:  "connections_total": n, "lane_links_emitted": n}
    last_failure_report: Dict[str, object] = {}

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
            if at_start:
                return secs[0]
            # Degenerate-terminal filter: a laneSection anchored exactly at the
            # road's end (s == length) has zero length and carries no
            # interface lanes; the real terminal face is the last section
            # with nonzero extent BEFORE the boundary.
            road = roads.get(road_id)
            len_m = _safe_float(road.get("length")) if road is not None else 0.0
            if len_m > 0.0:
                cand = [
                    s for s in secs
                    if _safe_float(s.get("s"), 0.0) < len_m - 1e-9
                ]
                if cand:
                    return cand[-1]
            return secs[-1]

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
        failure_counts: Dict[str, int] = {}
        failure_records: List[Dict[str, object]] = []

        def _note_failure(reason: str, record: Dict[str, object]) -> None:
            failure_counts[reason] = failure_counts.get(reason, 0) + 1
            if len(failure_records) < 500:
                failure_records.append({"reason": reason, **record})

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
                    _note_failure(
                        "CONNECTOR_MISSING_INTERFACE_SECTION"
                        if con_sec is None else "INCOMING_MISSING_EDGE_SECTION",
                        {"junction_id": junc_id, "incoming": incoming,
                         "connecting": connecting, "contact_point": point},
                    )
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
                emitted_from: set[int] = set()
                emitted_to: set[int] = set()
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
                    emitted_from.add(from_id)
                    emitted_to.add(to_id)

                    count += 1

                # ---------- failure-mode classification (no fallback) ----------
                # Every incoming driving lane that ends this connection with no
                # laneLink is classified; leftover connector driving lanes are
                # classified too. Nothing is re-paired across sides/signs.
                con_widthless_left = {
                    lid for lid, el in con_left.items() if not el.findall("width")
                }
                con_widthless_right = {
                    lid for lid, el in con_right.items() if not el.findall("width")
                }
                for side, inc_lanes, con_lanes, con_widthless in (
                    ("right", in_right, con_right, con_widthless_right),
                    ("left", in_left, con_left, con_widthless_left),
                ):
                    for lid, lane_el in inc_lanes.items():
                        if lid in emitted_from:
                            continue
                        if not lane_el.findall("width"):
                            _note_failure("INCOMING_LANE_NO_WIDTH", {
                                "junction_id": junc_id, "incoming": incoming,
                                "connecting": connecting, "lane_id": lid, "side": side,
                            })
                            continue
                        paired_side = [
                            (i, c) for i, c in right_pairs + left_pairs
                            if (i in inc_lanes) and i == lid
                        ]
                        if not paired_side:
                            if not con_lanes:
                                _note_failure("CONNECTOR_SIDE_NO_DRIVING_LANES", {
                                    "junction_id": junc_id, "incoming": incoming,
                                    "connecting": connecting, "lane_id": lid, "side": side,
                                })
                            elif con_widthless.intersection(con_lanes) and not (
                                con_lanes.keys() - con_widthless
                            ):
                                _note_failure("CONNECTOR_LANE_NO_WIDTH", {
                                    "junction_id": junc_id, "incoming": incoming,
                                    "connecting": connecting, "lane_id": lid, "side": side,
                                })
                            else:
                                _note_failure("COUNT_MISMATCH_INNER_FIRST_EXHAUSTED", {
                                    "junction_id": junc_id, "incoming": incoming,
                                    "connecting": connecting, "lane_id": lid, "side": side,
                                    "incoming_lanes": sorted(inc_lanes),
                                    "connector_lanes": sorted(con_lanes),
                                })

                total_links += count
                conn_count += 1

                if verbose:
                    print(f"   ✓ Junction {junc_id}: {incoming}->{connecting} → {count} laneLinks")

        if verbose:
            print(f"✅ LaneLinkBuilder: {total_links} laneLinks across {conn_count} connections.")
            if failure_counts:
                print(
                    "⚠️ unlinked driving-lane failure modes (no fallback pairing): "
                    + ", ".join(f"{k}={v}" for k, v in sorted(failure_counts.items()))
                )

        LaneLinkBuilder.last_failure_report = {
            "connections_total": conn_count,
            "lane_links_emitted": total_links,
            "summary": dict(failure_counts),
            "records": failure_records,
        }

    # ⭐⭐ THE WRAPPER THE PIPELINE EXPECTS ⭐⭐
    @staticmethod
    def regenerate(root: ET.Element, verbose: bool = True) -> None:
        LaneLinkBuilder.regenerate_lane_links(root, verbose=verbose)

    @staticmethod
    def prune_outer_to_inner_mispaired_lane_links(
        root: ET.Element, verbose: bool = False
    ) -> dict:
        """GAP-026 Stage-8 guard: remove severe outer->inner mispairings.

        For each connection, recompute the canonical inner-first pairing
        (same logic as ``match_by_direction``) and remove existing
        ``laneLink`` entries where ``abs(from) != abs(to)`` that disagree
        with it.  Removed outer lanes become explicit residuals (unlinked),
        never re-guessed.  Equal-order links are always kept (width repair
        in Stage 7 handles those).  No threshold is modified.
        """
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}

        def _safe_float(x, default: float = 0.0) -> float:
            try:
                return float(str(x).strip())
            except Exception:
                return default

        lane_sections: dict = {}
        for rid, road in roads.items():
            sections = list(road.findall("./lanes/laneSection"))
            sections.sort(key=lambda s: _safe_float(s.get("s"), 0.0))
            lane_sections[rid] = sections

        def edge_section(road_id: str, at_start: bool):
            secs = lane_sections.get(road_id)
            if not secs:
                return None
            return secs[0] if at_start else secs[-1]

        def driving_ids(section, side: str) -> list[int]:
            side_elem = section.find(side)
            if side_elem is None:
                return []
            out: list[int] = []
            for lane in side_elem.findall("lane"):
                try:
                    lid = int(str(lane.get("id")))
                except (TypeError, ValueError):
                    continue
                if str(lane.get("type", "driving")).lower() != "driving":
                    continue
                out.append(lid)
            return out

        pruned = 0
        kept = 0
        residuals: list[dict] = []
        for junc in root.findall("junction"):
            for conn in junc.findall("connection"):
                incoming = conn.get("incomingRoad")
                connecting = conn.get("connectingRoad")
                if incoming not in roads or connecting not in roads:
                    continue
                at_start = conn.get("contactPoint", "start") != "end"
                inc_sec = edge_section(incoming, False)
                con_sec = edge_section(connecting, at_start)
                if inc_sec is None or con_sec is None:
                    continue
                canonical: set[tuple[int, int]] = set()
                for side in ("left", "right"):
                    inc_ids = sorted(driving_ids(inc_sec, side), key=abs)
                    con_ids = sorted(driving_ids(con_sec, side), key=abs)
                    # inner-first truncation: zip pairs only equal-order ids
                    for i_id, c_id in zip(inc_ids, con_ids):
                        if (i_id > 0) == (c_id > 0) and abs(i_id) == abs(c_id):
                            canonical.add((i_id, c_id))
                        elif (i_id > 0) == (c_id > 0):
                            # count-mismatch inner pairing (e.g. -1->-1 kept
                            # even when incoming has extra outer lanes)
                            if abs(i_id) == abs(c_id):
                                canonical.add((i_id, c_id))
                            else:
                                canonical.add((i_id, c_id))
                for ll in list(conn.findall("laneLink")):
                    try:
                        pair = (int(str(ll.get("from"))), int(str(ll.get("to"))))
                    except (TypeError, ValueError):
                        continue
                    if pair in canonical:
                        kept += 1
                        continue
                    # Mispair signature: different |id| (outer->inner).
                    if abs(pair[0]) != abs(pair[1]):
                        conn.remove(ll)
                        pruned += 1
                        residuals.append(
                            {
                                "junction_id": junc.get("id"),
                                "connection_id": conn.get("id"),
                                "from": str(pair[0]),
                                "to": str(pair[1]),
                            }
                        )
                    else:
                        kept += 1
        if verbose:
            print(
                f"[LaneLinkBuilder] pruned {pruned} outer->inner mispairs, kept {kept}."
            )
        return {"pruned": pruned, "kept": kept, "residuals": residuals}

    @staticmethod
    def sanitize_junction_lane_links(root: ET.Element, label: str = "unlabeled", *args, **kwargs) -> dict:
        """Validate lane-link existence and endpoint pose continuity."""
        position_tolerance = float(kwargs.get("position_tolerance_m", 0.25))
        heading_tolerance = float(kwargs.get("heading_tolerance_rad", math.radians(12.0)))
        roads = {str(r.get("id")): r for r in root.findall("road") if r.get("id")}
        checked = passed = failed = 0
        failures: List[dict] = []

        def edge_pose(road: ET.Element, at_start: bool) -> Optional[tuple[float, float, float]]:
            geoms = sorted(road.findall("./planView/geometry"), key=lambda g: float(g.get("s", 0)))
            if not geoms:
                return None
            try:
                p = pose_at_s(geoms[0], 0.0) if at_start else endpoint(geoms[-1])
                heading = p.heading if at_start else p.heading
                return float(p.x), float(p.y), float(heading)
            except (TypeError, ValueError, ZeroDivisionError):
                return None

        def lane_pose(road: ET.Element, lane_id: int, at_start: bool) -> Optional[tuple[float, float, float]]:
            base = edge_pose(road, at_start)
            if base is None:
                return None
            sections = sorted(road.findall("./lanes/laneSection"), key=lambda s: float(s.get("s", 0)))
            if not sections:
                return None
            section = sections[0] if at_start else sections[-1]
            side = section.find("./left" if lane_id > 0 else "./right")
            if side is None:
                return None
            lanes = sorted((lane for lane in side.findall("lane") if lane.get("type", "driving") == "driving"), key=lambda l: abs(int(l.get("id", 0))))
            selected = next((lane for lane in lanes if int(lane.get("id", 0)) == lane_id), None)
            if selected is None:
                return None
            width = selected.find("./width")
            if width is None:
                return None
            lane_width = float(width.get("a", "nan"))
            if not math.isfinite(lane_width) or lane_width <= 0:
                return None
            preceding_width = 0.0
            for lane in lanes:
                if abs(int(lane.get("id", 0))) >= abs(lane_id):
                    continue
                preceding = lane.find("./width")
                if preceding is not None:
                    preceding_width += float(preceding.get("a", "0"))
            lateral = (preceding_width + lane_width / 2.0) * (1 if lane_id > 0 else -1)
            x, y, heading = base
            return x - math.sin(heading) * lateral, y + math.cos(heading) * lateral, heading

        for junction in root.findall("junction"):
            for connection in junction.findall("connection"):
                incoming = roads.get(str(connection.get("incomingRoad")))
                connecting = roads.get(str(connection.get("connectingRoad")))
                at_start = connection.get("contactPoint", "start") != "end"
                if incoming is None or connecting is None:
                    continue
                for lane_link in connection.findall("laneLink"):
                    checked += 1
                    try:
                        source = lane_pose(incoming, int(lane_link.get("from")), False)
                        target = lane_pose(connecting, int(lane_link.get("to")), at_start)
                    except (TypeError, ValueError):
                        source = target = None
                    heading_target = None if target is None else target[2] + (0 if at_start else math.pi)
                    valid = source is not None and target is not None and math.hypot(source[0] - target[0], source[1] - target[1]) <= position_tolerance and abs((source[2] - heading_target + math.pi) % (2 * math.pi) - math.pi) <= heading_tolerance
                    if valid:
                        passed += 1
                    else:
                        failed += 1
                        failures.append({"junction_id": junction.get("id"), "connection_id": connection.get("id"), "from": lane_link.get("from"), "to": lane_link.get("to")})
        return {"status": "ok" if failed == 0 else "fail", "label": label, "summary_metrics": {"checked": checked, "passed": passed, "failed": failed}, "failures": failures}
