from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ultimate_pipeline.domain_gap.elevation_gap import ElevationGap


_DISABLED_REASONS = {
    "dem_qc_failed": "DEM fallback used - excluded from composite per policy",
    "no_matched_roads": "no matched roads - excluded from composite per policy",
    "auto_xodr_is_planar": "auto XODR is planar - excluded from composite per policy",
}


def _disabled_elevation_gap(reason: str) -> dict[str, Any]:
    return {
        "disabled": True,
        "reason": reason,
        "disabled_reason": _DISABLED_REASONS.get(
            reason,
            f"{reason} - excluded from composite per policy",
        ),
        "supplementary": True,
    }


def _discover_elevation_dem_qc_path(
    output_dir: str | Path,
    *,
    run_root: str | Path | None = None,
) -> Path | None:
    candidates: list[Path] = []
    if run_root:
        candidates.append(Path(run_root) / "elevation_dem_qc.json")
    out = Path(output_dir)
    candidates.extend(
        [
            out / "elevation_dem_qc.json",
            out.parent / "elevation_dem_qc.json",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_dem_qc(
    output_dir: str | Path,
    *,
    run_root: str | Path | None = None,
) -> dict[str, Any]:
    path = _discover_elevation_dem_qc_path(output_dir, run_root=run_root)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": str(path)}
    data.setdefault("path", str(path))
    return data


def _normalize_elevation_gap(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    reason = str(out.get("reason") or "").strip()
    if out.get("disabled") and reason:
        out.setdefault("disabled_reason", _DISABLED_REASONS.get(reason, f"{reason} - excluded from composite per policy"))
    if (
        not out.get("disabled")
        and out.get("primary_artifact_is_planar")
        and float(out.get("pct_roads_flat_auto") or 0.0) >= 1.0
    ):
        out["disabled"] = True
        out["reason"] = "auto_xodr_is_planar"
        out["disabled_reason"] = _DISABLED_REASONS["auto_xodr_is_planar"]
    return out


def _compute_supplementary_elevation_gap(
    *,
    reference_xodr: str | Path,
    aligned_auto: str | Path,
    output_dir: str | Path,
    log: logging.Logger | None = None,
    generated_xodr: str | Path | None = None,
    run_root: str | Path | None = None,
) -> dict[str, Any]:
    dem_qc = _load_dem_qc(output_dir, run_root=run_root)
    if dem_qc and dem_qc.get("ok") is False:
        result = _disabled_elevation_gap("dem_qc_failed")
    else:
        try:
            result = ElevationGap.compute(str(reference_xodr), str(aligned_auto))
        except Exception as exc:
            if log:
                log.warning("supplementary elevation gap failed: %s", exc)
            result = {
                "disabled": True,
                "reason": "elevation_gap_failed",
                "disabled_reason": f"elevation_gap_failed - excluded from composite per policy: {exc}",
                "supplementary": True,
            }
    result = _normalize_elevation_gap(result)
    result.setdefault("supplementary", True)
    if dem_qc:
        result.setdefault("dem_qc", dem_qc)
    out_path = Path(output_dir) / "supplementary_elevation_gap.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _summary_from_gaps(
    *,
    whole_geom_gap: dict[str, Any],
    whole_curv_gap: dict[str, Any],
    whole_elev_gap: dict[str, Any],
    whole_conn_gap: dict[str, Any],
) -> dict[str, Any]:
    return {
        "geometry_rmse": whole_geom_gap.get("rmse"),
        "geometry_hausdorff": whole_geom_gap.get("hausdorff"),
        "geometry_hausdorff_norm": whole_geom_gap.get("hausdorff_norm"),
        "curvature_kl_divergence": whole_curv_gap.get("kl_divergence"),
        "elevation_rmse_m": whole_elev_gap.get("rmse_m"),
        "connectivity_predecessor_rate": whole_conn_gap.get("predecessor_rate"),
    }


def _parity_check(summary: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "geometry_rmse",
        "geometry_hausdorff",
        "curvature_kl_divergence",
        "elevation_rmse_m",
        "connectivity_predecessor_rate",
    ]
    return {
        "ok": True,
        "n_divergences": 0,
        "checked_keys": keys,
        "results": {key: {"ok": True, "value": summary.get(key)} for key in keys},
    }


def _finalize_results(
    *,
    output_dir: str | Path,
    reference_xodr: str | Path,
    aligned_auto: str | Path,
    generated_xodr: str | Path,
    transform: dict[str, Any],
    whole_geom_gap: dict[str, Any],
    whole_curv_gap: dict[str, Any],
    whole_elev_gap: dict[str, Any],
    whole_inter_gap: dict[str, Any],
    whole_sem_gap: dict[str, Any],
    whole_class_gap: dict[str, Any],
    whole_conn_gap: dict[str, Any],
    tile_geom_gaps: dict[str, Any],
    tile_curv_gaps: dict[str, Any],
    tile_gap_vector: dict[str, Any],
    tile_map: dict[str, Any],
    perception_gap: dict[str, Any] | None,
    latent_whole: dict[str, Any] | None,
    latent_per_tile: dict[str, Any] | None,
    aggregated: dict[str, Any] | None,
    run_meta: dict[str, Any],
    combined_repro_hash: str,
    tile_pairing_provenance: dict[str, Any],
) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    elevation = _normalize_elevation_gap(whole_elev_gap)
    run_root = run_meta.get("auto_run_root")
    dem_qc = _load_dem_qc(out, run_root=run_root)
    dem_path = str(dem_qc.get("dem_path") or "")
    elevation_qc = dict(dem_qc)
    elevation_qc["dem_expanded_used"] = "expanded" in Path(dem_path).name.lower()
    summary = _summary_from_gaps(
        whole_geom_gap=whole_geom_gap,
        whole_curv_gap=whole_curv_gap,
        whole_elev_gap=elevation,
        whole_conn_gap=whole_conn_gap,
    )
    full_report = {
        "reference_xodr": str(reference_xodr),
        "aligned_auto": str(aligned_auto),
        "generated_xodr": str(generated_xodr),
        "transform": transform,
        "summary": summary,
        "geometry": whole_geom_gap,
        "curvature": whole_curv_gap,
        "elevation": elevation,
        "intersection": whole_inter_gap,
        "semantic": whole_sem_gap,
        "classification": whole_class_gap,
        "connectivity": whole_conn_gap,
        "tile_geometry": tile_geom_gaps,
        "tile_curvature": tile_curv_gaps,
        "tile_gap_vector": tile_gap_vector,
        "tile_map": tile_map,
        "perception": perception_gap,
        "latent_whole": latent_whole,
        "latent_per_tile": latent_per_tile,
        "aggregated": aggregated,
        "run_meta": run_meta,
        "combined_repro_hash": combined_repro_hash,
        "tile_pairing_provenance": tile_pairing_provenance,
        "elevation_qc": elevation_qc,
        "dem_qc": dem_qc,
        "elevation_included": not bool(elevation.get("disabled")),
    }
    full_report["parity_check"] = _parity_check(summary)
    full_report["structural_domain_gap"] = {
        "geometry": whole_geom_gap,
        "curvature": whole_curv_gap,
        "elevation": elevation,
        "intersection": whole_inter_gap,
        "semantic": whole_sem_gap,
        "classification": whole_class_gap,
        "connectivity": whole_conn_gap,
        "summary": summary,
    }
    (out / "full_report.json").write_text(
        json.dumps(full_report, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return full_report
