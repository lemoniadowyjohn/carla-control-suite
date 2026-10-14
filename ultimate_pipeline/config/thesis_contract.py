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

# NEW-239: RQ5 splits into two independent claim families. Unlabeled real-world
# data cannot support a generalization-accuracy claim (no labels => no mIoU), so
# it gets its own authoritative scope that is explicitly about domain shift.
GENERALIZATION_RQ5A = "rq5a_simulated_transfer"
GENERALIZATION_RQ5B_SHIFT = "rq5b_real_unlabeled_shift"
GENERALIZATION_RQ5B_ACCURACY = "rq5b_real_generalization_accuracy_deferred_labels"

#: Claim families a real-unlabeled result may be reported under.
REAL_UNLABELED_AUTHORITATIVE_SCOPE = GENERALIZATION_RQ5B_SHIFT

#: Minimum decoded real-world images for real-unlabeled evidence to be admissible
#: (NEW-241). Evidence requires ``n > REAL_UNLABELED_MIN_IMAGES``.
REAL_UNLABELED_MIN_IMAGES = 1

#: Minimum paired labeled frames for labeled-sim evidence to be admissible
#: (NEW-240). Evidence requires ``frames_count >= SIM_LABELED_MIN_FRAMES``.
SIM_LABELED_MIN_FRAMES = 1

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


def _is_present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _has_error(payload: Dict[str, Any]) -> bool:
    """True when a result payload records any error condition.

    NEW-238: a payload carrying an error is never admissible evidence, even when
    its metric keys are present. ``ok: false`` plus ``mIoU: 0.0`` is a failed
    evaluation, not a measurement.
    """
    if not _is_present(payload.get("error")):
        errors = payload.get("errors")
        if isinstance(errors, (list, tuple)) and len(errors) > 0:
            return True
    if "ok" in payload and not _is_true(payload.get("ok")):
        return True
    status = payload.get("status")
    if status is not None and str(status).strip().lower() not in {"ok", "success", "succeeded", "pass", "passed"}:
        return True
    return False


def _labeled_sim_evidence_is_valid(payload: Any) -> bool:
    """
    NEW-238: strict admissibility for labeled simulated evaluation evidence.

    All of the following must hold:
      * the payload is a dict with no error condition and a successful status;
      * a positive ``frames_count`` meets the governed minimum;
      * ``mIoU`` is present and is a real number (not null);
      * the evaluated model and dataset are identified.
    """
    if not isinstance(payload, dict):
        return False
    if _has_error(payload):
        return False
    try:
        frames = int(payload.get("frames_count") or 0)
    except (TypeError, ValueError):
        return False
    if frames < SIM_LABELED_MIN_FRAMES:
        return False
    miou = payload.get("mIoU")
    if not isinstance(miou, (int, float)) or isinstance(miou, bool):
        return False
    if not _is_present(payload.get("model")):
        return False
    if not _is_present(payload.get("dataset")):
        return False
    return True


def _real_unlabeled_evidence_is_valid(payload: Any) -> bool:
    """
    NEW-238 / NEW-241: strict admissibility for real-unlabeled shift evidence.

    Same failure rules as labeled evidence, plus a positive image count above the
    governed minimum. An empty directory reporting ``{"n": 0, "entropy_mean":
    null}`` is inadmissible.
    """
    if not isinstance(payload, dict):
        return False
    if _has_error(payload):
        return False
    try:
        n = int(payload.get("n") or 0)
    except (TypeError, ValueError):
        return False
    if n <= REAL_UNLABELED_MIN_IMAGES:
        return False
    if payload.get("entropy_mean") is None or payload.get("confidence_mean") is None:
        return False
    return True


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
        if _labeled_sim_evidence_is_valid(result.get("sim")):
            sim_ok = True
        if _real_unlabeled_evidence_is_valid(result.get("real")):
            real_ok = True

    if sim_ok and real_ok and eval_manual_present and real_u_present:
        # NEW-239: the aggregate status names both authoritative claim families
        # rather than a single undifferentiated "generalization" claim. Only the
        # simulated half supports an accuracy result; the real-unlabeled half
        # supports domain-shift analysis only.
        return Classification(
            GENERALIZATION_STATUS_AUTHORITATIVE,
            (
                f"authoritative evidence exists for {GENERALIZATION_RQ5A} (labeled simulated "
                f"transfer) and {GENERALIZATION_RQ5B_SHIFT} (unlabeled real-world domain shift); "
                f"{GENERALIZATION_RQ5B_ACCURACY} remains deferred because the real-world data is "
                "unlabeled and cannot yield mIoU or pixel accuracy"
            ),
        )

    if sim_ok:
        return Classification(
            GENERALIZATION_STATUS_PROTOTYPE if real_u_present else GENERALIZATION_STATUS_AUTHORITATIVE,
            (
                f"authoritative labeled-simulated transfer evidence exists for {GENERALIZATION_RQ5A}, "
                f"but {GENERALIZATION_RQ5B_SHIFT} evidence is not yet admissible"
                if real_u_present
                else f"authoritative labeled-simulated transfer evidence exists for {GENERALIZATION_RQ5A}"
            ),
        )

    if real_ok:
        return Classification(
            GENERALIZATION_STATUS_PROTOTYPE if eval_manual_present else GENERALIZATION_STATUS_AUTHORITATIVE,
            (
                f"authoritative unlabeled real-world domain-shift evidence exists for "
                f"{GENERALIZATION_RQ5B_SHIFT}; this does NOT support a generalization-accuracy "
                f"claim -- {GENERALIZATION_RQ5B_ACCURACY} is deferred because the real-world data "
                "carries no labels"
            ),
        )

    return Classification(
        GENERALIZATION_STATUS_DEFERRED,
        (
            "result rows exist but none satisfy the governed evidence requirements: no error-free "
            f"labeled-simulated evaluation with >= {SIM_LABELED_MIN_FRAMES} frames, and no "
            f"error-free real-unlabeled evaluation with more than {REAL_UNLABELED_MIN_IMAGES} "
            "decoded image(s)"
        ),
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
        if _labeled_sim_evidence_is_valid(result.get("sim")):
            sim_ok = True
        if _real_unlabeled_evidence_is_valid(result.get("real")):
            real_ok = True

    if sim_ok and eval_manual_present:
        simulated_status = Classification(
            GENERALIZATION_STATUS_AUTHORITATIVE,
            (
                f"an error-free labeled-simulated evaluation with an identified model and "
                f"dataset is present; authoritative for {GENERALIZATION_RQ5A} only"
            ),
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
            (
                f"an error-free unlabeled real-world evaluation with more than "
                f"{REAL_UNLABELED_MIN_IMAGES} decoded image(s) is present; authoritative for "
                f"{GENERALIZATION_RQ5B_SHIFT} (domain shift) ONLY. It supports no accuracy or "
                f"generalization-performance claim: {GENERALIZATION_RQ5B_ACCURACY}."
            ),
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

    # NEW-239: real-world generalization *accuracy* is only ever authoritative if
    # labeled real-world evidence exists. Unlabeled real data is shift evidence
    # and nothing more, so this component stays deferred by construction.
    real_accuracy_status = Classification(
        GENERALIZATION_STATUS_DEFERRED,
        (
            "no labeled real-world evaluation is configured; unlabeled real data cannot produce "
            f"mIoU or pixel accuracy, so {GENERALIZATION_RQ5B_ACCURACY} cannot be claimed"
        ),
    )
    if eval_manual_present and sim_ok:
        real_accuracy_status = Classification(
            GENERALIZATION_STATUS_DEFINED,
            (
                "an authorized labeled manual evaluation is configured and ran, but this contract "
                f"receives no labeled real-world evaluation payload, so {GENERALIZATION_RQ5B_ACCURACY} "
                "remains deferred rather than being inferred from simulated metrics"
            ),
        )

    return {
        "simulated_manual_eval": simulated_status,
        "real_unlabeled_eval": real_status,
        "real_world_generalization_accuracy": real_accuracy_status,
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
