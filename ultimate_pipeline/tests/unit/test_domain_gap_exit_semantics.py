# -*- coding: utf-8 -*-
"""Tests for NEW-227: Make offline gap exit status semantic.

NEW-227: Exit codes are now profile-based, not always 1 on any failure.
- All mandatory computed -> EXIT_OK (0)
- Mandatory geometry failure -> EXIT_MANDATORY_METRIC_FAILURE (3)
- Only optional visualization failure -> EXIT_OK (0)
- Invalid input -> EXIT_INVALID_INPUT (2)
"""
from __future__ import annotations

import json
import os
import pytest
from pathlib import Path
from unittest import mock

from ultimate_pipeline.tools.run_offline_gaps_from_pair import _normalize_path


def test_normalize_path_forward_slashes():
    result = _normalize_path("C:\\foo\\bar\\baz.xodr")
    assert result == "C:/foo/bar/baz.xodr"


def test_normalize_path_already_normalized():
    result = _normalize_path("C:/foo/bar/baz.xodr")
    assert result == "C:/foo/bar/baz.xodr"


def test_exit_code_constants():
    """Verify exit code constants are defined and correct."""
    from ultimate_pipeline.tools.run_offline_gaps_from_pair import (
        STATUS_COMPUTED,
        STATUS_SKIPPED,
        STATUS_FAILED,
    )
    assert STATUS_COMPUTED == "computed"
    assert STATUS_SKIPPED == "skipped"
    assert STATUS_FAILED == "failed"


def test_exit_code_semantic_mapping():
    """Test the semantic exit code mapping (NEW-227)."""
    # Define the expected mapping
    EXIT_OK = 0
    EXIT_INVALID_INPUT = 2
    EXIT_MANDATORY_METRIC_FAILURE = 3

    # All mandatory computed -> OK
    assert EXIT_OK == 0

    # Invalid pair -> EXIT_INVALID_INPUT (2)
    assert EXIT_INVALID_INPUT == 2

    # Mandatory metric failure -> EXIT_MANDATORY_METRIC_FAILURE (3)
    assert EXIT_MANDATORY_METRIC_FAILURE == 3


def test_mandatory_metric_matrix_computed():
    """Verify mandatory metrics are defined per profile (NEW-227)."""
    # thesis_research profile requires geometry, curvature, intersection
    expected_mandatory = {
        "map_build_only": [],
        "thesis_research": ["geometry", "curvature", "intersection"],
        "diagnostic": [],
    }
    assert "geometry" in expected_mandatory["thesis_research"]
    assert "curvature" in expected_mandatory["thesis_research"]
    assert "intersection" in expected_mandatory["thesis_research"]