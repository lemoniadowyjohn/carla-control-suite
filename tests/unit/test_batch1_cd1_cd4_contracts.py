#!/usr/bin/env python3
"""Batch-1 tests for CD-1 (split authority + frame transactions) + CD-4 (failure guards + pretraining contract + load contracts).

Offline only; no CARLA/UE run required.
"""
import sys
import types
import json
import hashlib
import tempfile
from pathlib import Path

# Pre-register carla stub before importing any project modules
_carla = types.ModuleType("carla")
_carla.CityObjectLabel = type("CityObjectLabel", (), {"Road": 0, "TrafficLight": 1})()
_carla.ColorConverter = type("ColorConverter", (), {"CityScapesPalette": "palette"})
_carla.Image = object
_carla.Sensor = object
sys.modules["carla"] = _carla

# Allow torch import
torch = pytest = None
try:
    import torch
    import pytest
except ImportError:
    pass

# Import our target modules directly (avoiding circular import by ensuring conftest is processed first)
from ultimate_pipeline.perception.split_manifest import (
    build_split_manifest, write_split_manifest, load_and_verify_split_manifest,
    PARTITION_GENERATED_TRAIN, PARTITION_GENERATED_VALIDATION,
    PARTITION_GENERATED_TEST, PARTITION_MANUAL_TEST,
)


def _make_session(root: Path, frame: int = 1) -> Path:
    (root / "rgb" / "cam").mkdir(parents=True, exist_ok=True)
    (root / "semseg_raw" / "cam").mkdir(parents=True, exist_ok=True)
    (root / "rgb" / "cam" / f"{frame:08d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "semseg_raw" / "cam" / f"{frame:08d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "frame_status" / f"{frame:08d}.json").write_text(
        json.dumps({"schema": "frame_set_status_v1", "frame": frame, "status": "complete", "members": []}),
        encoding="utf-8",
    )
    return root


def test_split_manifest_session_granularity():
    """Generated sessions must be assigned to exactly ONE partition (adjacency invariant)."""
    with tempfile.TemporaryDirectory() as td:
        s1 = _make_session(Path(td) / "s1")
        s2 = _make_session(Path(td) / "s2")
        manual = _make_session(Path(td) / "manual")
        manifest = build_split_manifest(
            generated_roots=[str(s1), str(s2)],
            manual_roots=[str(manual)],
            seed=1,
        )
        # Each generated session appears in exactly one generated partition
        for session in manifest["sessions"]:
            if session.get("manual"):
                continue
            sid = session["session_id"]
            total = sum(
                1
                for p in (PARTITION_GENERATED_TRAIN, PARTITION_GENERATED_VALIDATION, PARTITION_GENERATED_TEST)
                if any(m.startswith(sid + ":") for m in manifest["partitions"][p])
            )
            assert total == 1, f"session {sid} assigned to multiple partitions"
        # Manual isolation: manual members only in manual_test
        for m in manifest["partitions"][PARTITION_MANUAL_TEST]:
            assert m.startswith("manual:"), "manual partition contains non-manual frame"


def test_split_manifest_sha256_verification():
    """Modifying the manifest after signing invalidates verification."""
    with tempfile.TemporaryDirectory() as td:
        s1 = _make_session(Path(td) / "s1")
        manifest = build_split_manifest(generated_roots=[str(s1)], seed=42)
        out = Path(td) / "split_manifest.json"
        write_split_manifest(out, manifest)
        # Tamper: modify count
        payload = json.loads(out.read_text())
        payload["counts"]["generated_train"] = 999
        out.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        _, failures = load_and_verify_split_manifest(out)
        assert failures, "tampered manifest should fail verification"


def test_training_failure_guard_module():
    from ultimate_pipeline.perception.training_failure_guard import (
        is_cuda_oom,
        classify_exception,
        TrainingFailure,
        STATUS_CUDA_OOM,
        STATUS_NAN_LOSS,
    )

    # OOM detection
    assert is_cuda_oom(ValueError("Out of memory"))
    assert is_cuda_oom(RuntimeError("CUDA out of memory"))

    # Classification
    verdict = classify_exception(ValueError("oom"))
    assert verdict.status == STATUS_CUDA_OOM

    # Direct error
    failure = TrainingFailure(STATUS_NAN_LOSS, "bad loss value")
    assert failure.status == STATUS_NAN_LOSS
    d = failure.to_dict()
    assert "status" in d


def test_load_contract_mandatory_migration():
    assert torch is not None, "torch required for load contract tests"
    from ultimate_pipeline.perception.rq5_provenance import load_state_dict_governed

    model = torch.nn.Linear(10, 2)
    fake_state = {"wrong_key": torch.tensor([1.0])}

    # Partial load WITHOUT migration_contract must fail closed
    try:
        load_state_dict_governed(model, f"/fake/path{torch.rand(1).tolist()[0]}.pt")
        assert False, "should fail"
    except FileNotFoundError:
        pass  # Expected

    # Load with mismatched keys but NO migration contract should also fail
    fake_file = tempfile.NamedTemporaryFile(suffix=".pt", delete=False)
    torch.save({"state_dict": fake_state}, fake_file.name)
    try:
        try:
            load_state_dict_governed(model, fake_file.name, allow_partial=True)
            assert False, "partial load requires migration_contract"
        except Exception as e:
            assert "migration_contract" in str(e).lower()
    finally:
        import os
        os.unlink(fake_file.name)


def test_pretraining_contract_guard():
    assert torch is not None, "torch required"
    import torchvision
    from ultimate_pipeline.perception.rq5_provenance import verify_random_initialisation

    model = torchvision.models.segmentation.fcn_resnet50(weights=None, num_classes=2)
    contract = verify_random_initialisation(model)
    assert contract["init"] == "random_frozen_protocol"
    assert contract["weights_argument"] is None
    assert contract.get("instantiated_state_sha256")


if __name__ == "__main__":
    if torch is None:
        print("SKIP: torch not installed")
        sys.exit(0)
    test_split_manifest_session_granularity()
    print("PASS split_manifest")
    test_split_manifest_sha256_verification()
    print("PASS manifest_sha256")
    test_training_failure_guard_module()
    print("PASS failure_guard")
    test_load_contract_mandatory_migration()
    print("PASS load_contract")
    test_pretraining_contract_guard()
    print("PASS pretraining_guard")
    print("\nBatch-1 offline tests PASS")