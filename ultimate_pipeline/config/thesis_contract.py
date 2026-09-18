from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple


PERCEPTION_RESULT_PAIRED_INGOLSTADT = "paired_manual_vs_auto_ingolstadt"
PERCEPTION_RESULT_PROXY = "proxy_cross_map_comparison"
PERCEPTION_RESULT_SMOKE = "smoke_test_only"
PERCEPTION_RESULT_FAILED = "capture_failed"
PERCEPTION_RESULT_BOUNDED = "bounded_partial_result"

GENERALIZATION_STATUS_IMPLEMENTED = "implemented_pipeline_only"
GENERALIZATION_STATUS_DEFINED = "experiment_defined_not_executed"
GENERALIZATION_STATUS_PROTOTYPE = "prototype_result_only"
GENERALIZATION_STATUS_AUTHORITATIVE = "authoritative_result_available"
GENERALIZATION_STATUS_DEFERRED = "deferred"

VARIABILITY_CLASS_SAME_INPUT = "same_input_repeat_determinism"
VARIABILITY_CLASS_MULTI_MAP = "multi_map_variability_natural_randomization"

INGOLSTADT_MANUAL_TOWNS = {"grid0821", "grid0828"}
PROXY_MAP_TOKENS = {"town10", "town10hd", "town10hd_opt"}


def _norm_token(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/").lower()
    if not text:
        return ""
    if "/" in text:
        text = text.split("/")[-1]
    return text


def _contains_any_token(value: Any, tokens: Iterable[str]) -> bool:
    norm = str(value or "").strip().replace("\\", "/").lower()
    return any(token in norm for token in tokens)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return False


@dataclass(frozen=True)
class Classification:
    value: str
    reason: str


def classify_single_perception_result(
    *,
    success: Any,
    frames_recorded: Any,
    failure_reason: Any = None,
    manual_town: Any = None,
    auto_town: Any = None,
    expected_map_name: Any = None,
    xodr_in: Any = None,
    first_frame_received: Any = None,
    evidence_written: Any = None,
    sensors_attached: Any = None,
) -> Classification:
    ok = _is_true(success)
    frames = max(0, _as_int(frames_recorded))
    first_frame_ok = _is_true(first_frame_received) or frames > 0
    evidence_ok = _is_true(evidence_written)
    sensors_ok = sensors_attached is True
    failure = str(failure_reason or "").strip()

    if not ok:
        if frames > 0 or first_frame_ok:
            return Classification(
                PERCEPTION_RESULT_BOUNDED,
                "capture produced partial evidence but did not satisfy the success gate",
            )
        return Classification(
            PERCEPTION_RESULT_FAILED,
            failure or "capture failed before any usable frame evidence was recorded",
        )

    if not first_frame_ok or not sensors_ok or not evidence_ok:
        return Classification(
            PERCEPTION_RESULT_BOUNDED,
            "capture succeeded only partially; frame, sensor-attach, or evidence-pack completeness is missing",
        )

    if str(xodr_in or "").strip():
        return Classification(
            PERCEPTION_RESULT_SMOKE,
            "single-arm generated-map capture is smoke/runtime evidence only, not a paired Ingolstadt comparison",
        )

    if (
        _contains_any_token(expected_map_name, PROXY_MAP_TOKENS)
        or _contains_any_token(auto_town, PROXY_MAP_TOKENS)
        or _contains_any_token(manual_town, PROXY_MAP_TOKENS)
    ):
        return Classification(
            PERCEPTION_RESULT_PROXY,
            "capture targets a proxy built-in map rather than the paired Ingolstadt manual-vs-auto comparison",
        )

    if _norm_token(expected_map_name) in INGOLSTADT_MANUAL_TOWNS or _norm_token(manual_town) in INGOLSTADT_MANUAL_TOWNS:
        return Classification(
            PERCEPTION_RESULT_BOUNDED,
            "single-arm Ingolstadt capture exists, but pairing against the opposite arm is not proven in this artifact",
        )

    return Classification(
        PERCEPTION_RESULT_SMOKE,
        "capture is usable runtime evidence, but not a paired Ingolstadt comparison artifact",
    )


def classify_pair_perception_result(
    *,
    manual_town: Any,
    auto_town: Any = None,
    xodr_in: Any = None,
    manual_success: Any,
    auto_success: Any,
    manual_frames_recorded: Any = 0,
    auto_frames_recorded: Any = 0,
) -> Classification:
    manual_ok = _is_true(manual_success)
    auto_ok = _is_true(auto_success)
    manual_frames = max(0, _as_int(manual_frames_recorded))
    auto_frames = max(0, _as_int(auto_frames_recorded))
    manual_ingolstadt = _norm_token(manual_town) in INGOLSTADT_MANUAL_TOWNS
    proxy_auto = _contains_any_token(auto_town, PROXY_MAP_TOKENS)

    if manual_ok and auto_ok and manual_ingolstadt and str(xodr_in or "").strip():
        return Classification(
            PERCEPTION_RESULT_PAIRED_INGOLSTADT,
            "manual cooked Ingolstadt capture and auto-generated Ingolstadt XODR capture both succeeded in the same pair run",
        )

    if manual_ok and auto_ok and proxy_auto:
        return Classification(
            PERCEPTION_RESULT_PROXY,
            "pair run succeeded, but the auto arm targets a proxy map rather than generated Ingolstadt XODR",
        )

    if manual_ok or auto_ok or manual_frames > 0 or auto_frames > 0:
        return Classification(
            PERCEPTION_RESULT_BOUNDED,
            "pair run produced only one successful arm or partial frame evidence",
        )

    return Classification(
        PERCEPTION_RESULT_FAILED,
        "pair run did not produce a successful manual/auto capture pair",
    )


def infer_generalization_claim_status(
    *,
    results: Any,
    train_gen_datasets: Iterable[Any],
    train_manual_datasets: Iterable[Any],
    eval_manual_dataset: Any = None,
    real_u_dir: Any = None,
) -> Classification:
    result_list = list(results or [])
    gen_count = len(list(train_gen_datasets or []))
    manual_count = len(list(train_manual_datasets or []))
    eval_manual_present = bool(str(eval_manual_dataset or "").strip())
    real_u_present = bool(str(real_u_dir or "").strip())

    if not result_list:
        if gen_count == 0 and manual_count == 0 and not eval_manual_present and not real_u_present:
            return Classification(
                GENERALIZATION_STATUS_IMPLEMENTED,
                "generalization code exists, but no experiment inputs or outputs were supplied",
            )
        return Classification(
            GENERALIZATION_STATUS_DEFINED,
            "generalization experiment inputs were specified, but no result rows were produced",
        )

    sim_ok = False
    real_ok = False
    for result in result_list:
        if not isinstance(result, dict):
            continue
        sim_payload = result.get("sim")
        real_payload = result.get("real")
        if isinstance(sim_payload, dict) and (_is_true(sim_payload.get("ok")) or any(key in sim_payload for key in ("mIoU", "pixel_accuracy", "frames_count"))):
            sim_ok = True
        if isinstance(real_payload, dict) and (_is_true(real_payload.get("ok")) or any(key in real_payload for key in ("entropy_mean", "confidence_mean", "n"))):
            real_ok = True

    if sim_ok and real_ok and eval_manual_present and real_u_present:
        return Classification(
            GENERALIZATION_STATUS_AUTHORITATIVE,
            "both simulated-manual and real-unlabeled evaluation outputs are present in the result set",
        )

    if sim_ok or real_ok:
        return Classification(
            GENERALIZATION_STATUS_PROTOTYPE,
            "generalization outputs exist, but the full simulated-and-real evidence chain is incomplete",
        )

    return Classification(
        GENERALIZATION_STATUS_DEFERRED,
        "result rows exist without evaluable simulated/manual or real-unlabeled evidence",
    )


def infer_generalization_component_statuses(
    *,
    results: Any,
    eval_manual_dataset: Any = None,
    real_u_dir: Any = None,
) -> Dict[str, Classification]:
    result_list = list(results or [])
    eval_manual_present = bool(str(eval_manual_dataset or "").strip())
    real_u_present = bool(str(real_u_dir or "").strip())

    sim_ok = False
    real_ok = False
    for result in result_list:
        if not isinstance(result, dict):
            continue
        sim_payload = result.get("sim")
        real_payload = result.get("real")
        if isinstance(sim_payload, dict) and (
            _is_true(sim_payload.get("ok"))
            or any(key in sim_payload for key in ("mIoU", "pixel_accuracy", "frames_count"))
        ):
            sim_ok = True
        if isinstance(real_payload, dict) and (
            _is_true(real_payload.get("ok"))
            or any(key in real_payload for key in ("entropy_mean", "confidence_mean", "n"))
        ):
            real_ok = True

    if sim_ok and eval_manual_present:
        simulated_status = Classification(
            GENERALIZATION_STATUS_AUTHORITATIVE,
            "simulated/manual evaluation outputs are present for the configured evaluation dataset",
        )
    elif sim_ok:
        simulated_status = Classification(
            GENERALIZATION_STATUS_PROTOTYPE,
            "simulated/manual metrics exist, but evaluation-dataset provenance is incomplete",
        )
    elif eval_manual_present:
        simulated_status = Classification(
            GENERALIZATION_STATUS_DEFINED,
            "a simulated/manual evaluation dataset was configured, but no evaluable output was produced",
        )
    else:
        simulated_status = Classification(
            GENERALIZATION_STATUS_IMPLEMENTED,
            "simulated/manual evaluation code exists, but no evaluation dataset was configured",
        )

    if real_ok and real_u_present:
        real_status = Classification(
            GENERALIZATION_STATUS_AUTHORITATIVE,
            "real-unlabeled evaluation outputs are present for the configured real-world image directory",
        )
    elif real_ok:
        real_status = Classification(
            GENERALIZATION_STATUS_PROTOTYPE,
            "real-unlabeled metrics exist, but the configured real-world input provenance is incomplete",
        )
    elif real_u_present:
        real_status = Classification(
            GENERALIZATION_STATUS_DEFINED,
            "a real-unlabeled evaluation directory was configured, but no evaluable output was produced",
        )
    else:
        real_status = Classification(
            GENERALIZATION_STATUS_IMPLEMENTED,
            "real-unlabeled evaluation code exists, but no real-world input directory was configured",
        )

    paired_ingolstadt_status = Classification(
        GENERALIZATION_STATUS_DEFERRED,
        "this report does not encode explicit paired Ingolstadt provenance strongly enough to support a simulated Ingolstadt generalization claim",
    )
    if sim_ok and real_ok and eval_manual_present and real_u_present:
        paired_ingolstadt_status = Classification(
            GENERALIZATION_STATUS_PROTOTYPE,
            "simulated and real evaluation outputs exist, but paired Ingolstadt provenance still requires a stronger authoritative artifact chain",
        )

    return {
        "simulated_manual_eval": simulated_status,
        "real_unlabeled_eval": real_status,
        "paired_ingolstadt_generalization": paired_ingolstadt_status,
    }


def classify_variability_experiment(
    *,
    same_input_repeat: bool,
    multiple_maps: bool,
) -> Classification:
    if same_input_repeat:
        return Classification(
            VARIABILITY_CLASS_SAME_INPUT,
            "repeated conversion of the same OSM input measures determinism/noise, not multi-map natural randomization",
        )
    if multiple_maps:
        return Classification(
            VARIABILITY_CLASS_MULTI_MAP,
            "multiple generated maps are being compared as a variability/randomization experiment class",
        )
    return Classification(
        VARIABILITY_CLASS_SAME_INPUT,
        "experiment class is unspecified; defaulting conservatively to same-input determinism",
    )


def build_visual_qa_contract(
    *,
    world_loaded: Any,
    correct_world_identity: Any,
    ego_spawned: Any,
    thesis_sensor_attached: Any,
    first_frame_received: Any,
    evidence_written: Any,
    runtime_verified: Any,
    visual_smoke_gate_ok: Any = None,
    visual_smoke_gate_required: Any = False,
) -> Dict[str, Any]:
    visual_required = _is_true(visual_smoke_gate_required)
    visual_ok = (
        _is_true(visual_smoke_gate_ok)
        if visual_smoke_gate_ok is not None
        else False
    )
    payload = {
        "world_loaded": bool(world_loaded),
        "correct_world_identity": bool(correct_world_identity),
        "ego_spawned": bool(ego_spawned),
        "thesis_sensor_attached": bool(thesis_sensor_attached),
        "first_frame_received": bool(first_frame_received),
        "evidence_written": bool(evidence_written),
        "runtime_verified": bool(runtime_verified),
        "visual_smoke_gate_required": bool(visual_required),
        "visual_smoke_gate_ok": bool(visual_ok),
    }
    required_keys = [
        "world_loaded",
        "correct_world_identity",
        "ego_spawned",
        "thesis_sensor_attached",
        "first_frame_received",
        "evidence_written",
    ]
    if visual_required:
        required_keys.append("visual_smoke_gate_ok")
    payload["ok"] = all(payload[key] for key in required_keys)
    if payload["ok"]:
        payload["status"] = "authoritative_result_available"
    elif visual_required and not visual_ok:
        payload["status"] = "blocked_until_visual_qa_passes"
    elif payload["runtime_verified"]:
        payload["status"] = "bounded_partial_result"
    else:
        payload["status"] = "missing_runtime_evidence"
    return payload
