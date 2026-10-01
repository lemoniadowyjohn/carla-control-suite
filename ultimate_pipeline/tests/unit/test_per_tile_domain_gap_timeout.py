# -*- coding: utf-8 -*-
"""Tests for NEW-228: per_tile_domain_gap_timeout.

NEW-228: Timeout handling for per-tile domain gap computation.
Tests that per-tile stages respect timeouts and don't hang indefinitely.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import pytest
from pathlib import Path
from unittest import mock

import ultimate_pipeline.pipeline_stages.stage_12_domain_gap as stage_mod
from ultimate_pipeline.pipeline_stages.stage_12_domain_gap import _step12_domain_gap


def test_per_tile_timeout_handled_gracefully():
    """Verify that per-tile timeout is handled gracefully without hanging (NEW-228)."""
    from unittest.mock import Mock

    fake_settings = Mock()
    fake_settings.ENABLE_DOMAIN_GAP = True
    fake_settings.MANUAL_MAP_XODR = str(Path(tempfile.mkdtemp()) / "manual.xodr")
    fake_settings.MANUAL_REFERENCE_XODR = None
    fake_settings.MANUAL_TILES_DIR = None
    fake_settings.MANUAL_TILES_ROOT = None
    fake_settings.PERCEPTION_MANUAL_JSON = None
    fake_settings.PERCEPTION_AUTO_JSON = None
    fake_settings.DOMAIN_GAP_OUT_DIR = "domain_gap"
    (Path(fake_settings.MANUAL_MAP_XODR)).write_text("<OpenDRIVE/>", encoding="utf-8")

    fake_self = Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(Path(tempfile.mkdtemp()))
    fake_self.vreport = Mock()
    fake_self.vreport.data = {}
    del fake_self.artifact_recorder

    patches = {
        "os": __import__("os"),
        "json": __import__("json"),
        "Path": __import__("pathlib").Path,
        "TileMetadata": Mock(),
        "run_full_domain_gap": mock.Mock(
            side_effect=TimeoutError("per-tile stage timed out")
        ),
    }

    with mock.patch.multiple(stage_mod, create=True, **patches), \
         mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
        # Should not hang; should complete with warning logged (but not raise)
        _step12_domain_gap(fake_self, "auto.xodr")
        # Verify that vreport.error was called (indicating the error was caught and logged)
        fake_self.vreport.add.assert_any_call("domain_gap", "error", "per-tile stage timed out")


def test_no_hang_on_missing_tiles():
    """Verify stage handles missing tiles directory gracefully (NEW-228)."""
    from unittest.mock import Mock

    fake_settings = Mock()
    fake_settings.ENABLE_DOMAIN_GAP = True
    fake_settings.MANUAL_MAP_XODR = str(Path(tempfile.mkdtemp()) / "manual.xodr")
    fake_settings.MANUAL_REFERENCE_XODR = None
    fake_settings.MANUAL_TILES_DIR = None  # No tiles dir
    fake_settings.MANUAL_TILES_ROOT = None
    fake_settings.PERCEPTION_MANUAL_JSON = None
    fake_settings.PERCEPTION_AUTO_JSON = None
    fake_settings.DOMAIN_GAP_OUT_DIR = "domain_gap"
    (Path(fake_settings.MANUAL_MAP_XODR)).write_text("<OpenDRIVE/>", encoding="utf-8")

    fake_self = Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(Path(tempfile.mkdtemp()))
    fake_self.vreport = Mock()
    fake_self.vreport.data = {}
    del fake_self.artifact_recorder

    patches = {
        "os": __import__("os"),
        "json": __import__("json"),
        "Path": __import__("pathlib").Path,
        "TileMetadata": Mock(),
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
         mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
        # Should not hang; should complete successfully
        _step12_domain_gap(fake_self, "auto.xodr")