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
    def check_xodr(root):
        """Adapt XODR objects to the real polygon-intersection checker.

        Buildings with explicit global outline corners are preferred. Roads are
        represented by their plan-view reference line buffered by the maximum
        driving-lane width available on that road. Missing geometry is skipped
        and reported by the caller as incomplete input rather than guessed.
        """
        from types import SimpleNamespace
        try:
            from shapely.geometry import LineString, Polygon
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
                width=0.5
                for lane in road.findall(".//lane[@type='driving']"):
                    try: width=max(width,float(lane.find("width").get("a")))
                    except (AttributeError, TypeError, ValueError): pass
                roads.append(SimpleNamespace(id=road.get("id","UNKNOWN"), polygon=LineString(points).buffer(width)))
        for object_node in root.findall(".//object[@type='building']"):
            corners=[]
            for corner in object_node.findall("./outline/cornerGlobal"):
                try: corners.append((float(corner.get("x")),float(corner.get("y"))))
                except (TypeError, ValueError): pass
            if len(corners) >= 3:
                buildings.append(SimpleNamespace(id=object_node.get("id","UNKNOWN"), polygon=Polygon(corners)))
        return SemanticOverlapChecker.check(buildings, roads)
