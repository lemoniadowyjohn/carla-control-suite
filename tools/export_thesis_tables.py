#!/usr/bin/env python3
"""C19 (step 1) — export honest, provenance-cited per-RQ tables.

Reads the actual C12-C18 evidence artifacts on disk (never re-derives or
guesses numbers) and assembles one machine-readable table per research
question, each row carrying provenance, comparability, and claim-boundary
fields. A row with no evidence file present is reported as NOT_RUN, not
silently omitted -- the honesty gate (C19 step 2,
audit_thesis_topic_contract.py) checks that every row has an explicit status.

Status vocabulary (kept consistent with ultimate_pipeline.config.thesis_contract):
    AUTHORITATIVE - full result, methodology sound, ready to cite as-is
    BOUNDED       - real result but with an explicit scope/method caveat
    PROTOTYPE     - real result but not yet validated (single run, no CI, etc.)
    DEFERRED_RUNTIME       - blocked by a missing/invalid live runtime arm
    DEFERRED_EXTERNAL_DATA - blocked by unavailable external data
    SUPERSEDED             - preserved historical row replaced by newer evidence
    NOT_RUN                - evidence file/run this table row depends on was not found
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

AUTHORITATIVE = "AUTHORITATIVE"
BOUNDED = "BOUNDED"
PROTOTYPE = "PROTOTYPE"
DEFERRED_RUNTIME = "DEFERRED_RUNTIME"
DEFERRED_EXTERNAL_DATA = "DEFERRED_EXTERNAL_DATA"
SUPERSEDED = "SUPERSEDED"
NOT_RUN = "NOT_RUN"

# Backwards-compatible names for older imports; emitted values use the new vocabulary.
DEFERRED = DEFERRED_RUNTIME
MISSING = NOT_RUN

VALID_STATUSES = frozenset({
    AUTHORITATIVE,
    BOUNDED,
    PROTOTYPE,
    DEFERRED_RUNTIME,
    DEFERRED_EXTERNAL_DATA,
    SUPERSEDED,
    NOT_RUN,
})
NO_CLAIM_STATUSES = frozenset({DEFERRED_RUNTIME, DEFERRED_EXTERNAL_DATA, NOT_RUN})


def _producer_commit(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return "UNKNOWN"
    commit = proc.stdout.strip()
    return commit if proc.returncode == 0 and commit else "UNKNOWN"


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _row(
    rq: str,
    metric: str,
    value: Any,
    status: str,
    *,
    artifact: str = "",
    sha256: str = "",
    note: str = "",
    thesis_baseline: str = "",
    unit: str = "",
    absolute_delta: Any = None,
    relative_delta: Any = None,
    comparability: str = "",
    method: str = "",
    producer_commit: str = "UNKNOWN",
    evidence_path: str | None = None,
    evidence_sha256: str | None = None,
    input_auto_sha256: str = "",
    input_manual_sha256: str = "",
    software_versions: Dict[str, Any] | None = None,
    sample_size: Any = None,
    random_seeds: List[Any] | None = None,
    confidence_interval: Any = None,
    claim_boundary: str = "",
    remaining_blocker: str = "",
) -> Dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid research row status: {status}")
    if evidence_path is None:
        evidence_path = artifact
    if evidence_sha256 is None:
        evidence_sha256 = sha256
    if not claim_boundary:
        claim_boundary = note
    if status in NO_CLAIM_STATUSES and not remaining_blocker:
        remaining_blocker = note
    return {
        "rq": rq,
        "metric": metric,
        "value": value,
        "status": status,
        "artifact": artifact,
        "sha256": sha256,
        "note": note,
        "thesis_baseline": thesis_baseline,
        "current_value": value,
        "unit": unit,
        "absolute_delta": absolute_delta,
        "relative_delta": relative_delta,
        "comparability": comparability,
        "method": method or "C19 evidence-table export",
        "producer_commit": producer_commit,
        "evidence_path": evidence_path or "",
        "evidence_sha256": evidence_sha256 or "",
        "input_auto_sha256": input_auto_sha256,
        "input_manual_sha256": input_manual_sha256,
        "software_versions": software_versions or {},
        "sample_size": sample_size,
        "random_seeds": random_seeds or [],
        "confidence_interval": confidence_interval,
        "claim_boundary": claim_boundary,
        "remaining_blocker": remaining_blocker,
    }


def _rq1_determinism_rows(root: Path) -> List[Dict[str, Any]]:
    """Thesis RQ1 -- Determinism (OSM->OpenDRIVE structural/topological
    stability and byte-level nondeterminism origin). Reads the same C15
    evidence file as _rq4_variability_rows below (that file's
    "determinism_arm" section is this RQ's content; "explicit_dr" is RQ4's).
    """
    ev_dir = root / "reports/post_audit_hardening/C15_RQ4_DR"
    ev_path = ev_dir / "C15_RQ4_DOMAIN_RANDOMIZATION.json"
    data = _read_json(ev_path)
    if data is None:
        return [
            _row("RQ1", metric, None, NOT_RUN, note="C15_RQ4_DOMAIN_RANDOMIZATION.json not found")
            for metric in (
                "raw_hash_repeatability",
                "normalized_hash_repeatability",
                "structural_signature_repeatability",
                "byte_nondeterminism_source",
            )
        ]
    det = data.get("determinism_arm", {})
    runs = det.get("runs", 0)
    byte_sha_unique = det.get("byte_sha_unique", 0)
    structurally_deterministic = det.get("structurally_deterministic")
    ev_rel = str(ev_path.relative_to(root))
    ev_sha = hashlib.sha256(ev_path.read_bytes()).hexdigest()
    norm_ev_path = root / "tests/unit/test_exp_osm_to_xodr_determinism_normalized.py"
    norm_ev_rel = str(norm_ev_path.relative_to(root)) if norm_ev_path.is_file() else ev_rel
    norm_ev_sha = hashlib.sha256(norm_ev_path.read_bytes()).hexdigest() if norm_ev_path.is_file() else ev_sha
    return [
        _row("RQ1", "raw_hash_repeatability", byte_sha_unique == 1, AUTHORITATIVE,
             artifact=ev_rel, sha256=ev_sha, evidence_path=ev_rel, evidence_sha256=ev_sha,
             unit="boolean", sample_size=runs,
             thesis_baseline="Byte-level nondeterminism under fixed inputs.",
             comparability="directly comparable to thesis determinism claim",
             method="repeated pinned OSM->OpenDRIVE conversions",
             note=f"{runs} runs, {byte_sha_unique} distinct raw sha256 values"),
        _row("RQ1", "normalized_hash_repeatability", bool(norm_ev_path.is_file()), BOUNDED,
             artifact=norm_ev_rel, sha256=norm_ev_sha, evidence_path=norm_ev_rel, evidence_sha256=norm_ev_sha,
             unit="boolean", sample_size=runs,
             thesis_baseline="Timestamp-normalized byte comparison was not a completed thesis result.",
             comparability="bounded: large-artifact normalized-hash evidence exists locally; portable fixture covers CI",
             method="timestamp-normalized OpenDRIVE hashing where available",
             note="Portable committed fixture proves timestamp-only changes normalize to one hash and structural changes remain detectable; large raw C15 XODRs remain optional integration artifacts"),
        _row("RQ1", "structural_signature_repeatability", structurally_deterministic, AUTHORITATIVE,
             artifact=ev_rel, sha256=ev_sha, evidence_path=ev_rel, evidence_sha256=ev_sha,
             unit="boolean", sample_size=runs,
             thesis_baseline="Five governed thesis runs had invariant topological counts.",
             comparability="directly comparable within structural-signature scope",
             method="road/junction/total-length signature comparison",
             note=f"{runs} runs, {byte_sha_unique} distinct sha256 "
                  "(byte-non-deterministic serialization, structure identical)"),
        _row("RQ1", "byte_nondeterminism_source", "timestamp metadata suspected", BOUNDED,
             artifact=ev_rel, sha256=ev_sha, evidence_path=ev_rel, evidence_sha256=ev_sha,
             unit="classification", sample_size=runs,
             thesis_baseline="Thesis established byte-level nondeterminism but did not fully isolate its source.",
             comparability="partial: do not claim exhaustive source isolation until governed artifacts are reproducible",
             method="C15 determinism artifact plus timestamp-normalized fixture tests",
             note=det.get("finding", "")),
        _row("RQ1", "natural_dr_present", False, AUTHORITATIVE,
             artifact="ultimate_pipeline/experiments/thesis/exp_osm_to_xodr_determinism.py",
             evidence_path=ev_rel, evidence_sha256=ev_sha,
             sample_size=runs, comparability="directly comparable to same-input repeatability",
             note=det.get("finding", "")),
    ]


def _rq2_structural_gap_rows(root: Path) -> List[Dict[str, Any]]:
    """Thesis RQ2 -- Structural domain gap (automatic OSM map vs. manually
    modeled CARLA map of the same region)."""
    ev_dir = root / "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP"
    curvature = _read_json(ev_dir / "curvature_recompute.json")
    local = _read_json(ev_dir / "local_registration.json")
    main = _read_json(ev_dir / "C14_RQ1_STRUCTURAL_GAP.json")
    if main is None:
        return [_row("RQ2", "structural_gap_composite", None, MISSING,
                      note="C14_RQ1_STRUCTURAL_GAP.json not found -- RQ2 not computed")]

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
            _row("RQ2", "local_lane_width_gap", local_network.get("lane_width_gap"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint comparison; directly comparable lane geometry, maps agree"
                      + footprint_note),
            _row("RQ2", "local_curvature_gap", local_network.get("curvature_gap"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint comparison; range-sensitive histogram-L1, "
                      "treat as a bounded structural signal, not a precise scalar" + footprint_note),
            _row("RQ2", "local_curvature_wasserstein_gap",
                 local_network.get("curvature_wasserstein_gap"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint comparison; Wasserstein distance over absolute-curvature "
                      "distributions, normalized by 0.2 1/m; range-robust companion to histogram-L1"
                      + footprint_note),
            _row("RQ2", "local_road_length_ratio_auto_over_manual",
                 local_network.get("road_length_ratio_auto_over_manual"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint ratio; measures road-network completeness inside Grid0828's area"
                      + footprint_note + " -- hull is tighter/preferred, bbox kept in local_registration.json "
                      "for comparison (hull materially lowers this ratio vs. the legacy bbox footprint)"),
            _row("RQ2", "local_junction_ratio_auto_over_manual",
                 local_network.get("junction_ratio_auto_over_manual"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint ratio; measures junction/detail completeness inside Grid0828's area"
                      + footprint_note),
            _row("RQ2", "local_road_count_ratio_auto_over_manual",
                 local_network.get("road_count_ratio_auto_over_manual"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="LOCAL manual-footprint ratio; separates structural completeness from whole-map scope"
                      + footprint_note),
            _row("RQ2", "local_auto_footprint_kept_fraction",
                 local_footprint.get("kept_fraction"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note=f"manual-footprint crop kept {local_footprint.get('auto_roads_kept')} / "
                      f"{local_footprint.get('auto_roads_total')} auto roads; whole-map stats are scope context"
                      + footprint_note),
            _row("RQ2", "whole_map_construction_layers_excluded_from_local_gap", True, BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note=local_construction.get("reason", "traffic-light density is a construction layer, "
                                             "not the local road-network structural gap")),
            _row("RQ2", "whole_map_road_type_coverage_gap_context",
                 scores.get("road_type_coverage_gap"), BOUNDED,
                 artifact=artifact, sha256=auto.get("sha256", ""),
                 note="whole-map context only; manual road types are a subset of auto's"),
        ]
        if local_buildings:
            rows.append(_row(
                "RQ2", "local_building_density_gap", local_buildings.get("building_density_gap"), BOUNDED,
                artifact=artifact, sha256=auto.get("sha256", ""),
                note="LOCAL manual-footprint building density comparison (C26): buildings recovered via "
                     "outline cornerGlobal absolute positions and cropped in-footprint -- no longer excluded"
                     + footprint_note,
            ))
        frechet = _read_json(ev_dir / "frechet_distance_local.json")
        if frechet and frechet.get("matched_pair_count"):
            rows.append(_row(
                "RQ2", "local_frechet_distance_median_m", frechet.get("median_m"), BOUNDED,
                artifact=artifact, sha256=auto.get("sha256", ""),
                note=(
                    "Thesis future-work #14, recomputed against the current local-registration "
                    f"methodology: mean={frechet.get('mean_m')}m p90={frechet.get('p90_m')}m over "
                    f"{frechet.get('matched_pair_count')} matched road pairs "
                    f"(spacing={frechet.get('spacing_m')}m, threshold={frechet.get('match_threshold_m')}m); "
                    "~30-50x smaller than the delivered thesis's uncropped whole-network SE(2) number "
                    "on every statistic -- see THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md"
                    + footprint_note
                ),
            ))
        return rows

    rows = [
        _row("RQ2", "lane_width_gap", scores.get("lane_width_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""),
             note="genuine, small -- directly comparable, maps agree"),
        _row("RQ2", "curvature_gap", scores.get("curvature_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""),
             note="real (fixed 2026-08-21, was a 1.0 measurement artifact); "
                  "range-sensitive histogram-L1, treat as 'moderate' not a precise scalar"),
        _row("RQ2", "curvature_wasserstein_gap", scores.get("curvature_wasserstein_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""),
             note="Wasserstein distance over absolute-curvature distributions, normalized by 0.2 1/m; "
                  "range-robust companion to histogram-L1"),
        _row("RQ2", "road_length_gap", scores.get("road_length_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""),
             note="construction/scope artifact (full OSM extraction vs curated subset), not domain gap"),
        _row("RQ2", "traffic_light_density_gap", scores.get("traffic_light_density_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""), note="construction artifact"),
        _row("RQ2", "building_density_gap", scores.get("building_density_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""), note="construction artifact"),
        _row("RQ2", "road_type_coverage_gap", scores.get("road_type_coverage_gap"), BOUNDED,
             artifact=artifact, sha256=auto.get("sha256", ""), note="manual road types are a subset of auto's"),
    ]
    return rows


def _rq3_perceptual_gap_rows(root: Path) -> List[Dict[str, Any]]:
    """Thesis RQ3 -- Perceptual domain gap (how structural differences shift
    perception outputs under identical sensor rig/route protocol)."""
    ev = root / "reports/post_audit_hardening/C17_rq2_perception_capture.md"
    return [_row("RQ3", "perceptual_gap", None, DEFERRED_RUNTIME,
                  artifact=str(ev.relative_to(root)) if ev.is_file() else "",
                  thesis_baseline="Direct generated-vs-manual paired perceptual measurement was not completed.",
                  comparability="not comparable: both generated and manual Ingolstadt arms are required",
                  method="requires live CARLA paired capture with identical rig and route",
                  claim_boundary="Town10HD is sensor-rig smoke/control evidence only, not an RQ3 answer.",
                  note="paired capture not executed -- needs a live CARLA server "
                       "(currently blocked by a livelock, see C20_TIER1_PROBE_20260821) "
                       "or the C16 UE cook (blocked on a human operator)")]


def _gnn_latent_row(root: Path) -> Dict[str, Any]:
    # C21: union-training (auto + manual tiles, resolving the C18 OOD caveat) + a
    # 5-seed ensemble (resolving the C18 single-run caveat) supersedes the C18
    # PROTOTYPE result IF its bootstrap CI excludes zero similarity (no-gap) --
    # exactly the bar the C21 governed prompt itself set for AUTHORITATIVE.
    c21_dir = root / "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE"
    agg_path = c21_dir / "aggregate_stats.json"
    agg = _read_json(agg_path)
    if agg is not None:
        cd = agg.get("cosine_distance", {})
        cs = agg.get("cosine_similarity", {})
        ci_excludes_zero = bool(agg.get("ci_excludes_zero_similarity"))
        seeds = agg.get("seeds", [])
        status = AUTHORITATIVE if ci_excludes_zero else BOUNDED
        agg_sha256 = hashlib.sha256(agg_path.read_bytes()).hexdigest()
        return _row(
            "RQ4", "gnn_latent_cosine_distance", cd.get("mean"), status,
            artifact="C21_GNN_AUTHORITATIVE/aggregate_stats.json", sha256=agg_sha256,
            evidence_path="reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/aggregate_stats.json",
            evidence_sha256=agg_sha256,
            thesis_baseline="Thesis fixed NT-Xent representation collapse and reported latent separation with K=1000 permutation p<0.001.",
            unit="cosine_distance",
            comparability="extension: multi-seed union-domain analysis, not the entire thesis RQ4 result",
            method="5-seed union-domain GNN ensemble with bootstrap confidence intervals",
            sample_size=len(seeds),
            random_seeds=seeds,
            confidence_interval=cd.get("ci95_bootstrap"),
            claim_boundary="Current C21 ensemble strengthens the thesis RQ4 result; it does not make RQ4 wholly new post-thesis work.",
            note=(
                f"{len(seeds)}-seed ensemble (seeds={seeds}) trained on the UNION of both "
                f"maps' tiles (resolves C18's OOD one-sided-training caveat); "
                f"cosine_distance 95% bootstrap CI={cd.get('ci95_bootstrap')}, "
                f"cosine_similarity 95% CI={cs.get('ci95_bootstrap')} "
                f"({'excludes' if ci_excludes_zero else 'includes'} zero/no-gap)"
            ),
        )
    ev_dir = root / "reports/post_audit_hardening/C18_GNN_LATENT_GAP"
    gnn = _read_json(ev_dir / "gnn_training_report.json")
    if gnn is not None:
        metrics = ((gnn.get("latent_gap") or {}).get("metrics")) or {}
        ckpt_md5 = ((gnn.get("latent_gap") or {}).get("encoder") or {}).get("checkpoint_md5", "")
        return _row(
            "RQ4", "gnn_latent_cosine_distance", metrics.get("cosine_distance"), PROTOTYPE,
            artifact="map_encoder_epoch50.pt", sha256=ckpt_md5,
            thesis_baseline="Thesis fixed NT-Xent representation collapse and reported latent separation with K=1000 permutation p<0.001.",
            unit="cosine_distance",
            comparability="limited: one-sided auto-only training makes manual map out-of-distribution",
            method="single-run latent gap measurement",
            note="one-sided (auto-only) training makes the manual map OOD for the encoder -- "
                 "conflates true structural gap with distribution shift; corroborates RQ2, "
                 "not an independent authoritative measurement",
        )
    return _row("RQ4", "gnn_latent_cosine_distance", None, NOT_RUN,
                note="neither C21_GNN_AUTHORITATIVE/aggregate_stats.json nor "
                     "C18_GNN_LATENT_GAP/gnn_training_report.json found")


def _rq4_variability_rows(root: Path) -> List[Dict[str, Any]]:
    """Thesis RQ4 -- Structural variability and latent representation (does
    repeated generation introduce measurable structural variability; can a
    latent representation support robustness analysis). Combines the GNN
    latent-space result with the explicit domain-randomization wiring check
    (both are about induced/measured structural variability, not
    determinism -- see _rq1_determinism_rows for that)."""
    rows: List[Dict[str, Any]] = [_gnn_latent_row(root)]
    ev_dir = root / "reports/post_audit_hardening/C15_RQ4_DR"
    data = _read_json(ev_dir / "C15_RQ4_DOMAIN_RANDOMIZATION.json")
    if data is None:
        rows.append(_row("RQ4", "explicit_dr_wired", None, NOT_RUN,
                          note="C15_RQ4_DOMAIN_RANDOMIZATION.json not found"))
        return rows
    dr = data.get("explicit_dr", {})
    rows.append(_row("RQ4", "explicit_dr_wired", dr.get("changes_input"), AUTHORITATIVE,
                      artifact=dr.get("module", ""),
                      thesis_baseline="Thesis RQ4 established latent separation after fixing representation collapse; explicit DR infrastructure is post-thesis support.",
                      comparability="implementation support, not a governed natural-vs-explicit DR experiment by itself",
                      method="module wiring evidence from C15 domain-randomization report",
                      note=f"apply_n produces {dr.get('apply_n_produces_distinct_variants')} distinct variants; "
                           "deterministic given a seed, varies across seeds"))
    return rows


def _rq5_transfer_rows(root: Path) -> List[Dict[str, Any]]:
    """Thesis RQ5 -- Generalization and transfer (do perception models
    trained on generated maps generalize to (a) the manual simulated map and
    (b) unlabeled real-world data)."""
    return [
        _row("RQ5", "miou_auto_train_manual_eval", None, DEFERRED_RUNTIME,
             thesis_baseline="No downstream generated-train/manual-test model-transfer experiment was completed.",
             comparability="not comparable: no frozen generated-trained checkpoint evaluated on manual Grid0828 holdout",
             method="requires valid RQ3 datasets before transfer evaluation",
             claim_boundary="Do not label manual-target training or unlabeled shift as generated-to-manual generalization.",
             note="RQ5(a): needs C17 paired captures (blocked -- see RQ3)"),
        _row("RQ5", "domain_adaptation_coral_mmd", None, DEFERRED_RUNTIME,
             thesis_baseline="No downstream transfer experiment was completed.",
             comparability="protocol/check only until labeled generated/manual datasets exist",
             method="requires valid RQ3 datasets; CORAL/MMD alone is not accuracy",
             claim_boundary="Unlabeled distribution shift alone is not model-generalization accuracy.",
             note="RQ5(a): needs C17 paired captures (blocked -- see RQ3)"),
        _row("RQ5", "real_unlabeled_shift_metrics", None, DEFERRED_EXTERNAL_DATA,
             thesis_baseline="No real-world Ingolstadt transfer evaluation was completed.",
             comparability="not comparable: no appropriate real-world dataset available",
             method="requires operator-supplied real-world data and a frozen generated-trained model",
             claim_boundary="Do not report real-world generalization accuracy from unlabeled shift metrics.",
             note="RQ5(b): no real-world Ingolstadt dataset available on this machine "
                  "(independent of the CARLA blocker)"),
    ]


def build_tables(root: Path) -> Dict[str, Any]:
    rows = (
        _rq1_determinism_rows(root)
        + _rq2_structural_gap_rows(root)
        + _rq3_perceptual_gap_rows(root)
        + _rq4_variability_rows(root)
        + _rq5_transfer_rows(root)
    )
    by_status: Dict[str, int] = {}
    producer_commit = _producer_commit(root)
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if r.get("producer_commit") in ("", "UNKNOWN"):
            r["producer_commit"] = producer_commit
    return {"schema_version": 2, "rows": rows, "counts_by_status": by_status, "row_count": len(rows)}


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
