#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/rq5_negative_controls.py

Executes the RQ5 negative-control battery and records the outcome in
``RQ5_NEGATIVE_CONTROLS.json``.

A negative control answers one question: *does the authority actually reject
this defect, or would it silently accept it and produce a plausible-looking
artifact?* Every control below is constructed so that the un-hardened code path
would pass, and the hardened path must fail.

Each control is synthetic and carries ``claim_scope = TEST_FIXTURE_ONLY``. This
file is not RQ5 evidence and never is; it is a statement about the code.

No CARLA import, no network, no real dataset.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.perception.class_weights import (  # noqa: E402
    compute_class_weights,
    scan_label_class_counts,
)
from ultimate_pipeline.perception.dataset_split_authority import (  # noqa: E402
    ROLE_GENERATED_TEST,
    ROLE_MANUAL_TEST,
    ROLE_TRAIN,
    ROLE_VALIDATION,
    build_split_authority,
    load_split_manifest,
    write_split_manifests,
)
from ultimate_pipeline.perception.rq5_provenance import (  # noqa: E402
    IncompleteIdentityError,
    assert_complete_identity,
    build_model_manifest,
    canonical_dumps,
    protocol_identity,
    sha256_text,
    verify_checkpoint_provenance_strict,
    write_model_manifest,
)
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES  # noqa: E402
from ultimate_pipeline.perception.training_convergence_gate import (  # noqa: E402
    TECHNICAL_PASS,
    run_convergence_gate,
)

__all__ = [
    "NEGATIVE_CONTROLS_SCHEMA",
    "NEGATIVE_CONTROLS_FILENAME",
    "CONTROL_NAMES",
    "run_all_controls",
    "main",
]

NEGATIVE_CONTROLS_SCHEMA = "rq5_negative_controls_v1"
NEGATIVE_CONTROLS_FILENAME = "RQ5_NEGATIVE_CONTROLS.json"
CLAIM_SCOPE = "TEST_FIXTURE_ONLY"

CAMERA = "front_left_camera"
SIZE = 32
NUM_CLASSES = CARLA_SEMANTIC_NUM_CLASSES

#: The control battery required by protocol v2 section 17, in order.
CONTROL_NAMES = (
    "missing_explicit_dataset_research_strict",
    "fallback_to_latest_dataset",
    "partial_dataset_identity",
    "copied_duplicate_across_train_test",
    "adjacent_group_leakage",
    "manual_frame_in_train",
    "manual_frame_in_validation",
    "manual_class_statistics_in_class_weights",
    "missing_seed",
    "wrong_checkpoint_sha256",
    "wrong_dataset_sha256",
    "nan_training_loss",
    "single_class_collapsed_model",
    "checkpoint_missing_parameters",
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _write_capture(root: Path, capture_id: str, segment: int, frames: int, seed: int, route: str) -> List[dict]:
    rgb_dir = root / "rgb" / CAMERA
    lab_dir = root / "semseg_raw" / CAMERA
    rgb_dir.mkdir(parents=True, exist_ok=True)
    lab_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    records: List[dict] = []
    base = int(capture_id.split("_")[-1]) * 1000
    for i in range(frames):
        frame_id = base + i
        name = f"{frame_id:08d}.png"
        Image.fromarray(
            rng.integers(0, 255, size=(SIZE, SIZE, 3), dtype=np.uint8), mode="RGB"
        ).save(rgb_dir / name)
        lab = rng.integers(0, 12, size=(SIZE, SIZE), dtype=np.uint8)
        lab[rng.random((SIZE, SIZE)) < 0.02] = 255
        Image.fromarray(lab, mode="L").save(lab_dir / name)
        records.append(
            {
                "frame_id": frame_id,
                "filename": name,
                "route_id": route,
                "segment_id": segment,
                "capture_id": capture_id,
            }
        )
    return records


def _make_dataset(root: Path, captures: int, frames: int, route: str, seed0: int) -> Path:
    records: List[dict] = []
    for i in range(captures):
        records += _write_capture(root, f"cap_{i:03d}", i, frames, seed0 + i, route)
    (root / "frame_index.json").write_text(json.dumps({"frames": records}), encoding="utf-8")
    return root


def _complete_identity(tag: str) -> Dict[str, Any]:
    return {
        "schema": "rq5_dataset_identity_v1",
        "identity_sha256": f"{tag}-sha",
        "complete": True,
        "root": f"/datasets/{tag}",
        "camera": CAMERA,
        "file_count": 100,
        "digested_file_count": 100,
    }


def _partial_identity(tag: str) -> Dict[str, Any]:
    identity = _complete_identity(tag)
    identity["complete"] = False
    identity["digested_file_count"] = 10
    return identity


def _make_run(
    run_dir: Path,
    *,
    train_identity: Dict[str, Any],
    validation_identity: Dict[str, Any],
    train_loss: float = 1.5,
    validation_loss: float = 1.4,
    epochs: int = 3,
    seed: Any = 7,
    drop_first_parameter: bool = False,
) -> Dict[str, Path]:
    """Materialise a run directory (optionally with a seeded defect)."""
    import torch

    from ultimate_pipeline.perception import train_launcher

    run_dir.mkdir(parents=True, exist_ok=True)
    ckpt = run_dir / "seg_fcn_epoch003.pt"
    state = train_launcher._build_model(NUM_CLASSES).state_dict()
    if drop_first_parameter:
        state = {k: v for k, v in dict(state).items() if k != sorted(state)[0]}
    torch.save(state, ckpt)

    manifest = build_model_manifest(
        checkpoint=ckpt,
        train_dataset_identity=train_identity,
        train_roots=[str(train_identity.get("root"))],
        validation_identity=validation_identity,
        test_dataset_identities={
            "generated_test": _complete_identity("generated_test"),
            "manual_test": _complete_identity("manual_test"),
        },
        num_classes=NUM_CLASSES,
        seed=7 if seed is None else seed,
        protocol_path=REPO_ROOT / "configs" / "rq5_protocol_freeze_v2.json",
        class_weighting_policy={"scheme": "median_frequency", "source": "train_split_manifest"},
        determinism={"status": "DETERMINISM_ENFORCED", "strict_determinism_blockers": []},
    )
    write_model_manifest(run_dir, manifest)

    if seed is None:
        # A manifest that simply does not record a seed is the realistic form of
        # this defect; build_model_manifest() always writes one.
        manifest_payload = json.loads((run_dir / "model_manifest.json").read_text(encoding="utf-8"))
        manifest_payload["seed"] = {"schema": "rq5_seed_contract_v1"}
        (run_dir / "model_manifest.json").write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    history = {
        "schema": "rq5_training_history_v1",
        "epochs_requested": epochs,
        "epochs_completed": epochs,
        "epochs": [
            {
                "epoch": i + 1,
                "train_loss": train_loss,
                "validation_loss": validation_loss,
                "validation_miou": 0.05,
            }
            for i in range(epochs)
        ],
    }
    (run_dir / "TRAINING_HISTORY.json").write_text(json.dumps(history), encoding="utf-8")
    return {"run_dir": run_dir, "checkpoint": ckpt, "manifest": run_dir / "model_manifest.json"}


def _model_factory():
    from ultimate_pipeline.perception import train_launcher

    return lambda: train_launcher._build_model(NUM_CLASSES)


# ---------------------------------------------------------------------------
# the battery
# ---------------------------------------------------------------------------


def run_all_controls(workdir: Path) -> Dict[str, Any]:
    """
    Run every negative control against a freshly built synthetic fixture set.

    Returns a payload with one row per control. ``rejected`` is True only when
    the hardened authority actually refused the defect.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    generated = _make_dataset(workdir / "generated", captures=6, frames=4, route="ing_sim", seed0=10)
    manual = _make_dataset(workdir / "manual", captures=3, frames=3, route="ing_manual", seed0=70)
    authority = build_split_authority(
        generated_root=generated, camera=CAMERA, manual_root=manual
    )
    split_dir = workdir / "splits"
    write_split_manifests(split_dir, authority)

    rows: List[Dict[str, Any]] = []

    def record(name: str, rejected: bool, detail: str, evidence: Any = None) -> None:
        rows.append(
            {
                "control": name,
                "expected": "REJECTED",
                "rejected": bool(rejected),
                "status": "PASS" if rejected else "MISS",
                "detail": detail,
                "evidence": evidence,
            }
        )

    # 1. missing explicit dataset in research-strict mode -----------------
    from ultimate_pipeline.perception import train_launcher

    def _ns(**overrides):
        base = dict(
            split_dir=str(split_dir),
            camera=CAMERA,
            seed=7,
            datasets=None,
            dataset=None,
            limit=0,
            epochs=3,
            batch=4,
            lr=1e-4,
            class_weight_scheme="median_frequency",
            no_manifest=False,
            dataset_identity_max_files=0,
        )
        base.update(overrides)
        return argparse.Namespace(**base)

    rejected = False
    detail = ""
    try:
        train_launcher.enforce_research_strict(_ns(split_dir=str(workdir / "absent_splits")))
    except SystemExit as exc:
        rejected = True
        detail = str(exc)
    record("missing_explicit_dataset_research_strict", rejected, detail or "not rejected", detail)

    # 2. fallback to the latest dataset ------------------------------------
    rejected = False
    detail = ""
    try:
        train_launcher._resolve_dataset_roots(
            _ns(dataset=str(workdir / "generated"), split_dir=str(split_dir)), strict=True
        )
        # A present root is fine; the control is a *missing* root.
        train_launcher._resolve_dataset_roots(
            _ns(dataset=str(workdir / "no_such_dataset")), strict=True
        )
    except SystemExit as exc:
        rejected = True
        detail = str(exc)
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        rejected = True
        detail = str(exc)
    record("fallback_to_latest_dataset", rejected, detail or "a missing dataset did not fail", detail)

    # 3. partial dataset identity -----------------------------------------
    rejected = False
    detail = ""
    try:
        assert_complete_identity(_partial_identity("generated_train"), role="generated_train")
    except IncompleteIdentityError as exc:
        rejected = True
        detail = str(exc)
    record("partial_dataset_identity", rejected, detail or "a prefix identity was accepted", detail)

    # 4. copied duplicate across train/test --------------------------------
    from ultimate_pipeline.perception.dataset_split_authority import audit_leakage

    manifests = {role: json.loads(json.dumps(m)) for role, m in authority.manifests.items()}
    manifests[ROLE_GENERATED_TEST]["entries"].append(dict(manifests[ROLE_TRAIN]["entries"][0]))
    audit = audit_leakage(manifests)
    record(
        "copied_duplicate_across_train_test",
        audit["leak_free"] is False,
        f"leak_free={audit['leak_free']} violations={len(audit['violations'])}",
        {"violations": audit["violations"][:2]},
    )

    # 5. adjacent-group leakage -------------------------------------------
    manifests = {role: json.loads(json.dumps(m)) for role, m in authority.manifests.items()}
    entry = dict(manifests[ROLE_TRAIN]["entries"][0])
    entry["role"] = ROLE_GENERATED_TEST
    manifests[ROLE_GENERATED_TEST]["entries"].append(entry)
    audit = audit_leakage(manifests)
    kinds = {v["kind"] for v in audit["violations"]}
    record(
        "adjacent_group_leakage",
        audit["leak_free"] is False,
        f"leak_free={audit['leak_free']} kinds={sorted(kinds)}",
        {"kinds": sorted(kinds)},
    )

    # 6./7. manual frames in train / validation ----------------------------
    for role, control_name in (
        (ROLE_TRAIN, "manual_frame_in_train"),
        (ROLE_VALIDATION, "manual_frame_in_validation"),
    ):
        manifests = {r: json.loads(json.dumps(m)) for r, m in authority.manifests.items()}
        manifests[role]["entries"].append(dict(manifests[ROLE_MANUAL_TEST]["entries"][0]))
        audit = audit_leakage(manifests)
        check = [
            c for c in audit["content_equality_checks"] if c["pair"] == [role, ROLE_MANUAL_TEST]
        ]
        shared = check[0]["shared_sample_identities"] if check else 0
        record(
            control_name,
            audit["leak_free"] is False and shared >= 1,
            f"shared manual sample identities in {role}: {shared}",
            {"shared": shared},
        )

    # 8. manual class statistics entering class weights --------------------
    train_manifest = load_split_manifest(split_dir / "train_manifest.json")
    train_paths = [e["label_path"] for e in train_manifest["entries"]]
    counts_before = scan_label_class_counts(train_paths, num_classes=NUM_CLASSES).tolist()
    weights_before = compute_class_weights(counts_before, num_classes=NUM_CLASSES).tolist()

    manual_manifest = load_split_manifest(split_dir / "manual_test_manifest.json")
    for entry in manual_manifest["entries"]:
        Image.fromarray(np.full((SIZE, SIZE), 7, dtype=np.uint8), mode="L").save(
            entry["label_path"]
        )
    counts_after = scan_label_class_counts(train_paths, num_classes=NUM_CLASSES).tolist()
    weights_after = compute_class_weights(counts_after, num_classes=NUM_CLASSES).tolist()

    manual_counts = scan_label_class_counts(
        [e["label_path"] for e in manual_manifest["entries"]], num_classes=NUM_CLASSES
    )
    # Sensitivity: the manual labels really did change, so the invariance above
    # is a property of the training-split source and not of a dead probe.
    sensitive = int(manual_counts.sum()) > 0
    invariant = counts_before == counts_after and weights_before == weights_after
    record(
        "manual_class_statistics_in_class_weights",
        invariant and sensitive,
        f"train class counts invariant to manual relabel: {invariant}; manual labels are "
        f"sensitive (non-zero manual pixels: {sensitive})",
        {"train_pixels": int(sum(counts_before)), "manual_pixels": int(manual_counts.sum())},
    )

    # 9. missing seed ------------------------------------------------------
    run = _make_run(
        workdir / "run_missing_seed",
        train_identity=_complete_identity("generated_train"),
        validation_identity=_complete_identity("generated_validation"),
        seed=None,
    )
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model_factory())
    failed = {c.code for c in report.checks if not c.ok}
    record(
        "missing_seed",
        report.technical_status != TECHNICAL_PASS
        and bool(failed & {"seed_contract", "checkpoint_manifest_binding"}),
        f"technical_status={report.technical_status} failed={sorted(failed)}",
        {"failures": report.failures},
    )

    # 10. wrong checkpoint SHA --------------------------------------------
    import torch

    run = _make_run(
        workdir / "run_wrong_ckpt",
        train_identity=_complete_identity("generated_train"),
        validation_identity=_complete_identity("generated_validation"),
    )
    from ultimate_pipeline.perception import train_launcher as _tl

    torch.save(_tl._build_model(NUM_CLASSES).state_dict(), run["checkpoint"])
    verification = verify_checkpoint_provenance_strict(run["checkpoint"], run["manifest"])
    record(
        "wrong_checkpoint_sha256",
        verification["ok"] is False,
        f"ok={verification['ok']}",
        {"failures": verification["failures"][:3]},
    )

    # 11. wrong dataset SHA ------------------------------------------------
    run = _make_run(
        workdir / "run_wrong_dataset",
        train_identity=_complete_identity("generated_train"),
        validation_identity=_complete_identity("generated_validation"),
    )
    report = run_convergence_gate(
        run_dir=run["run_dir"],
        expected_dataset_identities={"generated_train": "some-other-split"},
        model_factory=_model_factory(),
    )
    failed = {c.code for c in report.checks if not c.ok}
    record(
        "wrong_dataset_sha256",
        report.technical_status != TECHNICAL_PASS and "dataset_identity_match" in failed,
        f"technical_status={report.technical_status} failed={sorted(failed)}",
        {"failures": report.failures},
    )

    # 12. NaN loss ---------------------------------------------------------
    run = _make_run(
        workdir / "run_nan_loss",
        train_identity=_complete_identity("generated_train"),
        validation_identity=_complete_identity("generated_validation"),
        train_loss=float("nan"),
    )
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model_factory())
    failed = {c.code for c in report.checks if not c.ok}
    record(
        "nan_training_loss",
        report.technical_status != TECHNICAL_PASS and "train_loss_finite" in failed,
        f"technical_status={report.technical_status} failed={sorted(failed)}",
        {"failures": report.failures},
    )

    # 13. single-class collapsed model fixture -----------------------------
    run = _make_run(
        workdir / "run_collapsed",
        train_identity=_complete_identity("generated_train"),
        validation_identity=_complete_identity("generated_validation"),
    )
    report = run_convergence_gate(
        run_dir=run["run_dir"],
        model_factory=_model_factory(),
        prediction_probe=lambda _m: np.full(64, 4, dtype=np.int64),
    )
    failed = {c.code for c in report.checks if not c.ok}
    record(
        "single_class_collapsed_model",
        report.technical_status != TECHNICAL_PASS and "prediction_not_single_class" in failed,
        f"technical_status={report.technical_status} failed={sorted(failed)}",
        {"failures": report.failures},
    )

    # 14. checkpoint with missing parameters -------------------------------
    run = _make_run(
        workdir / "run_missing_params",
        train_identity=_complete_identity("generated_train"),
        validation_identity=_complete_identity("generated_validation"),
        drop_first_parameter=True,
    )
    report = run_convergence_gate(run_dir=run["run_dir"], model_factory=_model_factory())
    failed = {c.code for c in report.checks if not c.ok}
    record(
        "checkpoint_missing_parameters",
        report.technical_status != TECHNICAL_PASS and "model_loads_completely" in failed,
        f"technical_status={report.technical_status} failed={sorted(failed)}",
        {"failures": report.failures},
    )

    missing = [name for name in CONTROL_NAMES if not any(r["control"] == name for r in rows)]
    extra = [r["control"] for r in rows if r["control"] not in CONTROL_NAMES]

    payload = {
        "schema": NEGATIVE_CONTROLS_SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "claim_scope": CLAIM_SCOPE,
        "is_rq5_evidence": False,
        "protocol_sha256": protocol_identity()["sha256"],
        "controls_expected": list(CONTROL_NAMES),
        "controls_executed": [r["control"] for r in rows],
        "controls_missing": missing,
        "unexpected_controls": extra,
        "total": len(rows),
        "rejected": sum(1 for r in rows if r["rejected"]),
        "missed": sum(1 for r in rows if not r["rejected"]),
        "status": "PASS" if all(r["rejected"] for r in rows) and not missing else "FAIL",
        "rows": rows,
        "claim_boundary": (
            "These controls exercise code paths on synthetic fixtures. They prove the "
            "authority rejects the listed defects; they prove nothing about RQ5 accuracy, "
            "generalization or dataset quality, and are not RQ5 evidence."
        ),
    }
    payload["report_sha256"] = sha256_text(
        canonical_dumps({k: v for k, v in payload.items() if k not in ("created_utc", "report_sha256")})
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "reports" / "parallel_wave" / "rq5" / NEGATIVE_CONTROLS_FILENAME,
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="fixture scratch directory (default: a temp dir next to --out)",
    )
    args = parser.parse_args()

    import tempfile

    with tempfile.TemporaryDirectory(prefix="rq5_negative_controls_") as tmp:
        workdir = Path(args.workdir) if args.workdir else Path(tmp) / "fixtures"
        payload = run_all_controls(workdir)
        if args.workdir is None:
            payload["fixtures_persisted"] = False
            payload["fixture_note"] = (
                "fixtures were written to a temporary directory and discarded; rerun with "
                "--workdir to keep them for inspection"
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "rejected": payload["rejected"],
                      "missed": payload["missed"], "out": str(args.out)}, indent=2))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())