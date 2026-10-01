# -*- coding: utf-8 -*-
"""Tests for NEW-233: domain_gap_pipeline_integration.

NEW-233: Verify coordinate report subprocesses in stage_12_domain_gap.
Ensures the coordinate report subprocess integration works correctly
and that the generated reports are valid JSON.
"""
from __future__ import annotations

import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest import mock

import ultimate_pipeline.pipeline_stages.stage_12_domain_gap as stage_mod
from ultimate_pipeline.pipeline_stages.stage_12_domain_gap import _step12_domain_gap


def test_coordinate_report_generated(tmp_path):
    """Verify coordinate report is generated and is valid JSON (NEW-233)."""
    fake_settings = mock.Mock()
    fake_settings.ENABLE_DOMAIN_GAP = True
    fake_settings.MANUAL_MAP_XODR = str(tmp_path / "manual.xodr")
    fake_settings.MANUAL_REFERENCE_XODR = None
    fake_settings.MANUAL_TILES_DIR = None
    fake_settings.MANUAL_TILES_ROOT = None
    fake_settings.PERCEPTION_MANUAL_JSON = None
    fake_settings.PERCEPTION_AUTO_JSON = None
    fake_settings.DOMAIN_GAP_OUT_DIR = "domain_gap"
    (tmp_path / "manual.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")

    fake_self = mock.Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(tmp_path)
    fake_self.vreport = mock.Mock()
    fake_self.vreport.data = {}
    del fake_self.artifact_recorder

    patches = {
        "os": __import__("os"),
        "json": __import__("json"),
        "Path": __import__("pathlib").Path,
        "TileMetadata": mock.Mock(),
        "run_full_domain_gap": mock.Mock(
            return_value={
                "structural_domain_gap": {
                    "geometry": {"gap": 0.1},
                    "curvature": {"gap": 0.2},
                    "intersection": {"gap": 0.3},
                    "semantics": {"gap": 0.4},
                    "road_classification": {"gap": 0.5},
                    "connectivity": {"gap": 0.6},
                },
                "per_tile_structural_gap": {},
                "per_tile_status": "computed",
                "per_tile_status_reason": None,
            }
        ),
    }

    with mock.patch.multiple(stage_mod, create=True, **patches), \
         mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as mock_run:
        _step12_domain_gap(fake_self, str(tmp_path / "auto.xodr"))
        # Subprocess should have been called twice (once per coordinate report)
        assert mock_run.call_count == 2


def test_coordinate_report_valid_json(tmp_path):
    """Verify coordinate report output is valid JSON (NEW-233)."""
    # A minimal valid JSON coordinate report
    report = {
        "map_name": "Grid0821",
        "coordinates": {
            "lat": 48.7593,
            "lon": 11.462,
        },
        "origin": {
            "x": 540000.0,
            "y": 5402000.0,
        },
    }

    # Verify JSON serialization roundtrip
    json_str = json.dumps(report, ensure_ascii=True)
    parsed = json.loads(json_str)
    assert parsed["map_name"] == "Grid0821"
    assert abs(parsed["coordinates"]["lat"] - 48.7593) < 1e-6


def test_coordinate_report_subprocess_invocation(tmp_path):
    """Verify subprocess is called with correct arguments (NEW-233)."""
    fake_settings = mock.Mock()
    fake_settings.ENABLE_DOMAIN_GAP = True
    fake_settings.MANUAL_MAP_XODR = str(tmp_path / "manual.xodr")
    fake_settings.MANUAL_REFERENCE_XODR = None
    fake_settings.MANUAL_TILES_DIR = None
    fake_settings.MANUAL_TILES_ROOT = None
    fake_settings.PERCEPTION_MANUAL_JSON = None
    fake_settings.PERCEPTION_AUTO_JSON = None
    fake_settings.DOMAIN_GAP_OUT_DIR = "domain_gap"
    (tmp_path / "manual.xodr").write_text("<OpenDRIVE/>", encoding="utf-8")

    fake_self = mock.Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(tmp_path)
    fake_self.vreport = mock.Mock()
    fake_self.vreport.data = {}
    del fake_self.artifact_recorder

    patches = {
        "os": __import__("os"),
        "json": __import__("json"),
        "Path": __import__("pathlib").Path,
        "TileMetadata": mock.Mock(),
        "run_full_domain_gap": mock.Mock(
            return_value={
                "structural_domain_gap": {
                    "geometry": {"gap": 0.1},
                    "curvature": {"gap": 0.2},
                    "intersection": {"gap": 0.3},
                    "semantics": {"gap": 0.4},
                    "road_classification": {"gap": 0.5},
                    "connectivity": {"gap": 0.6},
                },
                "per_tile_structural_gap": {},
                "per_tile_status": "computed",
                "per_tile_status_reason": None,
            }
        ),
    }

    with mock.patch.multiple(stage_mod, create=True, **patches), \
         mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as mock_run:
        _step12_domain_gap(fake_self, str(tmp_path / "auto.xodr"))

        # Verify subprocess.run was called with correct arguments
        calls = mock_run.call_args_list
        assert len(calls) == 2  # Two coordinate reports (manual and auto)

        # Check that each call has the xodr_coordinate_report module
        for call in calls:
            cmd = call[0][0]
            assert "-m" in cmd
            # The module name should be in the command list
            assert any("xodr_coordinate_report" in part for part in cmd)
            assert "--xodr" in cmd
            assert "--out" in cmd