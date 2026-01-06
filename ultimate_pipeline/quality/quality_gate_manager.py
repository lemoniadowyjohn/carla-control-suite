# ultimate_pipeline/quality/quality_gate_manager.py

from __future__ import annotations
from typing import Any, Dict, Optional


class QualityGateManager:
    """
    Central registry for all quality gates.
    Writes all results into ValidationReport and exposes failures for LLM review.
    """

    _failures_by_name: Dict[str, Any] = {}

    def __init__(self, vreport, logs_dir: Optional[str] = None) -> None:
        self.vreport = vreport
        self.logs_dir = logs_dir

    # -------------------------------- bookkeeping --------------------------------

    def fail(self, gate_name: str, payload: Any) -> None:
        self.vreport.add("quality_gates", gate_name, {"status": "fail", "detail": payload})
        QualityGateManager._failures_by_name[gate_name] = payload

    def passed(self, gate_name: str) -> None:
        self.vreport.add("quality_gates", gate_name, {"status": "pass"})
        QualityGateManager._failures_by_name.pop(gate_name, None)

    @classmethod
    def get_failures(cls) -> Dict[str, Any]:
        return dict(cls._failures_by_name)

    # -------------------------------- concrete gates --------------------------------

    def gate_xml_integrity(self, xodr_path: str) -> None:
        from ultimate_pipeline.quality.check_xml_integrity import XMLIntegrityChecker
        issues = XMLIntegrityChecker.validate(xodr_path)
        if issues:
            self.fail("xml_integrity", issues)
        else:
            self.passed("xml_integrity")

    def gate_elevation_smoothness(self, root) -> None:
        from ultimate_pipeline.quality.check_elevation_smoothness import ElevationSmoothnessGate
        issues = ElevationSmoothnessGate.validate(root)
        if issues:
            self.fail("elevation_smoothness", issues)
        else:
            self.passed("elevation_smoothness")

    def gate_physics_feasibility(self, root) -> None:
        from ultimate_pipeline.quality.check_physics_feasibility import PhysicsFeasibilityChecker
        issues = PhysicsFeasibilityChecker.validate(root)
        if issues:
            self.fail("physics_feasibility", issues)
        else:
            self.passed("physics_feasibility")

    def gate_randomness_entropy(self, root) -> None:
        from ultimate_pipeline.quality.check_randomness_entropy import RandomnessEntropyMetric
        score = RandomnessEntropyMetric.compute(root)
        if score < 0.05:
            self.fail("randomness_entropy", {"entropy": score})
        else:
            self.passed("randomness_entropy")

    def gate_semantic_overlap(self, root) -> None:
        from ultimate_pipeline.quality.check_semantic_overlap import SemanticOverlapChecker
        issues = SemanticOverlapChecker.validate(root)
        if issues:
            self.fail("semantic_overlap", issues)
        else:
            self.passed("semantic_overlap")

    def gate_collision_mesh(self, root) -> None:
        """
        Optional collision-mesh sanity gate using Shapely.

        - If USE_SHAPELY is False or Shapely is missing, this gate is a no-op pass.
        - If issues are returned, we mark the gate as failed but do NOT abort the pipeline.
        """
        from ultimate_pipeline.quality.collision_mesh import CollisionMeshValidator

        issues = CollisionMeshValidator.validate(root)

        if issues:
            print("\n============== QUALITY GATE: COLLISION MESH ==============")
            print("⚠ Collision mesh gate detected issues:")
            for msg in issues:
                print("   -", msg)
            self.fail("collision_mesh", {"issues": issues})
        else:
            print("\n============== QUALITY GATE: COLLISION MESH ==============")
            print("✓ Collision mesh gate passed (no major polygon issues).")
            self.passed("collision_mesh")


    # ------------------------------- attachments --------------------------------

    def attach_geometry_validator(self, geom_report: Dict[str, Any]) -> None:
        if geom_report:
            self.vreport.add_dict("geometry_validator", geom_report)
