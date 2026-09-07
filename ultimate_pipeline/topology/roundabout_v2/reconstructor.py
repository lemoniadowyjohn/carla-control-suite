from __future__ import annotations
import copy
import xml.etree.ElementTree as ET
from .core import RoundaboutModel, choose_geometry_model, detect_candidates, extract_endpoint_anchors, infer_lane_model, sample_road
from .validator import validate_model, validate_segmented_ring
from .ring import build_segment_roads, build_segment_specs

class RoundaboutV2Reconstructor:
    """Opt-in analysis candidate. It never mutates the supplied XML root."""

    def __init__(self, *, circle_rmse_threshold: float = 0.75, sample_spacing_m: float = 1.0):
        if circle_rmse_threshold <= 0 or sample_spacing_m <= 0: raise ValueError("V2 parameters must be positive")
        self.circle_rmse_threshold=circle_rmse_threshold; self.sample_spacing_m=sample_spacing_m

    def analyze(self, root: ET.Element) -> list[RoundaboutModel]:
        roads={r.get("id"):r for r in root.findall("road") if r.get("id")}; out=[]
        for candidate in detect_candidates(root):
            model=RoundaboutModel(candidate)
            try:
                model.samples=[p for rid in candidate.road_ids for p in sample_road(roads[rid],self.sample_spacing_m)]
                junction=root.find(f"./junction[@id='{candidate.junction_ids[0]}']")
                model.anchors=extract_endpoint_anchors(root,junction,set(candidate.road_ids)) if junction is not None else []
                model.geometry_kind,model.circle_fit=choose_geometry_model(model.samples,self.circle_rmse_threshold)
                lane_ids,provenance=infer_lane_model([roads[r] for r in candidate.road_ids])
                model.action="PRESERVED_VALID" if model.geometry_kind != "CIRCLE_FIT" else "RECONSTRUCT_GEOMETRY"
                if candidate.detection_method == "HEURISTIC": model.action="REJECT_AMBIGUOUS"
                if not lane_ids or any(float(x["confidence"]) < 0 for x in provenance): model.action="PRESERVE_ORIGINAL"
            except (KeyError,TypeError,ValueError) as exc:
                model.action="PRESERVE_ORIGINAL"; model.geometry_kind=f"REJECTED:{type(exc).__name__}"
            validation=validate_model(model)
            if validation["status"] != "PASS" and model.action.startswith("RECONSTRUCT"): model.action="PRESERVE_ORIGINAL"
            out.append(model)
        return out

    def reconstruct_transactional(self, root: ET.Element) -> tuple[ET.Element,list[dict]]:
        clone=copy.deepcopy(root); diagnostics=[]
        for model in self.analyze(clone):
            diagnostics.append({"junction_ids":model.candidate.junction_ids,"action":model.action,"geometry_kind":model.geometry_kind,"circle_fit":model.circle_fit,"validation":validate_model(model)})
        return clone,diagnostics

    def reconstruct_ring_transactional(self, root: ET.Element, *, junction_id: str,
                                       anchors, first_road_id: int,
                                       z_start: float = 0.0) -> tuple[ET.Element, dict]:
        """Build a segmented ring on a clone and commit it only after validation.

        This low-level API deliberately requires caller-supplied, source-backed
        anchors.  It does not delete source roads or rewrite unrelated junctions.
        """
        if len(anchors) < 3:
            return root, {"status":"PRESERVE_ORIGINAL", "reason":"fewer_than_three_anchors"}
        points = [(a.x, a.y) for a in anchors]
        center_x = sum(x for x, _ in points) / len(points)
        center_y = sum(y for _, y in points) / len(points)
        try:
            specs = build_segment_specs(list(anchors), center_x, center_y, int(first_road_id))
            roads = build_segment_roads(specs, junction_id, z_start=z_start)
            validation = validate_segmented_ring(roads)
            if validation["status"] != "PASS":
                return root, {"status":"PRESERVE_ORIGINAL", "reason":";".join(validation["failures"])}
            clone = copy.deepcopy(root)
            existing = {r.get("id") for r in clone.findall("road")}
            if any(r.get("id") in existing for r in roads):
                raise ValueError("generated road id already exists")
            for road in roads:
                clone.append(road)
            return clone, {"status":"PASS", "action":"RECONSTRUCT_SEGMENTED_RING",
                           "road_ids":[r.get("id") for r in roads],
                           "source_road_ids":sorted({a.road_id for a in anchors}),
                           "validation":validation}
        except (TypeError, ValueError, OverflowError) as exc:
            return root, {"status":"PRESERVE_ORIGINAL", "reason":str(exc)}
