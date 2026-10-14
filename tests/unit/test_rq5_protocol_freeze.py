# tests/unit/test_rq5_protocol_freeze.py
# -*- coding: utf-8 -*-
"""P12/NEW-218: RQ5 protocol freeze contract + audit + trainer seeding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.rq5_contract_audit import REQUIRED, audit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "configs" / "rq5_protocol_freeze_v1.json"


def _doc():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_contract_exists_and_versioned():
    doc = _doc()
    assert doc["schema"] == "rq5_protocol_freeze/v1"
    assert doc["status"] == "FROZEN"
    assert "amendment_policy" in doc


def test_all_required_decisions_frozen():
    decisions = _doc()["decisions"]
    for name in REQUIRED:
        entry = decisions.get(name)
        assert isinstance(entry, dict), name
        assert entry.get("value") not in (None, ""), name
        assert entry.get("provenance") in ("repo_default", "campaign_frozen"), name
        assert entry.get("source"), name


def test_p12_extra_freezes_present():
    decisions = _doc()["decisions"]
    for name in ("lr_schedule", "batch_size", "primary_metric",
                 "confidence_interval_method", "transfer_comparison_matrix",
                 "failure_policy", "rq5b_boundary", "no_manual_leak_rule",
                 "seed_policy", "checkpoint_selection"):
        assert name in decisions, name


def test_no_manual_leak_rule_explicit():
    rule = _doc()["decisions"]["no_manual_leak_rule"]["value"]
    assert "never" in rule.lower() or "no manual" in rule.lower()


def test_rq5b_boundary_forbids_unlabeled_accuracy():
    boundary = _doc()["decisions"]["rq5b_boundary"]["value"]
    assert "never" in boundary.lower()
    assert "accuracy" in boundary.lower()


def test_audit_passes_with_frozen_contract():
    report = audit(REPO_ROOT)
    assert report["status"] == "PASS", report["missing_decisions"]
    assert report["missing_decisions"] == []
    assert report["scientific_choices_filled"] is False


def test_legacy_audit_without_contract_stays_fail(tmp_path):
    from tools.rq5_contract_audit import _audit_legacy
    report = _audit_legacy(tmp_path)
    assert report["status"] == "FAIL"


def test_seed_list_frozen_and_explicit():
    seeds = _doc()["decisions"]["seed_policy"]["value"]
    assert "7" in seeds and "17" in seeds and "42" in seeds


def _tiny_dataset(root: Path) -> Path:
    import numpy as np
    from PIL import Image
    ds = root / "ds"
    for sub in ("rgb/front", "semseg_raw/front"):
        (ds / sub).mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(0)
    for i in range(4):
        Image.fromarray((rng.rand(16, 16, 3) * 255).astype("uint8")).save(ds / "rgb/front" / f"f{i}.png")
        Image.fromarray((rng.randint(0, 5, (16, 16))).astype("uint8")).save(ds / "semseg_raw/front" / f"f{i}.png")
    return ds


def _run_train(monkeypatch, ds: Path, out: Path, seed: str):
    from ultimate_pipeline.perception import min_train_segmentation as m
    monkeypatch.setattr("sys.argv", ["train", "--dataset", str(ds), "--camera", "front",
                                     "--out-dir", str(out), "--epochs", "1",
                                     "--batch", "2", "--seed", seed, "--device", "cpu",
                                     "--no-class-weights"])
    m.main()
    return json.loads((out / "metrics.json").read_text(encoding="utf-8"))


def test_seeded_training_order_deterministic(tmp_path, monkeypatch):
    ds = _tiny_dataset(tmp_path)
    a = _run_train(monkeypatch, ds, tmp_path / "a", "7")
    b = _run_train(monkeypatch, ds, tmp_path / "b", "7")
    assert a["seed"] == 7
    assert a["loss"] == b["loss"]
