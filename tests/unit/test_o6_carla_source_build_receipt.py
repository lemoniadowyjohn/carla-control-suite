"""Tests for O6 source build receipt."""
from __future__ import annotations

import json
from pathlib import Path

from tools.carla_source_build_receipt import build_receipt


def test_receipt_has_required_sections(tmp_path: Path):
    receipt = build_receipt(tmp_path / "missing-ue", tmp_path / "missing-carla")
    for section in ("ue4", "carla", "build", "environment"):
        assert section in receipt


def test_missing_roots_are_unknown(tmp_path: Path):
    receipt = build_receipt(tmp_path / "missing-ue", tmp_path / "missing-carla")
    assert receipt["ue4"]["path"]["status"] == "unknown"
    assert receipt["carla"]["path"]["status"] == "unknown"
    assert receipt["build"]["carlaue4_build_status"]["status"] == "unknown"


def test_no_success_inferred_from_missing_executable(tmp_path: Path):
    root = tmp_path / "carla"
    root.mkdir()
    receipt = build_receipt(None, root)
    assert receipt["carla"]["executable"]["status"] == "unknown"
    assert receipt["build"]["carlaue4_build_status"]["status"] == "unknown"


def test_receipt_serializes(tmp_path: Path):
    json.dumps(build_receipt(None, None), sort_keys=True)
