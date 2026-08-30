# ultimate_pipeline/quality/quality_gate_manager.py
from __future__ import annotations

from typing import Any, Dict, Optional


class QualityGateManager:
    """Central registry for quality gates.

    Notes
    -----
    - Gates should be safe: reporting must never crash the pipeline.
    - Some gates accept an XML root Element, others accept a .xodr path.
      For path-based gates we enforce type checks to prevent accidental misuse.
    """

    def __init__(self, vreport, logs_dir: Optional[str] = None) -> None:
        self.vreport = vreport
        self.logs_dir = logs_dir
        # Instance-scoped failures (avoid leaking failures between runs/instances).
        self._failures_by_name: Dict[str, Any] = {}

    # -------------------------------- bookkeeping --------------------------------

    def fail(self, gate_name: str, payload: Any) -> None:
        self.vreport.add(
            "quality_gates", gate_name, {"status": "fail", "detail": payload}
        )
        self._failures_by_name[gate_name] = payload

    def passed(self, gate_name: str) -> None:
        self.vreport.add("quality_gates", gate_name, {"status": "pass"})
        self._failures_by_name.pop(gate_name, None)

    def get_failures(self) -> Dict[str, Any]:
        return dict(self._failures_by_name)

    # ------------------------------- internal helpers ----------------------------

    def _persist_optional(self, rep: Dict[str, Any], name: str) -> None:
        if not self.logs_dir:
            return
        try:
            import json
            import os

            os.makedirs(self.logs_dir, exist_ok=True)
            with open(
                os.path.join(self.logs_dir, f"{name}.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(rep, f, indent=2, default=str)
        except Exception:
            # Reporting must never crash the pipeline.
            pass

    def _finalize_gate(self, name: str, rep: Dict[str, Any]) -> None:
        if not isinstance(rep, dict) or not rep.get("ok", True):
            self.fail(name, rep)
        else:
            self.passed(name)

    @staticmethod
    def _require_path(xodr_path: Any, gate_name: str) -> str:
        if not isinstance(xodr_path, str) or not xodr_path.strip():
            raise TypeError(
                f"{gate_name} expects xodr_path: str (got {type(xodr_path)!r})"
            )
        return xodr_path

    # -------------------------------- concrete gates --------------------------------

    def gate_xml_integrity(self, xodr_path: str) -> None:
        from ultimate_pipeline.quality.check_xml_integrity import XMLIntegrityChecker

        xodr_path = self._require_path(xodr_path, "gate_xml_integrity")
        issues = XMLIntegrityChecker.validate(xodr_path)
        if issues:
            self.fail("xml_integrity", issues)
        else:
            self.passed("xml_integrity")

    def gate_elevation_smoothness(self, root) -> None:
        from ultimate_pipeline.quality.check_elevation_smoothness import (
            ElevationSmoothnessGate,
        )

        issues = ElevationSmoothnessGate.validate(root)
        if issues:
            self.fail("elevation_smoothness", issues)
        else:
            self.passed("elevation_smoothness")

    def gate_physics_feasibility(self, root) -> None:
        from ultimate_pipeline.quality.check_physics_feasibility import (
            PhysicsFeasibilityChecker,
        )

        issues = PhysicsFeasibilityChecker.validate(root)
        if issues:
            self.fail("physics_feasibility", issues)
        else:
            self.passed("physics_feasibility")

    def gate_randomness_entropy(self, root) -> None:
        from ultimate_pipeline.quality.check_randomness_entropy import (
            RandomnessEntropyMetric,
        )

        score = RandomnessEntropyMetric.compute(root)
        if score < 0.05:
            self.fail("randomness_entropy", {"entropy": score})
        else:
            self.passed("randomness_entropy")

    def gate_semantic_overlap(self, root) -> None:
        from ultimate_pipeline.quality.check_semantic_overlap import (
            SemanticOverlapChecker,
        )

        issues = SemanticOverlapChecker.validate(root)
        if issues:
            self.fail("semantic_overlap", issues)
        else:
            self.passed("semantic_overlap")

    def gate_collision_mesh(self, root) -> None:
        """Optional collision-mesh sanity gate using Shapely.

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

    def gate_carla_opendrive_compat(self, root) -> None:
        """Fail-fast CARLA import safety gate.

        Only fails on severity=='error' issues. Warnings are recorded as diagnostics
        but do not block the pipeline for thesis practicality.
        """
        from ultimate_pipeline.quality.check_carla_opendrive_compat import (
            StrictCarlaOpendriveGate,
        )

        issues = StrictCarlaOpendriveGate.validate(root)
        errors = [i for i in issues if i.get("severity") == "error"]
        warns = [i for i in issues if i.get("severity") == "warn"]

        # Record all issues in vreport for diagnostics
        if issues:
            self.vreport.add("quality_gates", "carla_opendrive_compat_issues", issues)

        # Only fail on actual errors, not warnings
        if errors:
            self.fail("carla_opendrive_compat", errors)
        else:
            if warns:
                print(f"⚠️ CARLA compat gate: {len(warns)} warning(s) (non-fatal)")
            self.passed("carla_opendrive_compat")

    def gate_dem_coverage(
        self,
        xodr_path: str,
        dem_path: str,
        *,
        threshold: float = 0.6,
        stage: str | None = None,
    ) -> Dict[str, Any]:
        from ultimate_pipeline.quality.check_dem_coverage import check_dem_coverage

        xodr_path = self._require_path(xodr_path, "gate_dem_coverage")
        rep = check_dem_coverage(xodr_path, dem_path, threshold=threshold)
        self._persist_optional(rep, stage or "dem_coverage")
        self._finalize_gate("dem_coverage", rep)
        return rep

    def gate_elevation_continuity(
        self, xodr_path: str, *, stage: str | None = None
    ) -> Dict[str, Any]:
        from ultimate_pipeline.quality.check_elevation_continuity import (
            check_elevation_continuity,
        )
        import os

        def _truthy_text(value: Any) -> bool:
            return str(value or "").strip().lower() in ("1", "true", "yes", "on")

        def _truthy_env(name: str) -> bool:
            return _truthy_text(os.getenv(name, ""))

        def _settings_thesis_strict() -> bool:
            try:
                from ultimate_pipeline.config.settings import SETTINGS

                return bool(getattr(SETTINGS, "THESIS_STRICT", False))
            except Exception:
                return False

        env_value = os.getenv("UP_ELEVATION_CONTINUITY_OFFSETS")
        env_override_present = env_value is not None and env_value.strip() != ""
        strict = (
            _truthy_env("UP_STRICT_QUALITY_GATES")
            or _truthy_env("UP_THESIS_STRICT")
            or _settings_thesis_strict()
        )
        if env_override_present:
            enable_offsets = _truthy_text(env_value)
            activation_reason = "env_enabled" if enable_offsets else "disabled"
        elif strict:
            enable_offsets = True
            activation_reason = "strict_auto_enabled"
        else:
            enable_offsets = False
            activation_reason = "disabled"

        xodr_path = self._require_path(xodr_path, "gate_elevation_continuity")

        offset_report: Dict[str, Any] = {
            "enabled": bool(enable_offsets),
            "applied": False,
            "reason": activation_reason,
            "explicit_env_override": bool(env_override_present),
            "strict_mode": bool(strict),
        }

        # Deterministic repair (no threshold changes): apply per-road constant Z offsets
        # directly to the FILE that the checker will read.
        if enable_offsets:
            try:
                from ultimate_pipeline.enrichment.elevation_link_offset_solver import apply_link_offset_correction

                rep_offsets = apply_link_offset_correction(xodr_path)
                roads_with_offsets = int(rep_offsets.get("roads_with_offsets", 0) or 0)
                offset_report.update(
                    {
                        "applied": roads_with_offsets > 0,
                        "roads_with_offsets": roads_with_offsets,
                        "components": int(rep_offsets.get("components", 0) or 0),
                        "max_abs_offset_m": float(rep_offsets.get("max_abs_offset_m", 0.0) or 0.0),
                    }
                )
            except Exception as e:
                offset_report["error"] = str(e)
                if strict:
                    raise RuntimeError(f"Offset solver failed in strict mode: {e}") from e
                try:
                    self.vreport.add(
                        "quality_gates",
                        "elevation_offset_solver_error",
                        {"error": str(e), "reason": activation_reason},
                    )
                except Exception:
                    pass

        self._persist_optional(
            offset_report,
            (stage or "elevation_continuity") + "__offset_solver",
        )
        rep = check_elevation_continuity(xodr_path)
        rep["offset_solver"] = offset_report
        self._persist_optional(rep, stage or "elevation_continuity")
        self._finalize_gate("elevation_continuity", rep)
        return rep

    # ------------------------------- topology / junction gates -------------------

    def gate_junction_integrity(
        self, xodr_path_or_root, *, stage: str | None = None
    ) -> Dict[str, Any]:
        """Validate junction references and connection consistency."""
        from ultimate_pipeline.quality.check_junction_integrity import (
            JunctionIntegrityGate,
        )

        rep = JunctionIntegrityGate.validate(xodr_path_or_root)
        self._persist_optional(
            rep, f"{(stage or 'junction_integrity')}_junction_integrity"
        )
        self._finalize_gate("junction_integrity", rep)
        return rep

    # ---------------- lane / geometry continuity gates ----------------

    def gate_lane_width_continuity(
        self, xodr_path: str, *, stage: str | None = None
    ) -> Dict[str, Any]:
        from ultimate_pipeline.quality.check_lane_width_continuity import (
            check_lane_width_continuity,
        )

        xodr_path = self._require_path(xodr_path, "gate_lane_width_continuity")
        rep = check_lane_width_continuity(xodr_path)
        self._persist_optional(rep, stage or "lane_width_continuity")
        self._finalize_gate("lane_width_continuity", rep)
        return rep

    def gate_lane_geometry_continuity(
        self, xodr_path: str, *, stage: str | None = None
    ) -> Dict[str, Any]:
        from ultimate_pipeline.quality.check_lane_geometry_continuity import (
            check_lane_geometry_continuity,
        )

        xodr_path = self._require_path(xodr_path, "gate_lane_geometry_continuity")
        rep = check_lane_geometry_continuity(xodr_path)
        self._persist_optional(rep, stage or "lane_geometry_continuity")
        self._finalize_gate("lane_geometry_continuity", rep)
        return rep

    def gate_geometric_continuity(
        self, xodr_path: str, *, stage: str | None = None
    ) -> Dict[str, Any]:
        """Generic geometry continuity checker (path-based)."""
        from ultimate_pipeline.quality.check_geometric_continuity import (
            check_geometric_continuity,
        )

        xodr_path = self._require_path(xodr_path, "gate_geometric_continuity")
        rep = check_geometric_continuity(xodr_path)
        self._persist_optional(rep, stage or "geometric_continuity")
        self._finalize_gate("geometric_continuity", rep)
        return rep

    def gate_origin_sanity(
        self, xodr_path: str, *, stage: str | None = None
    ) -> Dict[str, Any]:
        from ultimate_pipeline.quality.check_origin_sanity import check_origin_sanity

        xodr_path = self._require_path(xodr_path, "gate_origin_sanity")
        rep = check_origin_sanity(xodr_path)
        self._persist_optional(rep, stage or "origin_sanity")
        self._finalize_gate("origin_sanity", rep)
        return rep

    def gate_elevation_seams(
        self, xodr_path: str, *, stage: str | None = None
    ) -> Dict[str, Any]:
        from ultimate_pipeline.quality.check_elevation_seams import (
            check_elevation_seams,
        )

        xodr_path = self._require_path(xodr_path, "gate_elevation_seams")
        rep = check_elevation_seams(xodr_path)
        self._persist_optional(rep, stage or "elevation_seams")
        self._finalize_gate("elevation_seams", rep)
        return rep

    # ------------------------------- CARLA-stability gates ------------------------

    def gate_xodr_strict_carla(self, xodr_path: str) -> None:
        """Strict OpenDRIVE validation tuned to CARLA import stability."""
        from ultimate_pipeline.quality.xodr_strict_validator import StrictXodrValidator

        xodr_path = self._require_path(xodr_path, "gate_xodr_strict_carla")
        rep = StrictXodrValidator().validate_path(xodr_path)
        if not rep.get("ok", False):
            self.fail("xodr_strict_carla", rep)
        else:
            self.passed("xodr_strict_carla")

    # ------------------------------- attachments --------------------------------

    def attach_geometry_validator(self, geom_report: Dict[str, Any]) -> None:
        if geom_report:
            self.vreport.add_dict("geometry_validator", geom_report)
