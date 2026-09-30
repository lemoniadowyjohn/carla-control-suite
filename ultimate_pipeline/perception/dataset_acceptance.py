"""Dataset promotion contract (section 22 + 25) and label-quality gate (26).

A captured dataset may become ``TRAINING_DATASET_READY`` only when **every**
gate passes.  No single boolean from ``run_perception_safe`` may promote a
dataset on its own.

Also implements the immutable-reuse rule (NEW-225): existing data may be reused
only when its immutable receipt matches the current request, and old provenance
is never rewritten to match a current invocation.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

TRAINING_DATASET_READY = "TRAINING_DATASET_READY"
NOT_READY = "NOT_READY"
REUSE_AUTHORISED = "REUSE_AUTHORISED"

ACCEPTANCE_FILENAME = "DATASET_ACCEPTANCE.json"

#: The complete ordered gate list.  Every gate must be PASS.
GATE_ORDER: Tuple[str, ...] = (
    "map_identity",
    "runtime_stability",
    "sensor_canary",
    "full_required_rig",
    "calibration_contract",
    "route_contract",
    "frame_synchronization",
    "requested_frame_completeness",
    "writer_integrity",
    "semantic_label_quality",
    "no_stale_files",
    "no_queue_drops",
    "dataset_manifest",
    "software_provenance",
)

PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT_RUN"
BLOCKED = "BLOCKED"


def sha256_file(path: Any) -> str:
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def canonical_digest(payload: Any) -> str:
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


# ---------------------------------------------------------------------------
# Immutable reuse receipt (NEW-225)
# ---------------------------------------------------------------------------

RECEIPT_FIELDS: Tuple[str, ...] = (
    "map_or_xodr_sha256",
    "runtime_map_fingerprint",
    "route_sha256",
    "calibration_sha256",
    "rig_sha256",
    "weather_sha256",
    "capture_config_sha256",
    "software_sha256",
    "dataset_sha256",
)


def build_reuse_receipt(**identities: Any) -> Dict[str, Any]:
    receipt = {field: identities.get(field) for field in RECEIPT_FIELDS}
    receipt["schema"] = "IMMUTABLE_CAPTURE_RECEIPT/v1"
    receipt["receipt_digest"] = canonical_digest(
        {k: receipt[k] for k in RECEIPT_FIELDS}
    )
    receipt["built_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return receipt


def compare_reuse_receipt(
    stored: Mapping[str, Any], current: Mapping[str, Any]
) -> Dict[str, Any]:
    """Compare an existing immutable receipt with the current request."""
    mismatches: List[str] = []
    details: Dict[str, Any] = {}
    for field in RECEIPT_FIELDS:
        left = (stored or {}).get(field)
        right = (current or {}).get(field)
        equal = (left == right) or (left is None and right is None)
        details[field] = {"stored": left, "current": right, "equal": bool(equal)}
        if not equal:
            mismatches.append(field)
    stored_digest = (stored or {}).get("receipt_digest")
    current_digest = (current or {}).get("receipt_digest")
    if stored_digest and current_digest and stored_digest != current_digest:
        mismatches.append("receipt_digest")
    return {
        "schema": "REUSE_RECEIPT_COMPARISON/v1",
        "match": not mismatches,
        "mismatched_fields": sorted(set(mismatches)),
        "details": details,
        "policy": (
            "Never rewrite old provenance to match a current invocation; a "
            "mismatch simply means the data may not be reused."
        ),
    }


def authorise_reuse(
    *,
    stored_receipt: Optional[Mapping[str, Any]],
    current_request: Mapping[str, Any],
) -> Dict[str, Any]:
    if not stored_receipt:
        return {
            "status": NOT_READY,
            "reason": "no_immutable_receipt_present",
            "comparison": None,
        }
    comparison = compare_reuse_receipt(stored_receipt, current_request)
    if not comparison["match"]:
        return {
            "status": NOT_READY,
            "reason": f"receipt_mismatch:{','.join(comparison['mismatched_fields'])}",
            "comparison": comparison,
        }
    return {"status": REUSE_AUTHORISED, "reason": "immutable_receipt_matches", "comparison": comparison}


# ---------------------------------------------------------------------------
# Label quality gate (section 26)
# ---------------------------------------------------------------------------


def evaluate_label_quality(
    raw_ids: Iterable[Any],
    *,
    class_names: Optional[Sequence[str]] = None,
    unlabeled_ids: Sequence[int] = (255,),
    dominant_threshold: float = 0.90,
    degenerate_threshold: float = 0.98,
) -> Dict[str, Any]:
    """Raw measurements and policy verdict are reported **separately**.

    Rare-but-valid scenes are not auto-rejected: ``policy_verdict`` is advisory
    unless a policy explicitly flips ``reject``.
    """
    values: List[int] = []
    for item in raw_ids:
        try:
            values.append(int(item))
        except Exception:
            continue

    total = len(values)
    stats: Dict[str, Any] = {"n": total}
    if total == 0:
        return {
            "schema": "LABEL_QUALITY/v1",
            "measurements": {"n": 0},
            "policy_verdict": {"status": FAIL, "reject": False, "reasons": ["no_pixels"]},
            "note": "Raw measurements and policy verdict reported separately.",
        }

    counts: Dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1

    unlabeled_set = set(int(x) for x in unlabeled_ids)
    unlabeled_count = sum(counts.get(k, 0) for k in unlabeled_set)
    labelled_total = total - unlabeled_count
    dominant_id, dominant_count = max(counts.items(), key=lambda kv: kv[1])
    dominant_fraction = dominant_count / total

    class_ids = sorted(i for i in counts if i not in unlabeled_set)
    coverage = {
        str(cid): {
            "count": counts[cid],
            "fraction": counts[cid] / total,
            "name": (class_names[cid] if class_names and cid < len(class_names) else None),
        }
        for cid in class_ids
    }
    degenerate_frames = 0
    if dominant_fraction >= degenerate_threshold:
        degenerate_frames = 1
    degenerate_fraction = degenerate_frames / 1

    reasons: List[str] = []
    if labelled_total == 0:
        reasons.append("all_pixels_unlabeled")
    if dominant_fraction >= dominant_threshold:
        reasons.append(f"dominant_class_fraction={dominant_fraction:.4f}")
    if degenerate_fraction > 0:
        reasons.append(f"degenerate_frame_fraction={degenerate_fraction:.4f}")
    if class_names and len(class_ids) < len(class_names):
        missing = sorted(set(range(len(class_names))) - set(class_ids))
        reasons.append(f"class_coverage_incomplete:missing={missing}")

    # Advisory policy: never auto-reject a rare-but-valid scene.
    reject = False
    policy_status = PASS
    if labelled_total == 0:
        reject = True
        policy_status = FAIL

    return {
        "schema": "LABEL_QUALITY/v1",
        "measurements": {
            "n": total,
            "class_distribution": {str(k): v for k, v in sorted(counts.items())},
            "class_coverage": coverage,
            "labelled_pixels": labelled_total,
            "unlabeled_fraction": unlabeled_count / total,
            "dominant_class_id": dominant_id,
            "dominant_class_fraction": dominant_fraction,
            "degenerate_frame_fraction": degenerate_fraction,
            "degenerate_frame_count": degenerate_frames,
        },
        "policy_verdict": {
            "status": policy_status,
            "reject": reject,
            "reasons": reasons,
            "dominant_threshold": dominant_threshold,
            "degenerate_threshold": degenerate_threshold,
        },
        "note": (
            "Rare valid scenes are not automatically rejected; raw measurements "
            "and the policy verdict are reported separately."
        ),
    }


def label_quality_from_files(
    label_paths: Sequence[Any],
    *,
    class_names: Optional[Sequence[str]] = None,
    sample_limit: int = 50,
) -> Dict[str, Any]:
    """Best-effort measurement over real label files (PNG class-ID maps)."""
    import numpy as np

    from ultimate_pipeline.perception.label_quality import label_stats  # noqa: F401

    all_ids: List[int] = []
    frames_measured = 0
    degenerate_frames = 0
    frame_fractions: List[float] = []

    for path in list(label_paths)[: max(0, int(sample_limit))]:
        try:
            from PIL import Image  # type: ignore

            array = np.array(Image.open(str(path)))
        except Exception:
            continue
        flat = array.reshape(-1)
        if flat.size == 0:
            continue
        frames_measured += 1
        ids = [int(x) for x in np.unique(flat)]
        all_ids.extend(int(x) for x in flat[:: max(1, flat.size // 20000)])
        counts: Dict[int, int] = {}
        for value in flat.tolist():
            counts[int(value)] = counts.get(int(value), 0) + 1
        top = max(counts.values()) / flat.size
        frame_fractions.append(float(top))
        if top >= 0.98:
            degenerate_frames += 1

    if frames_measured == 0:
        return {
            "schema": "LABEL_QUALITY/v1",
            "measurements": {"n": 0, "frames_measured": 0},
            "policy_verdict": {"status": FAIL, "reject": False, "reasons": ["no_label_files_readable"]},
        }

    quality = evaluate_label_quality(all_ids, class_names=class_names)
    quality["measurements"]["frames_measured"] = frames_measured
    quality["measurements"]["degenerate_frames"] = degenerate_frames
    quality["measurements"]["degenerate_frame_percentage"] = degenerate_frames / frames_measured
    quality["measurements"]["max_frame_dominant_fraction"] = max(frame_fractions)
    return quality


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


class Gate:
    def __init__(self, name: str, status: str = NOT_RUN, detail: Optional[Mapping[str, Any]] = None) -> None:
        self.name = str(name)
        self.status = str(status)
        self.detail = dict(detail or {})

    @property
    def passed(self) -> bool:
        return self.status == PASS

    def as_dict(self) -> Dict[str, Any]:
        return {"gate": self.name, "status": self.status, "detail": self.detail}


def evaluate_acceptance(
    gates: Mapping[str, Any],
    *,
    dataset_root: Any = None,
    software_provenance: Optional[Mapping[str, Any]] = None,
    label_quality: Optional[Mapping[str, Any]] = None,
    reuse: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the ``DATASET_ACCEPTANCE.json`` payload."""
    normalised: List[Gate] = []
    for name in GATE_ORDER:
        raw = gates.get(name)
        if raw is None:
            status = NOT_RUN
            detail: Dict[str, Any] = {"note": "gate not supplied"}
        elif isinstance(raw, Gate):
            status, detail = raw.status, raw.detail
        elif isinstance(raw, str):
            status, detail = raw, {}
        elif isinstance(raw, bool):
            status, detail = (PASS if raw else FAIL), {"bool_source": True}
        elif isinstance(raw, Mapping):
            status = str(raw.get("status") or (PASS if raw.get("passed") else FAIL))
            detail = {k: v for k, v in raw.items() if k not in ("status", "passed")}
        else:
            status, detail = FAIL, {"value": repr(raw)}
        normalised.append(Gate(name, status, detail))

    unexpected = sorted(set(gates) - set(GATE_ORDER))
    for name in unexpected:
        normalised.append(Gate(name, str(gates[name]), {"unexpected_gate": True}))

    failed = [g.name for g in normalised if g.status == FAIL]
    not_run = [g.name for g in normalised if g.status == NOT_RUN]
    blocked = [g.name for g in normalised if g.status == BLOCKED]
    all_pass = bool(normalised) and not failed and not not_run and not blocked

    status = TRAINING_DATASET_READY if all_pass else NOT_READY
    if blocked and not failed:
        status = NOT_READY

    payload: Dict[str, Any] = {
        "schema": "DATASET_ACCEPTANCE/v1",
        "status": status,
        "training_dataset_ready": bool(status == TRAINING_DATASET_READY),
        "gates": [g.as_dict() for g in normalised],
        "gate_order": list(GATE_ORDER),
        "failed_gates": failed,
        "not_run_gates": not_run,
        "blocked_gates": blocked,
        "dataset_root": str(dataset_root) if dataset_root else None,
        "software_provenance": dict(software_provenance or {}),
        "label_quality": dict(label_quality or {}),
        "reuse": dict(reuse or {}) if reuse else None,
        "single_boolean_promotion_forbidden": True,
        "authority_note": (
            "No single boolean from run_perception_safe alone may promote a "
            "dataset; every gate in gate_order must PASS."
        ),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        payload["extra"] = dict(extra)
    payload["acceptance_digest"] = canonical_digest(
        {k: payload[k] for k in ("schema", "status", "gate_order", "failed_gates", "not_run_gates")}
    )
    return payload


def write_acceptance(payload: Mapping[str, Any], directory: Any) -> Path:
    target = Path(str(directory)) / ACCEPTANCE_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def load_acceptance(directory: Any) -> Optional[Dict[str, Any]]:
    path = Path(str(directory)) / ACCEPTANCE_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def assert_dataset_ready(payload: Mapping[str, Any]) -> None:
    if not payload or payload.get("status") != TRAINING_DATASET_READY:
        raise RuntimeError(
            "dataset_not_promotable:"
            f"status={(payload or {}).get('status')}:"
            f"failed={(payload or {}).get('failed_gates')}:"
            f"not_run={(payload or {}).get('not_run_gates')}"
        )


def software_provenance(
    *,
    git_sha: Optional[str] = None,
    capture_config_sha256: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "git_sha": git_sha,
        "capture_config_sha256": capture_config_sha256,
    }
    if extra:
        payload.update(dict(extra))
    payload["software_sha256"] = canonical_digest(
        {k: payload[k] for k in sorted(payload) if k != "software_sha256"}
    )
    return payload
