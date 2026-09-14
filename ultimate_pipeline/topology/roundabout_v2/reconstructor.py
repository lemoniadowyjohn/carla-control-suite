from __future__ import annotations
import copy
import xml.etree.ElementTree as ET
from .core import Anchor, Candidate, RoundaboutModel, choose_geometry_model, detect_candidates, extract_endpoint_anchors, infer_lane_model, sample_road
from .validator import validate_model, validate_segmented_ring
from .ring import build_segment_roads, build_segment_specs

class RoundaboutV2Reconstructor:
    """Opt-in V2 analysis and transactional candidate materializer.

    The supplied tree is never modified.  Materialized ring roads are added to
    a private clone only after the per-candidate validator accepts them.  This
    remains an offline candidate facility; no pipeline stage invokes it.
    """

    def __init__(self, *, circle_rmse_threshold: float = 0.75, sample_spacing_m: float = 1.0):
        if circle_rmse_threshold <= 0 or sample_spacing_m <= 0: raise ValueError("V2 parameters must be positive")
        self.circle_rmse_threshold=circle_rmse_threshold; self.sample_spacing_m=sample_spacing_m

    def analyze(self, root: ET.Element, *, osm_path: str | None = None,
                candidates: list[Candidate] | None = None) -> list[RoundaboutModel]:
        roads={r.get("id"):r for r in root.findall("road") if r.get("id")}; out=[]
        for candidate in candidates if candidates is not None else detect_candidates(root, osm_path=osm_path):
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

    @staticmethod
    def _candidate_anchors(root: ET.Element, candidate: Candidate) -> list[Anchor]:
        """Extract stable, physically distinct approach anchors for a candidate.

        One OSM roundabout can span more than one OpenDRIVE junction.  The V1
        analysis only inspected the first junction, and can therefore receive
        duplicate connections for the same approach endpoint.  A duplicate
        pose is not a second ring split: retain one deterministic anchor when
        all geometric and lane facts agree, otherwise fail closed.
        """
        anchors: list[Anchor] = []
        ring_road_ids = set(candidate.road_ids)
        for junction_id in candidate.junction_ids:
            junction = root.find(f"./junction[@id='{junction_id}']")
            if junction is not None:
                anchors.extend(extract_endpoint_anchors(root, junction, ring_road_ids))

        unique: dict[tuple[str, str, float, float], Anchor] = {}
        for anchor in sorted(
            anchors,
            key=lambda item: (item.road_id, item.endpoint, item.x, item.y, item.anchor_id),
        ):
            key = (anchor.road_id, anchor.endpoint, round(anchor.x, 9), round(anchor.y, 9))
            existing = unique.get(key)
            if existing is None:
                unique[key] = anchor
                continue
            if (
                existing.lane_ids != anchor.lane_ids
                or abs(existing.heading - anchor.heading) > 1e-9
                or existing.z != anchor.z
            ):
                raise ValueError("conflicting duplicate approach anchors")

        return sorted(unique.values(), key=lambda item: item.anchor_id)

    @staticmethod
    def _first_available_road_id(root: ET.Element) -> int:
        """Return a deterministic numeric road ID beyond every existing one."""
        existing = {road.get("id", "") for road in root.findall("road")}
        numeric_ids = [int(road_id) for road_id in existing if road_id.isdecimal()]
        next_id = max(numeric_ids, default=0) + 1
        while str(next_id) in existing:
            next_id += 1
        return next_id

    def reconstruct_transactional(self, root: ET.Element, *, osm_path: str | None = None,
                                  candidates: list[Candidate] | None = None) -> tuple[ET.Element,list[dict]]:
        """Materialize valid geometry candidates into one private map clone.

        A failed ring leaves the accumulated clone unchanged, so an ambiguous
        or invalid candidate never prevents independent candidates from being
        evaluated.  Source roads and junctions are intentionally retained:
        V2 does not claim to have completed attachment/lane-link migration.
        """
        clone=copy.deepcopy(root); diagnostics=[]
        next_road_id=self._first_available_road_id(clone)
        for model in self.analyze(clone, osm_path=osm_path, candidates=candidates):
            record={"junction_ids":model.candidate.junction_ids,"action":model.action,"geometry_kind":model.geometry_kind,"circle_fit":model.circle_fit,"validation":validate_model(model)}
            if model.action != "RECONSTRUCT_GEOMETRY":
                record["materialization"]={"status":"NOT_APPLICABLE","reason":f"model_action:{model.action}"}
                diagnostics.append(record)
                continue

            try:
                materialization_anchors = self._candidate_anchors(clone, model.candidate)
                record["materialization_anchor_count"] = len(materialization_anchors)
                candidate_clone, result = self.reconstruct_ring_transactional(
                    clone,
                    junction_id=model.candidate.junction_ids[0],
                    anchors=materialization_anchors,
                    first_road_id=next_road_id,
                    z_start=next((anchor.z for anchor in materialization_anchors if anchor.z is not None), 0.0),
                )
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                result = {"status":"PRESERVE_ORIGINAL", "reason":str(exc)}
                candidate_clone = clone
            record["materialization"] = result
            if result.get("status") == "PASS":
                clone = candidate_clone
                next_road_id = self._first_available_road_id(clone)
            diagnostics.append(record)
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
