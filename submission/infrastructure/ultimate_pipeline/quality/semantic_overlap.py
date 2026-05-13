class SemanticOverlapChecker:

    @staticmethod
    def check(buildings, roads):
        overlaps = []
        for b in buildings:
            for r in roads:
                if b.polygon.intersects(r.polygon):
                    overlaps.append({"building": b.id, "road": r.id})
        return overlaps
