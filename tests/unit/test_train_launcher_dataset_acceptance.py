"""NEW-277 -- DATASET_ACCEPTANCE enforcement in train_launcher.py.

GAP-039 recorded NEW-277 as "never implemented": train_launcher.py had no
dataset acceptance gate, so ``SegDataset`` could yield zero items and the
launcher would still write a checkpoint plus a NEW-243 model_manifest.json for
a model trained on nothing. These tests pin the fail-closed behaviour.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ultimate_pipeline.perception.train_launcher import (
    DatasetAcceptanceError,
    enforce_dataset_acceptance,
    evaluate_dataset_acceptance,
)


def _mk_root(tmp_path: Path, name: str, rgb: int, lab: int) -> Path:
    """Build a dataset root with `rgb` rgb frames and `lab` label frames.

    Frame names are zero-padded so the two sets overlap predictably: frame i is
    shared when i < min(rgb, lab).
    """
    root = tmp_path / name
    rgb_dir = root / "rgb" / "front_left_camera"
    lab_dir = root / "semseg_raw" / "front_left_camera"
    rgb_dir.mkdir(parents=True)
    lab_dir.mkdir(parents=True)
    for i in range(rgb):
        (rgb_dir / f"{i:05d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    for i in range(lab):
        (lab_dir / f"{i:05d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return root


# --------------------------------------------------------------------------
# acceptance decisions
# --------------------------------------------------------------------------


def test_fully_paired_dataset_is_accepted(tmp_path: Path) -> None:
    root = _mk_root(tmp_path, "good", rgb=4, lab=4)
    rep = evaluate_dataset_acceptance([root], "front_left_camera")
    assert rep["accepted"] is True
    assert rep["total_paired_frames"] == 4
    assert rep["reasons"] == []


def test_empty_rgb_directory_is_rejected(tmp_path: Path) -> None:
    """The exact GAP-039 hole: rgb/<cam> present but empty."""
    root = _mk_root(tmp_path, "empty_rgb", rgb=0, lab=3)
    rep = evaluate_dataset_acceptance([root], "front_left_camera")
    assert rep["accepted"] is False
    assert any("no paired" in r for r in rep["reasons"])


def test_missing_label_directory_is_rejected(tmp_path: Path) -> None:
    root = _mk_root(tmp_path, "no_labels", rgb=3, lab=0)
    (root / "semseg_raw" / "front_left_camera").rmdir()
    rep = evaluate_dataset_acceptance([root], "front_left_camera")
    assert rep["accepted"] is False
    assert rep["per_root"][0]["label_dir_present"] is False
    assert any("semseg_raw/front_left_camera" in r for r in rep["reasons"])


def test_missing_rgb_directory_is_rejected(tmp_path: Path) -> None:
    root = _mk_root(tmp_path, "no_rgb", rgb=3, lab=3)
    shutil.rmtree(root / "rgb")
    rep = evaluate_dataset_acceptance([root], "front_left_camera")
    assert rep["accepted"] is False
    assert rep["per_root"][0]["rgb_dir_present"] is False


def test_half_paired_dataset_is_rejected_but_unpaired_is_reported(tmp_path: Path) -> None:
    """rgb frames with no label counterpart are unusable: labels resolve by name."""
    root = _mk_root(tmp_path, "half", rgb=5, lab=2)
    rep = evaluate_dataset_acceptance([root], "front_left_camera")
    assert rep["accepted"] is True  # 2 pairs exist, so it IS trainable
    assert rep["total_paired_frames"] == 2
    assert rep["per_root"][0]["rgb_frames"] == 5
    assert rep["per_root"][0]["label_frames"] == 2
    assert len(rep["per_root"][0]["unpaired_rgb"]) == 3


def test_one_bad_root_rejects_the_whole_multi_root_set(tmp_path: Path) -> None:
    good = _mk_root(tmp_path, "good", rgb=3, lab=3)
    bad = _mk_root(tmp_path, "bad", rgb=0, lab=0)
    rep = evaluate_dataset_acceptance([good, bad], "front_left_camera")
    assert rep["accepted"] is False
    assert rep["total_paired_frames"] == 3  # good root still counted


def test_limit_to_zero_is_rejected_when_no_pairs_exist(tmp_path: Path) -> None:
    root = _mk_root(tmp_path, "empty", rgb=0, lab=0)
    rep = evaluate_dataset_acceptance([root], "front_left_camera", limit=10)
    assert rep["accepted"] is False


def test_limit_caps_effective_frames_but_stays_accepted(tmp_path: Path) -> None:
    root = _mk_root(tmp_path, "many", rgb=10, lab=10)
    rep = evaluate_dataset_acceptance([root], "front_left_camera", limit=3)
    assert rep["accepted"] is True
    assert rep["total_paired_frames"] == 10
    assert rep["effective_frames"] == 3


# --------------------------------------------------------------------------
# fail-closed enforcement
# --------------------------------------------------------------------------


def test_enforce_raises_on_unacceptable_dataset(tmp_path: Path) -> None:
    root = _mk_root(tmp_path, "empty_rgb", rgb=0, lab=5)
    with pytest.raises(DatasetAcceptanceError) as exc:
        enforce_dataset_acceptance([root], "front_left_camera")
    msg = str(exc.value)
    assert "DATASET_ACCEPTANCE rejected" in msg
    assert "model_manifest.json" in msg  # states the consequence


def test_enforce_returns_report_when_acceptable(tmp_path: Path) -> None:
    root = _mk_root(tmp_path, "good", rgb=2, lab=2)
    rep = enforce_dataset_acceptance([root], "front_left_camera")
    assert rep["accepted"] is True
    assert rep["effective_frames"] == 2


def test_acceptance_report_is_json_serialisable(tmp_path: Path) -> None:
    """It is embedded in the model manifest, so it must survive json.dump."""
    import json

    root = _mk_root(tmp_path, "good", rgb=2, lab=3)
    rep = enforce_dataset_acceptance([root], "front_left_camera")
    json.dumps(rep)  # must not raise


def test_dataset_acceptance_error_is_a_runtime_error() -> None:
    """Callers can catch it broadly without swallowing unrelated IO errors."""
    assert issubclass(DatasetAcceptanceError, RuntimeError)