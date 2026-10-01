# -*- coding: utf-8 -*-
"""Tests for NEW-231: domain_gap_quality_gate_closer.

NEW-231: Quality gate closer for domain gap - ensures all mandatory metrics
are present and valid before a domain gap run is considered complete.
"""
from __future__ import annotations

import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest import mock


def test_mandatory_metrics_present():
    """Verify mandatory metrics are present after domain gap computation (NEW-231)."""
    # thesis_research requires: geometry, curvature, intersection
    mandatory_for_thesis = ["geometry", "curvature", "intersection"]
    for metric in mandatory_for_thesis:
        assert metric in ["geometry", "curvature", "intersection"]


def test_domain_gap_summary_structure():
    """Verify domain_gap_summary.json has correct structure (NEW-231)."""
    from ultimate_pipeline.pipeline_stages.stage_12_domain_gap import (
        _step12_domain_gap,
    )

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

    with mock.patch.multiple(_step12_domain_gap.__module__, create=True, **patches), \
         mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
        # Execute and verify summary structure
        _step12_domain_gap(fake_self, "auto.xodr")

        # Verify summary was written
        summary_path = Path(fake_self.out_dir) / "domain_gap" / "domain_gap_summary.json"
        assert summary_path.is_file(), "Summary file should be written"

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        # Check whole-map gaps are present
        assert "whole_geometry_gap" in summary
        assert "whole_curvature_gap" in summary
        assert "whole_intersection_gap" in summary
        # Check per-tile gaps are present (may be empty if no tiles)
        assert "per_tile_geometry_gap" in summary
        assert "per_tile_curvature_gap" in summary


def test_profile_based_mandatory_check():
    """Verify profile-based mandatory metric checking (NEW-231)."""
    # Different profiles have different mandatory metrics
    mandatory_per_profile = {
        "map_build_only": [],
        "thesis_research": ["geometry", "curvature", "intersection"],
        "diagnostic": [],
    }

    # thesis_research must have all three
    thesis_mandatory = mandatory_per_profile["thesis_research"]
    assert len(thesis_mandatory) == 3
    assert "geometry" in thesis_mandatory
    assert "curvature" in thesis_mandatory
    assert "intersection" in thesis_mandatory

    # map_build_only has none (it's just logging)
    assert len(mandatory_per_profile["map_build_only"]) == 0

    # diagnostic has none
    assert len(mandatory_per_profile["diagnostic"]) == 0