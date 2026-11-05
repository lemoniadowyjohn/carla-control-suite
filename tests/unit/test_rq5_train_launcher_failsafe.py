"""Fail-closed regression coverage for the RQ5 training launcher."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def test_pretraining_contract_error_returns_failure_writes_receipt_and_uses_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A frozen-contract rejection must not turn into an AttributeError or success."""
    from ultimate_pipeline.perception import train_launcher as launcher
    from ultimate_pipeline.perception.rq5_provenance import PretrainingContractError

    root = tmp_path / "dataset"
    root.mkdir()
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "train_launcher.py",
            "--dataset",
            str(root),
            "--out-dir",
            str(out_dir),
            "--no-class-weights",
        ],
    )
    monkeypatch.setattr(launcher, "enforce_dataset_acceptance", lambda *args, **kwargs: {"total_paired_frames": 1})
    monkeypatch.setattr(launcher, "validate_num_classes", lambda value: value)
    monkeypatch.setattr(launcher, "seed_everything", lambda value: {"seed": value})
    monkeypatch.setattr(launcher, "SemanticSegDataset", lambda *args, **kwargs: object())
    monkeypatch.setattr(launcher, "DataLoader", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        launcher,
        "_build_model",
        lambda *_: (_ for _ in ()).throw(PretrainingContractError("frozen contract rejected")),
    )

    assert launcher._main_impl() == 1
    captured = capsys.readouterr()
    assert "pretraining contract violation: frozen contract rejected" in captured.err
    assert "AttributeError" not in captured.err
    receipt = json.loads((out_dir / "training_failure.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "TRAINING_ABORTED_PRETRAINING_CONTRACT"
    assert receipt["failure"]["message"] == "frozen contract rejected"
    assert not (out_dir / "SUCCESS.txt").exists()


def test_stale_success_revocation_failure_is_explicit_and_preserves_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale success that cannot be revoked blocks the new run rather than failing open."""
    from ultimate_pipeline.perception import train_launcher as launcher

    success = tmp_path / "SUCCESS.txt"
    success.write_text("stale success\n", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_for_success(self: Path, *args, **kwargs) -> None:
        if self == success:
            raise PermissionError("denied by test")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_for_success)
    with pytest.raises(RuntimeError, match="Failed to revoke stale SUCCESS.txt") as raised:
        launcher._revoke_stale_success(tmp_path)

    assert isinstance(raised.value.__cause__, PermissionError)
    assert success.exists()


def test_launcher_refuses_admission_when_stale_success_cannot_be_revoked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted re-run cannot start training while stale success is visible."""
    from ultimate_pipeline.perception import train_launcher as launcher

    root = tmp_path / "dataset"
    root.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    success = out_dir / "SUCCESS.txt"
    success.write_text("stale success\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["train_launcher.py", "--dataset", str(root), "--out-dir", str(out_dir)],
    )
    admission_reached = False

    def should_not_admit(*args, **kwargs):
        nonlocal admission_reached
        admission_reached = True
        raise AssertionError("training admission must not run after failed stale-success revocation")

    original_unlink = Path.unlink

    def fail_for_success(self: Path, *args, **kwargs) -> None:
        if self == success:
            raise PermissionError("denied by test")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(launcher, "enforce_dataset_acceptance", should_not_admit)
    monkeypatch.setattr(Path, "unlink", fail_for_success)

    with pytest.raises(RuntimeError, match="Failed to revoke stale SUCCESS.txt") as raised:
        launcher._main_impl()

    assert isinstance(raised.value.__cause__, PermissionError)
    assert not admission_reached
    assert success.exists()
