from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ultimate_pipeline.config.thesis_contract import (
    PERCEPTION_RESULT_BOUNDED,
    PERCEPTION_RESULT_FAILED,
    PERCEPTION_RESULT_PAIRED_INGOLSTADT,
    PERCEPTION_RESULT_PROXY,
    PERCEPTION_RESULT_SMOKE,
    classify_variability_experiment,
)
from ultimate_pipeline.config.thesis_rq_contract import ALL_RQS, metric_allowed_for_rq


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _read_json_dict(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _contains(path: Path, needle: str) -> bool:
    return needle in _read_text(path)


def _find_run11_source(repo_root: Path) -> Path | None:
    # Portable, repo-relative resolution only. A previous version added a
    # `repo_root.parent / "carla_-main" / ...` sibling fallback that hard-coded
    # this dev machine's checkout directory name and would silently mis-resolve
    # (or no-op) on any other clone or CI runner; removed for portability.
    local = repo_root / "thesis_results" / "structural_gap_v1" / "run_11"
    if local.is_dir():
        return local
    return None


def _bool(value: Any) -> bool:
    return bool(value)


# run_11 (thesis_results/structural_gap_v1/run_11) has been superseded as the
# *canonical RQ2 structural-domain-gap result* by the legacy-named C14 artifact
# (reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/),
# which carries a provenanced whole-map gap, a curvature-sampling fix, and a
# local-registration refinement (auto map cropped to Grid0828's footprint, revealing
# the real 4.5-6x road-network-completeness gap the whole-map view obscured as scope).
# This does NOT affect thesis_results/structural_gap_v1/run_11/alignment.json or
# auto_aligned_rigid.xodr as inputs to run_full_domain_gap.py's
# use_authoritative_alignment_bundle short-circuit -- that is a separate, file-gated
# alignment-cache consumer of the same directory, untouched by this supersession.
RUN11_SUPERSEDED_BY = "C14_RQ1_STRUCTURAL_GAP"
RUN11_SUPERSEDED_BY_DETAIL = (
    "RQ2's canonical structural-domain-gap result is now reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/ "
    "(C14_RQ1_REPORT.md, manual_vs_auto.json, curvature_recompute.json, "
    "local_registration.json). run_11's missing-provenance flags below describe the "
    "legacy artifact only and are not an unaddressed gap in the current RQ2 structural result; see "
    "unresolved_or_unverified for the explicit resolution record."
)


def _main_payload(repo_root: Path) -> Dict[str, Any]:
    source_run11 = _find_run11_source(repo_root)
    governed_run11 = repo_root / "thesis_results" / "structural_gap_v1" / "run_11"

    run11_addendum = _read_json_dict(governed_run11 / "run_11_audit_addendum.json")
    supplementary = _read_json_dict(governed_run11 / "supplementary_metrics.json")
    elevation = _read_json_dict(governed_run11 / "elevation_stats_auto.json")

    run_perception_safe = repo_root / "ultimate_pipeline" / "tools" / "run_perception_safe.py"
    run_perception_pair = repo_root / "ultimate_pipeline" / "tools" / "run_perception_pair.py"
    run_generalization = repo_root / "ultimate_pipeline" / "run_generalization_experiments.py"
    thesis_sensor_rig = repo_root / "ultimate_pipeline" / "carla_tools" / "thesis_sensor_rig.py"
    transform_conventions = repo_root / "ultimate_pipeline" / "sensors" / "transform_conventions.py"
    map_only_probe = repo_root / "ultimate_pipeline" / "tools" / "map_only_probe.py"

    same_input = classify_variability_experiment(
        same_input_repeat=True,
        multiple_maps=False,
    )
    multi_map = classify_variability_experiment(
        same_input_repeat=False,
        multiple_maps=True,
    )

    fit_metric_provenance = supplementary.get("fit_metric_provenance", {})
    conservative = run11_addendum.get("conservative_interpretation", {})
    coverage_context = run11_addendum.get("coverage_context", supplementary.get("coverage_context", {}))
    elevation_context = run11_addendum.get("elevation_context", {})

    unresolved: list[Dict[str, Any]] = []
    source_revision_status = str(
        fit_metric_provenance.get("exact_source_revision_status") or ""
    )
    if source_revision_status in {"conflicting", "unverified"}:
        unresolved.append(
            {
                "topic": "run11_fit_metric_provenance",
                "status": source_revision_status,
                "detail": fit_metric_provenance.get("producer_provenance_summary", ""),
            }
        )

    visual_qa_status = "missing_runtime_evidence"
    unresolved.append(
        {
            "topic": "visual_qa_runtime_verification_this_pass",
            "status": visual_qa_status,
            "detail": "Code-path contract exists, but no CARLA runtime probe was executed in this reconciliation pass.",
        }
    )

    # run_11's missing-provenance flags (source_available, governed_addenda,
    # coverage_context_present, fit_metric_exact_source_revision_status, etc.) are a
    # real, honestly-reported fact about the legacy artifact on this machine -- but
    # they must not be reported as a silent, unaddressed gap now that C14 is the
    # canonical RQ2 structural result. Record the resolution explicitly rather than omitting
    # run_11 from the unresolved list.
    unresolved.append(
        {
            "topic": "run11_provenance_gap",
            "status": "resolved_via_supersession",
            "detail": (
                f"run_11's unprovenanced legacy fields (source_available, governed_addenda, "
                f"coverage_context_present, fit_metric_exact_source_revision_status) are resolved "
                f"via supersession, not by re-provenancing run_11 itself. {RUN11_SUPERSEDED_BY_DETAIL}"
            ),
        }
    )

    return {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": repo_root.as_posix(),
        "run11": {
            "superseded_by": RUN11_SUPERSEDED_BY,
            "superseded_by_detail": RUN11_SUPERSEDED_BY_DETAIL,
            "source_dir": source_run11.as_posix() if source_run11 else "",
            "source_available": bool(source_run11),
            "governed_addenda": {
                "run_11_audit_addendum_json": (governed_run11 / "run_11_audit_addendum.json").is_file(),
                "supplementary_metrics_json": (governed_run11 / "supplementary_metrics.json").is_file(),
                "elevation_stats_auto_json": (governed_run11 / "elevation_stats_auto.json").is_file(),
            },
            "addendum_parsed": bool(run11_addendum),
            "supplementary_metrics_parsed": bool(supplementary),
            "elevation_stats_parsed": bool(elevation),
            "fit_metric_primary_safe_conclusion": fit_metric_provenance.get("verified_safe_conclusion", ""),
            "fit_metric_exact_source_revision_status": source_revision_status or "missing",
            "true_divergence_supported": _bool(fit_metric_provenance.get("true_divergence_supported", False)),
            "coverage_context": coverage_context,
            "conservative_interpretation": conservative,
            "elevation_context": elevation_context,
            "coverage_context_present": all(
                key in coverage_context
                for key in (
                    "auto_road_length_m",
                    "manual_road_length_m",
                    "coverage_ratio_auto_to_manual",
                    "bbox_iou_after_reprojection",
                )
            ),
            "full_network_vs_local_claim_boundary_present": _bool(
                conservative.get("full_network_metrics_do_not_equal_local_registration_quality")
                or supplementary.get("interpretation_contract", {}).get(
                    "full_network_metrics_do_not_equal_local_registration_quality"
                )
            ),
        },
        "calibration_contract": {
            "validation_method_present": _contains(thesis_sensor_rig, "_validate_loaded_calibration_contract"),
            "camera_uses_K_undistortion": _contains(thesis_sensor_rig, "K_undistortion"),
            "camera_image_size_enforced": _contains(thesis_sensor_rig, "_parse_image_size"),
            "camera_cTv_direct_enforced": (
                _contains(thesis_sensor_rig, "ctv_invert=False")
                and _contains(transform_conventions, "Non-canonical camera cTv inversion requested")
            ),
            "lidar_vTl_inversion_enforced": _contains(transform_conventions, "np.linalg.inv(T_lidar_vehicle)"),
        },
        "perception_labels": {
            "supported_result_classes": [
                PERCEPTION_RESULT_PAIRED_INGOLSTADT,
                PERCEPTION_RESULT_PROXY,
                PERCEPTION_RESULT_SMOKE,
                PERCEPTION_RESULT_FAILED,
                PERCEPTION_RESULT_BOUNDED,
            ],
            "single_arm_result_class_present": _contains(run_perception_safe, "\"result_class\""),
            "pair_result_class_present": _contains(run_perception_pair, "\"result_class\""),
            "pair_result_reason_present": _contains(run_perception_pair, "\"result_class_reason\""),
            "visual_qa_contract_present": _contains(run_perception_safe, "visual_qa_contract.json"),
        },
        "generalization_status": {
            "machine_readable_status_present": _contains(run_generalization, "generalization_status.json"),
            "overall_status_enum_present": _contains(run_generalization, "generalization_claim_status"),
            "component_status_fields_present": (
                _contains(run_generalization, "simulated_manual_eval_status")
                and _contains(run_generalization, "real_unlabeled_eval_status")
                and _contains(run_generalization, "paired_ingolstadt_generalization_status")
            ),
            "claim_boundary_present": _contains(
                run_generalization,
                "Do not claim simulated Ingolstadt or real-world unlabeled generalization",
            ),
        },
        "variability_experiment_classes": {
            "same_input_repeat": {
                "value": same_input.value,
                "reason": same_input.reason,
            },
            "multi_map_variability": {
                "value": multi_map.value,
                "reason": multi_map.reason,
            },
            "separation_status": "explicit_machine_readable_labels_available",
        },
        "visual_qa_contract": {
            "probe_world_loaded_key_present": _contains(map_only_probe, "\"world_loaded\""),
            "probe_world_identity_key_present": _contains(map_only_probe, "\"correct_world_identity\""),
            "capture_visual_contract_path": "perception_status.json + visual_qa_contract.json",
            "runtime_verified_this_pass": False,
            "runtime_verification_status": visual_qa_status,
        },
        "unresolved_or_unverified": unresolved,
    }


def _current_rq_tables_audit(repo_root: Path) -> Dict[str, Any]:
    """C19 step 2 (current era) -- audit the C12-C18 evidence via the C19
    step-1 export, independent of the legacy run11/thesis_sensor_rig checks
    above (which predate the C6-C20 remediation arc and audit a different,
    older evidence layout). Fails closed: any row missing an explicit
    status, or no-claim rows lacking a stated deferral reason, is
    reported as a contract violation rather than silently passing.
    """
    rq_tables_path = repo_root / "reports" / "post_audit_hardening" / "C19_THESIS_ASSEMBLY" / "rq_tables.json"
    rq_tables = _read_json_dict(rq_tables_path)
    if not rq_tables:
        return {
            "rq_tables_found": False,
            "rq_tables_path": rq_tables_path.as_posix(),
            "violations": ["rq_tables.json not found -- run tools/export_thesis_tables.py first"],
        }

    valid_statuses = {
        "AUTHORITATIVE",
        "BOUNDED",
        "PROTOTYPE",
        "DEFERRED_RUNTIME",
        "DEFERRED_EXTERNAL_DATA",
        "SUPERSEDED",
        "NOT_RUN",
    }
    no_claim_statuses = {"DEFERRED_RUNTIME", "DEFERRED_EXTERNAL_DATA", "NOT_RUN"}
    violations: list[str] = []
    rows = rq_tables.get("rows", [])
    for row in rows:
        status = row.get("status")
        rq = row.get("rq")
        metric = row.get("metric")
        if status not in valid_statuses:
            violations.append(f"row {rq}/{metric}: invalid or missing status {status!r}")
        if status in no_claim_statuses and not str(row.get("note") or "").strip():
            violations.append(f"row {rq}/{metric}: {status} with no reason given")
        # Metric->RQ semantic check (ultimate_pipeline.config.thesis_rq_contract):
        # this is what would have caught the 2026-09 RQ-numbering drift, where
        # every row had a valid status but the wrong RQ number for its content.
        if not metric_allowed_for_rq(rq, metric):
            violations.append(
                f"row {rq}/{metric}: metric not in the allowed set for {rq} "
                "(check for RQ-label drift against ultimate_pipeline.config.thesis_rq_contract)"
            )

    # RQ numbers here follow the actual submitted thesis (submission/thesis_source/
    # Chapter1/chap1.tex): RQ1=determinism, RQ2=structural gap, RQ3=perceptual gap,
    # RQ4=structural variability/latent representation, RQ5=generalization/transfer.
    # export_thesis_tables.py used a drifted numbering (structural gap as "RQ1",
    # perceptual gap as "RQ2", GNN work as "RQ3/RQ5") until this was corrected
    # 2026-09-06 -- every row now carries a single, correct, standalone tag, so no
    # combined-tag special-casing is needed here anymore.
    rq_covered = {row.get("rq") for row in rows}
    missing_rq_coverage = ALL_RQS - rq_covered
    if missing_rq_coverage:
        violations.append(f"RQs with zero rows: {sorted(missing_rq_coverage)}")

    return {
        "rq_tables_found": True,
        "rq_tables_path": rq_tables_path.as_posix(),
        "row_count": len(rows),
        "counts_by_status": rq_tables.get("counts_by_status", {}),
        "violations": violations,
        "ok": not violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit whether the repo exposes conservative thesis-topic contract outputs."
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    repo_root = _repo_root()
    payload = _main_payload(repo_root)
    payload["current_rq_tables_audit"] = _current_rq_tables_audit(repo_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
