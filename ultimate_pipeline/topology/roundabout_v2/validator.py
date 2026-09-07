from __future__ import annotations

import math
from .core import RoundaboutModel, validate_lane_mapping

def validate_model(model: RoundaboutModel) -> dict:
    failures=[]
    if model.candidate.detection_method in {"AMBIGUOUS","REJECTED"}: failures.append("ambiguous_detection")
    if not model.samples: failures.append("samples_missing")
    if model.circle_fit:
        required=("center_x","center_y","radius","rmse","max_residual")
        if not all(k in model.circle_fit and math.isfinite(float(model.circle_fit[k])) for k in required): failures.append("invalid_circle_fit")
        if float(model.circle_fit.get("radius",0)) <= 0: failures.append("non_positive_radius")
    if model.action.startswith("RECONSTRUCT") and not model.anchors: failures.append("anchors_missing")
    return {"status":"PASS" if not failures else "FAIL","failures":failures}

def validate_elevation_records(records: list[dict]) -> dict:
    failures=[]; previous=None
    for index,record in enumerate(records):
        try: s=float(record["s"]); values=[float(record[k]) for k in "abcd"]
        except (KeyError,TypeError,ValueError): failures.append(f"record_{index}_invalid"); continue
        if not math.isfinite(s) or not all(math.isfinite(x) for x in values): failures.append(f"record_{index}_nonfinite")
        if previous is not None and s <= previous: failures.append(f"record_{index}_nonmonotonic")
        previous=s
    return {"status":"PASS" if not failures else "FAIL","failures":failures}
