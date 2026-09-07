from __future__ import annotations
import copy
import xml.etree.ElementTree as ET
from .core import RoundaboutModel, choose_geometry_model, detect_candidates, extract_endpoint_anchors, infer_lane_model, sample_road
from .validator import validate_model

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
