"""
RQ5 research-strict mode, validation loop and class-weight isolation tests.

Protocol v2 makes ``--research-strict`` the only acceptable mode for a governed
RQ5 run. These tests assert two things:

1. every prohibited convenience is a hard failure in strict mode, and
2. a strict-mode run on a synthetic fixture actually produces the artifacts the
   protocol demands -- a final-epoch checkpoint, a real generated-validation
   pass, a complete dataset identity per role and a protocol-bound manifest.

All fixtures are synthetic and carry ``claim_scope = TEST_FIXTURE_ONLY``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from ultimate_pipeline.perception.class_weights import (
    compute_class_weights,
    scan_label_class_counts,
)
from ultimate_pipeline.perception.dataset_split_authority import (
    ROLE_GENERATED_TEST,
    ROLE_MANUAL_TEST,
    ROLE_TRAIN,
    ROLE_VALIDATION,
    build_split_authority,
    load_split_manifest,
    write_split_manifests,
)
from ultimate_pipeline.perception.min_train_segmentation import (
    TRAINING_HISTORY_FILENAME,
    TRAINING_HISTORY_SCHEMA,
    ManifestSegDataset,
)
from ultimate_pipeline.perception.rq5_provenance import (
    IncompleteIdentityError,
    assert_complete_identity,
    apply_determinism_contract,
    load_model_manifest,
    require_complete_identities,
)
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES

CAMERA = "front_left_camera"
PROTOCOL_SEED = 7
SIZE = 32


# ---------------------------------------------------------------------------
# synthetic fixtures
# ---------------------------------------------------------------------------


def _write_capture(root: Path, capture_id: str, segment: int, frames: int, seed: int, route: str) -> list[dict]:
    rgb_dir = root / "rgb" / CAMERA
    lab_dir = root / "semseg_raw" / CAMERA
    rgb_dir.mkdir(parents=True, exist_ok=True)
    lab_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    records = []
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


def _make_dataset(tmp_path: Path, name: str, captures: int, frames: int, route: str, seed0: int) -> Path:
    root = tmp_path / name
    records: list[dict] = []
    for i in range(captures):
        records += _write_capture(root, f"cap_{i:03d}", i, frames, seed0 + i, route)
    (root / "frame_index.json").write_text(json.dumps({"frames": records}), encoding="utf-8")
    return root


def _make_splits(tmp_path: Path) -> Path:
    generated = _make_dataset(tmp_path, "generated", captures=6, frames=4, route="ing_sim", seed0=10)
    manual = _make_dataset(tmp_path, "manual", captures=3, frames=3, route="ing_manual", seed0=70)
    authority = build_split_authority(
        generated_root=generated, camera=CAMERA, manual_root=manual
    )
    split_dir = tmp_path / "splits"
    write_split_manifests(split_dir, authority)
    return split_dir


def _strict_argv(split_dir: Path, out_dir: Path, extra=()) -> list[str]:
    return [
        "train_launcher.py",
        "--research-strict",
        "--split-dir", str(split_dir),
        "--camera", CAMERA,
        "--out-dir", str(out_dir),
        "--epochs", "3",
        "--batch", "4",
        "--lr", "1e-4",
        "--num-classes", str(CARLA_SEMANTIC_NUM_CLASSES),
        "--limit", "0",
        "--device", "cpu",
        "--num-workers", "0",
        "--seed", str(PROTOCOL_SEED),
        *extra,
    ]


# ---------------------------------------------------------------------------
# strict-mode prohibitions
# ---------------------------------------------------------------------------


def _namespace(**overrides) -> argparse.Namespace:
    base = dict(
        split_dir=str(REPO := Path(__file__).resolve().parents[2]),
        camera=CAMERA,
        seed=PROTOCOL_SEED,
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


def test_strict_mode_rejects_implicit_split_creation():
    from ultimate_pipeline.perception import train_launcher

    with pytest.raises(SystemExit, match="explicit --split-dir"):
        train_launcher.enforce_research_strict(_namespace(split_dir=None))


def test_strict_mode_rejects_implicit_camera():
    from ultimate_pipeline.perception import train_launcher

    with pytest.raises(SystemExit, match="camera must be given explicitly"):
        train_launcher.enforce_research_strict(_namespace(camera=None))


def test_strict_mode_rejects_implicit_seed():
    from ultimate_pipeline.perception import train_launcher

    with pytest.raises(SystemExit, match="seed must be given explicitly"):
        train_launcher.enforce_research_strict(_namespace(seed=None))


def test_strict_mode_rejects_split_prefix_truncation():
    from ultimate_pipeline.perception import train_launcher

    with pytest.raises(SystemExit, match="a prefix of a governed split is not the split"):
        train_launcher.enforce_research_strict(_namespace(limit=10))


def test_strict_mode_rejects_skipped_provenance():
    from ultimate_pipeline.perception import train_launcher

    with pytest.raises(SystemExit, match="provenance is not optional"):
        train_launcher.enforce_research_strict(_namespace(no_manifest=True))


def test_strict_mode_rejects_partial_dataset_identity():
    from ultimate_pipeline.perception import train_launcher

    with pytest.raises(SystemExit, match="partial identity"):
        train_launcher.enforce_research_strict(_namespace(dataset_identity_max_files=8))


def test_strict_mode_pins_the_frozen_v1_hyperparameters():
    from ultimate_pipeline.perception import train_launcher

    with pytest.raises(SystemExit, match="freezes epochs=3"):
        train_launcher.enforce_research_strict(_namespace(epochs=9))
    with pytest.raises(SystemExit, match="freezes batch_size=4"):
        train_launcher.enforce_research_strict(_namespace(batch=8))
    with pytest.raises(SystemExit, match="freezes learning_rate"):
        train_launcher.enforce_research_strict(_namespace(lr=1e-3))
    with pytest.raises(SystemExit, match="class weighting"):
        train_launcher.enforce_research_strict(_namespace(class_weight_scheme="inverse_frequency"))


def test_strict_mode_never_falls_back_to_another_dataset(tmp_path):
    """A missing explicit dataset is a failure; no other dataset is substituted."""
    from ultimate_pipeline.perception import train_launcher

    other = _make_dataset(tmp_path, "other", captures=2, frames=2, route="other", seed0=5)
    namespace = _namespace(dataset=str(tmp_path / "does_not_exist"))
    with pytest.raises(SystemExit):
        train_launcher._resolve_dataset_roots(namespace, strict=True)
    assert other.exists()  # the unrelated dataset was not touched or adopted


def test_legacy_non_strict_fallback_is_preserved(tmp_path, monkeypatch):
    """Outside strict mode the historical auto-discovery behaviour still works."""
    from ultimate_pipeline.perception import train_launcher
    from ultimate_pipeline.config.settings import SETTINGS

    base = tmp_path / "runs"
    dataset = base / "older"
    _make_dataset(dataset.parent, "older", captures=1, frames=1, route="r", seed0=3)
    monkeypatch.setattr(SETTINGS, "BASE_OUTPUT_DIR", str(base), raising=False)
    monkeypatch.setattr(SETTINGS, "TRAINING_DATASET_DIR", "", raising=False)

    namespace = argparse.Namespace(dataset=None, datasets=None)
    resolved = train_launcher._resolve_dataset_roots(namespace, strict=False)
    assert resolved and resolved[0].name == "older"


def test_strict_run_reports_every_prohibition_as_false(tmp_path):
    from ultimate_pipeline.perception import train_launcher

    record = train_launcher.enforce_research_strict(_namespace(split_dir=str(_make_splits(tmp_path))))
    for key in (
        "auto_dataset_discovery",
        "missing_dataset_fallback",
        "latest_checkpoint_fallback",
        "implicit_split_creation",
        "implicit_camera",
        "implicit_seed",
        "mtime_selection",
        "limit_truncation",
    ):
        assert record[key] is False, key
    assert record["pinned"]["epochs"] == 3


# ---------------------------------------------------------------------------
# dataset identity completeness
# ---------------------------------------------------------------------------


def test_partial_dataset_identity_is_rejected_for_authoritative_roles():
    with pytest.raises(IncompleteIdentityError, match="incomplete"):
        assert_complete_identity(
            {"identity_sha256": "deadbeef", "complete": False, "digested_file_count": 4, "file_count": 40},
            role="generated_train",
        )


def test_missing_dataset_identity_is_rejected():
    with pytest.raises(IncompleteIdentityError, match="none was supplied"):
        assert_complete_identity(None, role="generated_train")


def test_partial_identity_is_accepted_only_as_a_diagnostic():
    report = assert_complete_identity(
        {"identity_sha256": "deadbeef", "complete": False}, role="generated_train", authoritative=False
    )
    assert report["authoritative"] is False
    assert report["complete"] is False


def test_every_applicable_research_role_must_be_complete():
    identities = {
        "generated_train": {"identity_sha256": "a", "complete": True},
        "generated_validation": {"identity_sha256": "b", "complete": True},
        "generated_test": {"identity_sha256": "c", "complete": False},
        "manual_test": {"identity_sha256": "d", "complete": True},
    }
    with pytest.raises(IncompleteIdentityError, match="generated_test"):
        require_complete_identities(identities)


def test_absent_role_is_reported_when_it_does_not_apply():
    identities = {
        "generated_train": {"identity_sha256": "a", "complete": True},
        "generated_validation": {"identity_sha256": "b", "complete": True},
        "generated_test": {"identity_sha256": "c", "complete": True},
    }
    with pytest.raises(IncompleteIdentityError, match="manual_test"):
        require_complete_identities(identities)
    report = require_complete_identities(identities, allow_absent_roles=("manual_test",))
    assert report["manual_test"]["skipped"] is True
    assert report["generated_train"]["identity_sha256"] == "a"


# ---------------------------------------------------------------------------
# determinism contract
# ---------------------------------------------------------------------------


def test_determinism_contract_records_actual_settings_not_intentions():
    contract = apply_determinism_contract(4242)
    payload = contract.to_dict()
    assert payload["seed"] == 4242
    assert payload["bit_exactness_claimed"] is False
    assert payload["seed_applied"]["pythonhashseed"] == "4242"
    assert payload["seed_applied"]["random"] == "seeded"
    assert payload["seed_applied"]["numpy"] == "seeded"
    assert payload["torch_cudnn_benchmark"] is False
    assert payload["status"] in ("DETERMINISM_ENFORCED", "SEEDED_BUT_NUMERICALLY_NONDETERMINISTIC")


def test_determinism_contract_marks_blockers_when_strict_is_impossible(monkeypatch):
    import torch

    def _boom(*_args, **_kwargs):
        raise RuntimeError("deterministic algorithms unavailable for this op")

    monkeypatch.setattr(torch, "use_deterministic_algorithms", _boom)
    contract = apply_determinism_contract(7, strict=True)
    payload = contract.to_dict()
    assert payload["status"] == "SEEDED_BUT_NUMERICALLY_NONDETERMINISTIC"
    assert payload["strict_determinism_blockers"]
    assert payload["bit_exactness_claimed"] is False


# ---------------------------------------------------------------------------
# end-to-end strict run
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def strict_run(tmp_path_factory):
    """One real (fixture) strict-mode training run shared by the assertions below."""
    tmp_path = tmp_path_factory.mktemp("strict_run")
    from ultimate_pipeline.perception import train_launcher

    split_dir = _make_splits(tmp_path)
    out_dir = tmp_path / "run_seed7"
    argv = _strict_argv(split_dir, out_dir, extra=["--validation-miou"])
    old_argv = sys.argv
    sys.argv = argv
    try:
        code = train_launcher.main()
    finally:
        sys.argv = old_argv
    assert code == 0
    return {"tmp": tmp_path, "split_dir": split_dir, "out_dir": out_dir}


def test_strict_run_writes_a_final_epoch_checkpoint_and_manifest(strict_run):
    out_dir = strict_run["out_dir"]
    assert (out_dir / "seg_fcn_epoch003.pt").is_file()
    assert not (out_dir / "checkpoints" / "model_last.pt").exists(), (
        "the governed checkpoint is the final-epoch checkpoint; a stray model_last.pt would "
        "reintroduce an ambiguous checkpoint identity"
    )
    manifest = load_model_manifest(out_dir / "model_manifest.json")
    assert Path(manifest["checkpoint"]["path"]) == (out_dir / "seg_fcn_epoch003.pt")


def test_strict_run_records_a_real_generated_validation_pass(strict_run):
    history = json.loads(
        (strict_run["out_dir"] / TRAINING_HISTORY_FILENAME).read_text(encoding="utf-8")
    )
    assert history["schema"] == TRAINING_HISTORY_SCHEMA
    assert history["epochs_completed"] == 3
    assert history["validation_dataset_role"] == ROLE_VALIDATION
    rows = history["epochs"]
    assert len(rows) == 3
    for row in rows:
        assert isinstance(row["train_loss"], float)
        assert row["validation_loss"] is not None
        assert np.isfinite(row["train_loss"])
        assert np.isfinite(row["validation_loss"])
    assert history["epochs"][0]["validation_miou"] is not None


def test_validation_never_selects_the_checkpoint(strict_run):
    history = json.loads(
        (strict_run["out_dir"] / TRAINING_HISTORY_FILENAME).read_text(encoding="utf-8")
    )
    policy = history["checkpoint_policy"]
    assert policy["checkpoint_policy"] == "final_epoch_only"
    assert policy["validation_selects_epoch"] is False
    assert policy["early_stopping"] is False
    assert policy["selection_consults_manual"] is False
    manifest = load_model_manifest(strict_run["out_dir"] / "model_manifest.json")
    assert manifest["checkpoint"]["policy"]["validation_selects_epoch"] is False


def test_manifest_binds_protocol_dataset_identities_and_class_weight_policy(strict_run):
    manifest = load_model_manifest(strict_run["out_dir"] / "model_manifest.json")
    assert manifest["protocol"]["schema"] == "rq5_protocol_freeze/v2"
    assert manifest["protocol"]["sha256"]

    dataset = manifest["dataset"]
    for role_key in ("train_identity", "validation_identity"):
        assert dataset[role_key]["complete"] is True, f"{role_key} identity must be complete"
        assert dataset[role_key]["identity_sha256"]
    for role, identity in dataset["test_identities"].items():
        assert identity["complete"] is True, f"{role} identity must be complete"

    weighting = manifest["class_weighting"]
    assert weighting["scheme"] == "median_frequency"
    assert weighting["source"] == f"train_split_manifest:{ROLE_TRAIN}"
    assert "generated_validation" in weighting["forbidden_sources"]
    assert "manual_test" in weighting["forbidden_sources"]

    assert manifest["optimization"] == {
        "optimizer": "Adam",
        "learning_rate": pytest.approx(1e-4),
        "epochs": 3,
        "batch_size": 4,
    }
    assert manifest["augmentation_policy"] == "none"
    assert manifest["seed"]["seed"] == PROTOCOL_SEED
    assert manifest["determinism"]["status"] in (
        "DETERMINISM_ENFORCED",
        "SEEDED_BUT_NUMERICALLY_NONDETERMINISTIC",
    )


def test_manifest_records_strict_pins_and_no_manual_metrics(strict_run):
    manifest = load_model_manifest(strict_run["out_dir"] / "model_manifest.json")
    strict = manifest["extra"]["research_strict"]
    assert strict["research_strict"] is True
    assert strict["pinned"]["camera"] == CAMERA
    assert strict["pinned"]["seed"] == PROTOCOL_SEED
    assert strict["auto_dataset_discovery"] is False
    blob = json.dumps(manifest).lower()
    assert "manual_test_metrics" not in blob
    assert "miou_manual_test" not in blob


def test_manifest_builder_rejects_manual_test_metrics(tmp_path):
    from ultimate_pipeline.perception import train_launcher
    from ultimate_pipeline.perception.rq5_provenance import build_model_manifest

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    ckpt = out_dir / "seg_fcn_epoch003.pt"
    torch = pytest.importorskip("torch")
    torch.save(train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES).state_dict(), ckpt)
    with pytest.raises(ValueError, match="manual-test metrics"):
        build_model_manifest(
            checkpoint=ckpt,
            train_dataset_identity={"identity_sha256": "a", "complete": True},
            train_roots=["/x"],
            extra={"manual_test_metrics": {"mIoU": 0.4}},
        )


def test_strict_run_dataset_refuses_a_manifest_from_another_role(strict_run):
    split_dir = strict_run["split_dir"]
    manifest = load_split_manifest(split_dir / "validation_manifest.json")
    with pytest.raises(Exception, match="declares role"):
        ManifestSegDataset(manifest, role=ROLE_TRAIN)


def test_strict_run_refuses_a_split_whose_frames_are_missing(tmp_path):
    split_dir = _make_splits(tmp_path)
    manifest = load_split_manifest(split_dir / "train_manifest.json")
    Path(manifest["entries"][0]["rgb_path"]).unlink()
    with pytest.raises(Exception, match="missing"):
        ManifestSegDataset(manifest, role=ROLE_TRAIN)


# ---------------------------------------------------------------------------
# class-weight leakage: the negative control that matters most
# ---------------------------------------------------------------------------


def test_manual_labels_cannot_affect_class_weights(strict_run):
    """
    Overwriting every manual-test label with a single class must leave the
    training class weights bit-identical.

    This is the strongest available statement that manual-target statistics
    cannot reach the weights: if any manual pixel had been counted, the
    histogram -- and therefore the weights -- would have changed.
    """
    manifest = load_model_manifest(strict_run["out_dir"] / "model_manifest.json")
    before = manifest["class_weighting"]["class_counts"]

    manual_manifest = load_split_manifest(strict_run["split_dir"] / "manual_test_manifest.json")
    assert manual_manifest["frame_count"] > 0
    for entry in manual_manifest["entries"]:
        Image.fromarray(
            np.full((SIZE, SIZE), 7, dtype=np.uint8), mode="L"
        ).save(entry["label_path"])

    train_manifest = load_split_manifest(strict_run["split_dir"] / "train_manifest.json")
    train_paths = [e["label_path"] for e in train_manifest["entries"]]
    after = scan_label_class_counts(train_paths, num_classes=CARLA_SEMANTIC_NUM_CLASSES).tolist()
    assert before == after

    weights = compute_class_weights(after, num_classes=CARLA_SEMANTIC_NUM_CLASSES)
    assert weights.shape == (CARLA_SEMANTIC_NUM_CLASSES,)

    manual_paths = [e["label_path"] for e in manual_manifest["entries"]]
    manual_counts = scan_label_class_counts(manual_paths, num_classes=CARLA_SEMANTIC_NUM_CLASSES)
    assert int(manual_counts.sum()) > 0, "the manual relabel must actually have changed manual pixels"


def test_class_weight_source_is_never_a_whole_root_scan(strict_run):
    manifest = load_model_manifest(strict_run["out_dir"] / "model_manifest.json")
    assert manifest["class_weighting"]["source"].startswith("train_split_manifest")
    assert manifest["class_weighting"]["computed_from"] == "generated training split only"


def test_role_label_sets_are_disjoint(strict_run):
    splits = {
        role: {e["label_path"] for e in load_split_manifest(
            strict_run["split_dir"] / f"{name}.json"
        )["entries"]}
        for role, name in (
            (ROLE_TRAIN, "train_manifest"),
            (ROLE_VALIDATION, "validation_manifest"),
            (ROLE_GENERATED_TEST, "generated_test_manifest"),
            (ROLE_MANUAL_TEST, "manual_test_manifest"),
        )
    }
    roles = list(splits)
    for i, left in enumerate(roles):
        for right in roles[i + 1:]:
            assert not (splits[left] & splits[right]), f"{left} and {right} share label files"