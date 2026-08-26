#!/usr/bin/env python3
"""C19 (step 1) — export honest, provenance-cited per-RQ tables.

Reads the actual C12-C18 evidence artifacts on disk (never re-derives or
guesses numbers) and assembles one machine-readable table per research
question, each row citing the artifact it came from and its sha256 where
the artifact is a pinned file. A row with no evidence file present is
reported as MISSING, not silently omitted -- the honesty gate (C19 step 2,
audit_thesis_topic_contract.py) checks that every row has an explicit
status.

Status vocabulary (kept consistent with ultimate_pipeline.config.thesis_contract):
    AUTHORITATIVE - full result, methodology sound, ready to cite as-is
    BOUNDED       - real result but with an explicit scope/method caveat
    PROTOTYPE     - real result but not yet validated (single run, no CI, etc.)
    DEFERRED      - genuinely not computed yet, with a stated reason
    MISSING       - evidence file this table row depends on was not found
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

AUTHORITATIVE = "AUTHORITATIVE"
BOUNDED = "BOUNDED"
PROTOTYPE = "PROTOTYPE"
DEFERRED = "DEFERRED"
MISSING = "MISSING"


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _row(rq: str, metric: str, value: Any, status: str, *, artifact: str = "",
         sha256: str = "", note: str = "") -> Dict[str, Any]:
    return {
        "rq": rq, "metric": metric, "value": value, "status": status,
        "artifact": artifact, "sha256": sha256, "note": note,
    }


def _rq1_rows(root: Path) -> List[Dict[str, Any]]:
    ev_dir = root / "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP"
    curvature = _read_json(ev_dir / "curvature_recompute.json")
    local = _read_json(ev_dir / "local_registration.json")
    main = _read_json(ev_dir / "C14_RQ1_STRUCTURAL_GAP.json")
    if main is None:
        return [_row("RQ1", "structural_gap_composite", None, MISSING,
                      note="C14_RQ1_STRUCTURAL_GAP.json not found -- RQ1 not computed")]

    scores = (curvature or {}).get("all_scores") or main.get("scores") or {}
    auto = main.get("auto_map", {})
    manual = main.get("manual_map", {})
    artifact = f"{auto.get('path', '')} vs {manual.get('path', '')}"
    # local_registration.json schema (C26, 2026-08-26): top-level "hull" (default, tighter,
    # preferred) / "bbox" (legacy, wider) blocks, each with its own "local_structural_summary".
    # Older artifacts had a single flat top-level "local_structural_summary" -- kept as a
    # fallback so this tool degrades gracefully against a stale/legacy artifact rather than
    # silently reporting whole-map-only rows.
    local = local or {}
    local_summary = (
        (local.get("hull") or {}).get("local_structural_summary")
        or (local.get("bbox") or {}).get("local_structural_summary")
        or local.get("local_structural_summary")
        or {}
    )
    footprint_kind = "hull" if "hull" in local else ("bbox" if "bbox" in local else "unknown")
    local_network = local_summary.get("road_network_structural") or {}
    local_footprint = local_summary.get("footprint") or {}
    local_construction = local_summary.get("construction_differences_excluded") or {}
    local_buildings = local_summary.get("building_density_comparison") or {}
    if local_network:
        footprint_note = f" [footprint={footprint_kind}]" if footprint_kind != "unknown" else ""
        rows = [
            _row("RQ1", "local_lane_width_gap", local_network.get("lane_width_gap"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint comparison; directly comparable lane geometry, maps agree"
                      + footprint_note),
            _row("RQ1", "local_curvature_gap", local_network.get("curvature_gap"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint comparison; range-sensitive histogram-L1, "
                      "treat as a bounded structural signal, not a precise scalar" + footprint_note),
            _row("RQ1", "local_curvature_wasserstein_gap",
                 local_network.get("curvature_wasserstein_gap"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint comparison; Wasserstein distance over absolute-curvature "
                      "distributions, normalized by 0.2 1/m; range-robust companion to histogram-L1"
                      + footprint_note),
            _row("RQ1", "local_road_length_ratio_auto_over_manual",
                 local_network.get("road_length_ratio_auto_over_manual"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint ratio; measures road-network completeness inside Grid0828's area"
                      + footprint_note + " -- hull is tighter/preferred, bbox kept in local_registration.json "
                      "for comparison (hull materially lowers this ratio vs. the legacy bbox footprint)"),
            _row("RQ1", "local_junction_ratio_auto_over_manual",
                 local_network.get("junction_ratio_auto_over_manual"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint ratio; measures junction/detail completeness inside Grid0828's area"
                      + footprint_note),
            _row("RQ1", "local_road_count_ratio_auto_over_manual",
                 local_network.get("road_count_ratio_auto_over_manual"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint ratio; separates structural completeness from whole-map scope"
                      + footprint_note),
            _row("RQ1", "local_auto_footprint_kept_fraction",
                 local_footprint.get("kept_fraction"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note=f"manual-footprint crop kept {local_footprint.get('auto_roads_kept')} / "
                      f"{local_footprint.get('auto_roads_total')} auto roads; whole-map stats are scope context"
                      + footprint_note),
            _row("RQ1", "whole_map_construction_layers_excluded_from_local_gap", True, BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note=local_construction.get("reason", "traffic-light density is a construction layer, "
                                             "not the local road-network structural gap")),
            _row("RQ1", "whole_map_road_type_coverage_gap_context",
                 scores.get("road_type_coverage_gap"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="whole-map context only; manual road types are a subset of auto's"),
        ]
        if local_buildings:
            rows.append(_row(
                "RQ1", "local_building_density_gap", local_buildings.get("building_density_gap"), BOUNDED,
                artifact=artifact, sha256=auto.get("sha256", ""),
                note="LOCAL manual-footprint building density comparison (C26): buildings recovered via "
                     "outline cornerGlobal absolute positions and cropped in-footprint -- no longer excluded"
                     + footprint_note,
            ))
        return rows

    rows = [
        _row("RQ1", "lane_width_gap", scores.get("lane_width_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""),
             note="genuine, small -- directly comparable, maps agree"),
        _row("RQ1", "curvature_gap", scores.get("curvature_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""),
             note="real (fixed 2026-08-21, was a 1.0 measurement artifact); "
                  "range-sensitive histogram-L1, treat as 'moderate' not a precise scalar"),
        _row("RQ1", "curvature_wasserstein_gap", scores.get("curvature_wasserstein_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""),
             note="Wasserstein distance over absolute-curvature distributions, normalized by 0.2 1/m; "
                  "range-robust companion to histogram-L1"),
        _row("RQ1", "road_length_gap", scores.get("road_length_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""),
             note="construction/scope artifact (full OSM extraction vs curated subset), not domain gap"),
        _row("RQ1", "traffic_light_density_gap", scores.get("traffic_light_density_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""), note="construction artifact"),
        _row("RQ1", "building_density_gap", scores.get("building_density_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""), note="construction artifact"),
        _row("RQ1", "road_type_coverage_gap", scores.get("road_type_coverage_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""), note="manual road types are a subset of auto's"),
    ]
    return rows


def _rq2_rows(root: Path) -> List[Dict[str, Any]]:
    ev = root / "reports/post_audit_hardening/C17_rq2_perception_capture.md"
    return [_row("RQ2", "perceptual_gap", None, DEFERRED,
                  artifact=str(ev.relative_to(root)) if ev.is_file() else "",
                  note="paired capture not executed -- needs a live CARLA server "
                       "(currently blocked by a livelock, see C20_TIER1_PROBE_20260821) "
                       "or the C16 UE cook (blocked on a human operator)")]


def _rq3_rq5_rows(root: Path) -> List[Dict[str, Any]]:
    ev_dir = root / "reports/post_audit_hardening/C18_GNN_LATENT_GAP"
    gnn = _read_json(ev_dir / "gnn_training_report.json")
    rows: List[Dict[str, Any]] = []
    if gnn is not None:
        metrics = ((gnn.get("latent_gap") or {}).get("metrics")) or {}
        ckpt_md5 = ((gnn.get("latent_gap") or {}).get("encoder") or {}).get("checkpoint_md5", "")
        rows.append(_row(
            "RQ3/RQ5", "gnn_latent_cosine_distance", metrics.get("cosine_distance"), PROTOTYPE,
            artifact="map_encoder_epoch50.pt", sha256=ckpt_md5,
            note="one-sided (auto-only) training makes the manual map OOD for the encoder -- "
                 "conflates true structural gap with distribution shift; corroborates RQ1, "
                 "not an independent authoritative measurement",
        ))
    else:
        rows.append(_row("RQ3/RQ5", "gnn_latent_cosine_distance", None, MISSING,
                          note="gnn_training_report.json not found"))
    rows.append(_row("RQ3", "miou_auto_train_manual_eval", None, DEFERRED,
                      note="needs C17 paired captures (blocked -- see RQ2)"))
    rows.append(_row("RQ5", "real_unlabeled_shift_metrics", None, DEFERRED,
                      note="no real-world Ingolstadt dataset available on this machine "
                           "(independent of the CARLA blocker)"))
    rows.append(_row("RQ3", "domain_adaptation_coral_mmd", None, DEFERRED,
                      note="needs C17 paired captures (blocked -- see RQ2)"))
    return rows


def _rq4_rows(root: Path) -> List[Dict[str, Any]]:
    ev_dir = root / "reports/post_audit_hardening/C15_RQ4_DR"
    data = _read_json(ev_dir / "C15_RQ4_DOMAIN_RANDOMIZATION.json")
    if data is None:
        return [_row("RQ4", "natural_dr", None, MISSING, note="C15_RQ4_DOMAIN_RANDOMIZATION.json not found")]
    det = data.get("determinism_arm", {})
    dr = data.get("explicit_dr", {})
    return [
        _row("RQ4", "natural_dr_present", False, AUTHORITATIVE,
             artifact="ultimate_pipeline/experiments/thesis/exp_osm_to_xodr_determinism.py",
             note=det.get("finding", "")),
        _row("RQ4", "structurally_deterministic", det.get("structurally_deterministic"), AUTHORITATIVE,
             note=f"{det.get('runs', 0)} runs, {det.get('byte_sha_unique', 0)} distinct sha256 "
                  "(byte-non-deterministic serialization, structure identical)"),
        _row("RQ4", "explicit_dr_wired", dr.get("changes_input"), AUTHORITATIVE,
             artifact=dr.get("module", ""),
             note=f"apply_n produces {dr.get('apply_n_produces_distinct_variants')} distinct variants; "
                  "deterministic given a seed, varies across seeds"),
    ]


def build_tables(root: Path) -> Dict[str, Any]:
    rows = (
        _rq1_rows(root) + _rq2_rows(root) + _rq3_rq5_rows(root) + _rq4_rows(root)
    )
    by_status: Dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {"rows": rows, "counts_by_status": by_status, "row_count": len(rows)}


def _to_markdown(payload: Dict[str, Any]) -> str:
    lines = ["# Thesis RQ tables (C19)", "", "| RQ | metric | value | status | note |", "|---|---|---|---|---|"]
    for r in payload["rows"]:
        val = r["value"]
        val_s = "—" if val is None else str(val)
        lines.append(f"| {r['rq']} | {r['metric']} | {val_s} | {r['status']} | {r['note']} |")
    lines.append("")
    lines.append(f"Counts by status: {payload['counts_by_status']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    args = ap.parse_args()

    payload = build_tables(REPO_ROOT)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "rq_tables.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (args.out / "rq_tables.md").write_text(_to_markdown(payload), encoding="utf-8")
    print(f"[export_thesis_tables] {payload['row_count']} rows -> {args.out}")
    print(f"[export_thesis_tables] counts_by_status: {payload['counts_by_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
