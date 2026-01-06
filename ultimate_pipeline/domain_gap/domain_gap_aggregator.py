from __future__ import annotations
from typing import Dict, Any, Optional


class DomainGapAggregator:
    """
    Aggregates individual domain-gap components into a structured report.

    Academic contract:
    - Raw metrics are preserved verbatim
    - Normalization is explicit, documented, and reproducible
    - Disabled or missing components NEVER influence composites
    - Composite score ∈ [0,1], where 0 = identical maps
    - Composite computation is OPTIONAL and fully auditable
    """

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------
    @staticmethod
    def _safe_dict(d: Any) -> Dict[str, Any]:
        return d if isinstance(d, dict) else {}

    @staticmethod
    def _norm(value: Optional[float], ref: float) -> Optional[float]:
        """
        Normalize |value| by an explicit reference scale.
        Returns None if normalization is undefined.
        """
        if value is None or ref <= 0:
            return None
        try:
            return min(abs(float(value)) / float(ref), 1.0)
        except Exception:
            return None

    # -------------------------------------------------
    # Main entry point
    # -------------------------------------------------
    @staticmethod
    def aggregate(
            *,
            gap_geometry: Dict | None = None,
            gap_curvature: Dict | None = None,
            gap_intersection: Dict | None = None,
            gap_semantic: Dict | None = None,
            gap_road_classification: Dict | None = None,  # ✅ ADD
            compute_composite: bool = False,
            weights: Dict[str, float] | None = None,
            normalization: Dict[str, float] | None = None,
    ) -> Dict[str, Any]:

        # ---------------------------------------------
        # Normalization contract (explicit defaults)
        # ---------------------------------------------
        norm = normalization or {
            "geometry_rmse_m": 1.0,     # meters
            "curvature_kl": 0.5,        # KL divergence
            "intersection_delta": 1.0,  # placeholder (not used in composite)
            "semantic_delta": 1.0,      # placeholder (not used in composite)
        }

        # ---------------------------------------------
        # Weight contract (only positive weights count)
        # ---------------------------------------------
        w = weights or {
            "geometry": 1.0,
            "curvature": 1.0,
            "intersection": 1.0,
            "semantic": 1.0,
        }

        out: Dict[str, Any] = {
            "components": {},
            "composite": None,
            "composite_metadata": None,
        }

        # =====================================================
        # Geometry
        # =====================================================
        g = DomainGapAggregator._safe_dict(gap_geometry)
        if g and not g.get("disabled"):
            rmse = g.get("rmse")
            rmse_norm = DomainGapAggregator._norm(
                rmse, norm.get("geometry_rmse_m", 1.0)
            )

            out["components"]["geometry"] = {
                "rmse": rmse,
                "hausdorff": g.get("hausdorff"),
                "rmse_norm": rmse_norm,
                "runtime_sec": g.get("runtime_sec"),
                "samples": g.get("samples"),
            }
        else:
            out["components"]["geometry"] = {"disabled": True}

        # =====================================================
        # Curvature
        # =====================================================
        c = DomainGapAggregator._safe_dict(gap_curvature)
        if c and not c.get("disabled"):
            kl = c.get("kl_divergence")
            kl_norm = DomainGapAggregator._norm(
                kl, norm["curvature_kl"]
            )
            out["components"]["curvature"] = {
                "kl_divergence": kl,
                "kl_divergence_norm": kl_norm,
                "delta_mean": c.get("delta_mean"),
                "runtime_sec": c.get("runtime_sec"),
                "samples_manual": c.get("samples_manual"),
                "samples_auto": c.get("samples_auto"),
            }
        else:
            out["components"]["curvature"] = {"disabled": True}

        # =====================================================
        # Intersection (reported, not normalized)
        # =====================================================
        i = DomainGapAggregator._safe_dict(gap_intersection)
        if i and not i.get("disabled"):
            out["components"]["intersection"] = dict(i)
        else:
            out["components"]["intersection"] = {"disabled": True}

        # =====================================================
        # Semantic / object gap (reported, not normalized)
        # =====================================================
        s = DomainGapAggregator._safe_dict(gap_semantic)
        if s and not s.get("disabled"):
            out["components"]["semantic"] = dict(s)
        else:
            out["components"]["semantic"] = {"disabled": True}
        # =====================================================
        # Road classification
        # =====================================================
        r = DomainGapAggregator._safe_dict(gap_road_classification)
        if r and not r.get("disabled"):
            out["components"]["road_classification"] = dict(r)
        else:
            out["components"]["road_classification"] = {"disabled": True}

        # =====================================================
        # Composite score (optional, geometry + curvature only)
        # =====================================================
        if compute_composite:
            score = 0.0
            weight_sum = 0.0
            used = []

            g_c = out["components"]["geometry"]
            gw = float(w.get("geometry", 0.0))
            if gw > 0 and not g_c.get("disabled") and g_c.get("rmse_norm") is not None:
                score += gw * g_c["rmse_norm"]
                weight_sum += gw
                used.append("geometry")

            c_c = out["components"]["curvature"]
            cw = float(w.get("curvature", 0.0))
            if cw > 0 and not c_c.get("disabled") and c_c.get("kl_divergence_norm") is not None:
                score += cw * c_c["kl_divergence_norm"]
                weight_sum += cw
                used.append("curvature")

            used.sort()

            if weight_sum > 0:
                out["composite"] = score / weight_sum
                out["composite_metadata"] = {
                    "used_components": used,
                    "weights": {k: w.get(k) for k in used},
                    "normalization": norm,
                    "normalization_units": {
                        "geometry_rmse_m": "meters",
                        "curvature_kl": "KL divergence",
                    },
                    "range": "[0,1]",
                    "interpretation": "0 = identical maps, 1 = maximal modeled gap",
                    "excluded_components": [
                        "intersection",
                        "semantic",
                        "road_classification",
                    ],

                }
            else:
                out["composite"] = None
                out["composite_metadata"] = {
                    "reason": "no normalized components available"
                }

        return out
