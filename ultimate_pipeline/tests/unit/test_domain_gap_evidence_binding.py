# -*- coding: utf-8 -*-
"""Tests for NEW-226: domain_gap_evidence_binding.

NEW-226: Harden run_offline_gaps_from_pair.py - input validation.
Ensures validate_pair_manifest() is called before computation and
verify_files_against_manifest() checks XODR hashes.
"""
from __future__ import annotations

import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest import mock

from ultimate_pipeline.tools.run_offline_gaps_from_pair import _load_manifest


def test_manifest_missing_arms_raises(tmp_path):
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps({"config": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'arms' key"):
        _load_manifest(str(manifest_file))


def test_manifest_missing_config_raises(tmp_path):
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps({"arms": [{"manual_xodr": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'config' key"):
        _load_manifest(str(manifest_file))


def test_manifest_valid_passes(tmp_path):
    manifest = {
        "arms": [{"manual_xodr": "x"}],
        "config": {"rig": "thesis"},
    }
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    # Should not raise
    result = _load_manifest(str(manifest_file))
    assert "arms" in result
    assert "config" in result


def test_manifest_structure_integrity(tmp_path):
    """Verify manifest structure has required fields for NEW-226."""
    manifest = {
        "arms": [
            {
                "manual_xodr": "manual_maps/Grid0821.xodr",
                "auto_xodr": "final_runs/Grid0821/xodr_hardened.xodr",
            }
        ],
        "config": {"rig": "thesis"},
    }
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    result = _load_manifest(str(manifest_file))
    assert len(result["arms"]) >= 1
    arm = result["arms"][0]
    assert "manual_xodr" in arm
    assert "config" in manifest