class SemanticOverlapChecker:

    @staticmethod
    def check(buildings, roads):
        overlaps = []
        for b in buildings:
            for r in roads:
                if b.polygon.intersects(r.polygon):
                    overlaps.append({"building": b.id, "road": r.id})
        return overlaps

    @staticmethod
    def _driving_extent_per_side(road):
        """Cumulative driving-lane width from centerline outward, per side.

        Real OpenDRIVE roads are frequently asymmetric (e.g. one driving lane
        on the right, only a sidewalk on the left, as confirmed on the pinned
        map's road 42464) -- buffering the centerline symmetrically by "the
        max driving-lane width" extends the polygon onto a side that may have
        no driving lane at all, producing false-positive building overlaps
        for anything sitting near the road's non-driving side. Takes the max
        per-side extent across laneSections (a road's width can vary along
        its length; this keeps the same "conservative single width" scope
        the previous symmetric version used, just correctly split by side).
        """
        left_extent = 0.0
        right_extent = 0.0
        for section in road.findall(".//lanes/laneSection"):
            for side_name, sign in (("left", 1), ("right", -1)):
                side_el = section.find(side_name)
                if side_el is None:
                    continue
                lanes = sorted(
                    side_el.findall("lane"),
                    key=lambda lane: abs(int(lane.get("id", 0))),
                )
                cumulative = 0.0
                last_driving_extent = 0.0
                for lane in lanes:
                    width_el = lane.find("width")
                    try:
                        lane_width = float(width_el.get("a")) if width_el is not None else 0.0
                    except (TypeError, ValueError):
                        lane_width = 0.0
                    cumulative += lane_width
                    if lane.get("type") == "driving":
                        last_driving_extent = cumulative
                if sign > 0:
                    left_extent = max(left_extent, last_driving_extent)
                else:
                    right_extent = max(right_extent, last_driving_extent)
        return left_extent, right_extent

    @staticmethod
    def check_xodr(root):
        """Adapt XODR objects to the real polygon-intersection checker.

        Buildings with explicit global outline corners are preferred. Roads
        are represented by their plan-view reference line buffered
        asymmetrically by the real per-side driving-lane extent (see
        _driving_extent_per_side) -- not a symmetric buffer, which would
        extend the road polygon onto a side with no driving lane at all.
        Missing geometry is skipped and reported by the caller as incomplete
        input rather than guessed.
        """
        from types import SimpleNamespace
        try:
            from shapely.geometry import LineString, Polygon
            from shapely.ops import unary_union
        except ImportError:
            return [{"type":"dependency_missing", "dependency":"shapely"}]
        buildings=[]; roads=[]
        for road in root.findall("road"):
            points=[]
            for geometry in road.findall("./planView/geometry"):
                try:
                    points.append((float(geometry.get("x")), float(geometry.get("y"))))
                except (TypeError, ValueError):
                    continue
            if len(points) >= 2:
                line = LineString(points)
                left_extent, right_extent = SemanticOverlapChecker._driving_extent_per_side(road)
                min_extent = 0.25  # keep a road with zero driving-lane data from vanishing to a bare line
                pieces = []
                if left_extent > 0:
                    pieces.append(line.buffer(left_extent, single_sided=True))
                if right_extent > 0:
                    pieces.append(line.buffer(-right_extent, single_sided=True))
                if not pieces:
                    pieces.append(line.buffer(min_extent))
                polygon = unary_union(pieces)
                roads.append(SimpleNamespace(id=road.get("id","UNKNOWN"), polygon=polygon))
        for object_node in root.findall(".//object[@type='building']"):
            corners=[]
            for corner in object_node.findall("./outline/cornerGlobal"):
                try: corners.append((float(corner.get("x")),float(corner.get("y"))))
                except (TypeError, ValueError): pass
            if len(corners) >= 3:
                buildings.append(SimpleNamespace(id=object_node.get("id","UNKNOWN"), polygon=Polygon(corners)))
        return SemanticOverlapChecker.check(buildings, roads)
