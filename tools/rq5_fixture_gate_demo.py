#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/rq5_fixture_gate_demo.py

Executes the RQ5 offline code chain end-to-end on **synthetic fixtures** and
persists the resulting artifacts so the gate wiring can be inspected without a
CARLA runtime:

    synthetic datasets -> grouped splits -> quality gate -> research-strict
    training (3 frozen epochs, generated-validation pass) -> TRAINING_HISTORY.json
    -> TRAINING_CONVERGENCE.json -> DATASET_QUALITY.json

Everything this tool writes carries ``claim_scope = TEST_FIXTURE_ONLY`` and is
NOT RQ5 evidence. It proves the code paths execute and the gates agree; it says
nothing about mIoU, degradation or generalization, and no number produced here
may be quoted as an RQ5 result.

This tool never runs final RQ5 training: it uses synthetic data, a single
fixture seed, and a fixture checkpoint path.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.perception.dataset_quality_gate import (  # noqa: E402
    evaluate_dataset_quality,
    write_dataset_quality,
)
from ultimate_pipeline.perception.dataset_split_authority import (  # noqa: E402
    audit_leakage,
    build_split_authority,
    write_leakage_audit,
    write_split_manifests,
)
from ultimate_pipeline.perception.rq5_provenance import (  # noqa: E402
    canonical_dumps,
    protocol_identity,
    sha256_file,
    sha256_text,
)
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES  # noqa: E402
from ultimate_pipeline.perception.training_convergence_gate import (  # noqa: E402
    run_convergence_gate,
    write_convergence_report,
)

FIXTURE_DEMO_SCHEMA = "rq5_fixture_gate_demo_v1"
CLAIM_SCOPE = "TEST_FIXTURE_ONLY"

CAMERA = "front_left_camera"
SIZE = 32
NUM_CLASSES = CARLA_SEMANTIC_NUM_CLASSES
DEMO_SEED = 7


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


def run_demo(workdir: Path, out_dir: Path, *, keep_fixtures: bool = False) -> Dict[str, Any]:
    """Run the full offline chain on synthetic fixtures and persist the artifacts."""
    workdir = Path(workdir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated = _make_dataset(workdir / "generated", captures=6, frames=4, route="ing_sim", seed0=10)
    manual = _make_dataset(workdir / "manual", captures=3, frames=3, route="ing_manual", seed0=70)

    # 1. quality gate per domain ------------------------------------------
    quality_paths = {}
    quality_status = {}
    for role, root in (("generated", generated), ("manual", manual)):
        report = evaluate_dataset_quality(root, CAMERA, role=role, num_classes=NUM_CLASSES)
        path = write_dataset_quality(out_dir / role, report, claim_scope=CLAIM_SCOPE)
        quality_paths[role] = path
        quality_status[role] = report.status
        if report.status != "PASS":
            raise SystemExit(f"fixture quality gate failed for {role}: {report.metrics['quality_failures']}")

    # 2. grouped splits + leakage audit ------------------------------------
    authority = build_split_authority(
        generated_root=generated, camera=CAMERA, manual_root=manual
    )
    split_dir = out_dir / "splits"
    split_paths = write_split_manifests(split_dir, authority)
    leakage = audit_leakage(authority.manifests, claim_scope=CLAIM_SCOPE)
    leakage_path = write_leakage_audit(out_dir, leakage)
    if not leakage["leak_free"]:
        raise SystemExit(f"fixture splits leaked: {leakage['violations'][:3]}")

    # 3. research-strict training (3 frozen epochs) -------------------------
    from ultimate_pipeline.perception import train_launcher

    run_dir = out_dir / "run" / f"seed_{DEMO_SEED}"
    argv = [
        "train_launcher.py",
        "--research-strict",
        "--split-dir", str(split_dir),
        "--camera", CAMERA,
        "--out-dir", str(run_dir),
        "--epochs", "3",
        "--batch", "4",
        "--lr", "1e-4",
        "--num-classes", str(NUM_CLASSES),
        "--limit", "0",
        "--device", "cpu",
        "--num-workers", "0",
        "--seed", str(DEMO_SEED),
        "--validation-miou",
        "--protocol", str(REPO_ROOT / "configs" / "rq5_protocol_freeze_v2.json"),
    ]
    old_argv = sys.argv
    sys.argv = argv
    try:
        code = train_launcher.main()
    finally:
        sys.argv = old_argv
    if code != 0:
        raise SystemExit(f"fixture training exited {code}")

    # 4. convergence gate ---------------------------------------------------
    manifest = json.loads(
        (run_dir / "model_manifest.json").read_text(encoding="utf-8")
    )
    convergence = run_convergence_gate(
        run_dir=run_dir,
        expected_epochs=3,
        expected_seed=DEMO_SEED,
        expected_dataset_identities={
            "generated_train": manifest["dataset"]["train_identity_sha256"],
            "generated_validation": manifest["dataset"]["validation_identity_sha256"],
        },
        model_factory=lambda: train_launcher._build_model(NUM_CLASSES),
    )
    convergence.claim_scope = CLAIM_SCOPE
    convergence_path = write_convergence_report(out_dir, convergence)

    artifacts = {
        "dataset_quality_generated": quality_paths["generated"],
        "dataset_quality_manual": quality_paths["manual"],
        "leakage_audit": leakage_path,
        "training_history": run_dir / "TRAINING_HISTORY.json",
        "model_manifest": run_dir / "model_manifest.json",
        "checkpoint": run_dir / "seg_fcn_epoch003.pt",
        "training_convergence": convergence_path,
        **{f"split_manifest::{role}": path for role, path in split_paths.items()},
    }
    hashes = {key: sha256_file(path) for key, path in artifacts.items()}

    summary = {
        "schema": FIXTURE_DEMO_SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "claim_scope": CLAIM_SCOPE,
        "is_rq5_evidence": False,
        "final_rq5_training_executed": False,
        "protocol_sha256": protocol_identity()["sha256"],
        "fixture_seed": DEMO_SEED,
        "generated_frames": len(authority.generated_index.frames),
        "manual_frames": len(authority.manual_index.frames) if authority.manual_index else 0,
        "role_frame_counts": {role: len(v) for role, v in authority.roles.items()},
        "group_kind": authority.group_kind,
        "leakage_free": leakage["leak_free"],
        "dataset_quality": quality_status,
        "checkpoint_policy": "final_epoch_only",
        "validation_selects_epoch": False,
        "technical_convergence": convergence.technical_status,
        "scientific_performance": convergence.scientific_status,
        "artifacts_sha256": hashes,
        "claim_boundary": (
            "Synthetic fixture run with claim_scope=TEST_FIXTURE_ONLY. It demonstrates that the "
            "RQ5 offline chain executes and that the gates agree. It is not RQ5 evidence, it "
            "trains no governed model, and no metric produced here may be quoted as an RQ5 "
            "result. Final RQ5 training remains blocked on a validated RQ3 paired dataset."
        ),
    }
    summary["report_sha256"] = sha256_text(
        canonical_dumps({k: v for k, v in summary.items() if k not in ("created_utc", "report_sha256")})
    )

    summary_path = out_dir / "RQ5_FIXTURE_GATE_DEMO.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary["artifacts_sha256"]["RQ5_FIXTURE_GATE_DEMO.json"] = sha256_file(summary_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "reports" / "parallel_wave" / "rq5" / "fixture_demo")
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument("--keep-fixtures", action="store_true")
    args = parser.parse_args()

    if args.workdir is not None:
        args.workdir.mkdir(parents=True, exist_ok=True)
        summary = run_demo(args.workdir, args.out_dir, keep_fixtures=True)
    else:
        with tempfile.TemporaryDirectory(prefix="rq5_fixture_demo_") as tmp:
            summary = run_demo(Path(tmp) / "fixtures", args.out_dir)
        summary["fixtures_persisted"] = False

    print(
        json.dumps(
            {
                "claim_scope": summary["claim_scope"],
                "technical_convergence": summary["technical_convergence"],
                "scientific_performance": summary["scientific_performance"],
                "leakage_free": summary["leakage_free"],
                "artifacts": sorted(summary["artifacts_sha256"]),
            },
            indent=2,
        )
    )
    return 0 if summary["technical_convergence"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())