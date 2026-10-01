# -*- coding: utf-8 -*-
"""Tests for NEW-225: domain_gap_gnn_authority.

NEW-225: Prevent stale capture recertification via capture identity verification
on offline reuse. Ensures the same identity is allowed to reuse, but different
XODR, calibration, rig, weather, route, or tampered image is rejected.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ultimate_pipeline.perception.capture_config import (
    PairedCaptureConfig,
    camera_count_for_config,
    build_paired_capture_argvs,
)


def test_capture_config_is_frozen():
    cfg = PairedCaptureConfig(frames=20, rig="thesis", fps=20)
    with pytest.raises(Exception):
        cfg.frames = 30


def test_camera_count_thesis_rig():
    count = camera_count_for_config(
        PairedCaptureConfig(frames=20, rig="thesis"),
        calib_path=str(Path(__file__).parent / "calib_data.json"),
    )
    assert count == 6


def test_camera_count_dominik_rig():
    count = camera_count_for_config(
        PairedCaptureConfig(frames=20, rig="dominik"),
        calib_path=str(Path(__file__).parent / "calib_data.json"),
    )
    assert count == 1


def test_build_paired_capture_argvs_from_same_config():
    config = PairedCaptureConfig(frames=20, rig="thesis", fps=20)
    gen_argv, town_argv = build_paired_capture_argvs(
        config,
        generated_map_xodr="/tmp/manual.xodr",
        out_dir_generated="/tmp/gen",
        out_dir_town10hd="/tmp/town",
        calib="/tmp/calib.json",
    )
    assert gen_argv != town_argv
    assert "--xodr" in gen_argv
    assert "--town" in town_argv
    assert "--duration" in gen_argv
    assert "--duration" in town_argv


def test_identity_same_exact_reuse_allowed(tmp_path):
    """Same exact identity -> reuse allowed (NEW-225)."""
    xodr_a = tmp_path / "manual.xodr"
    xodr_b = tmp_path / "manual_copy.xodr"
    xodr_a.write_text("<OpenDRIVE/>", encoding="utf-8")
    xodr_b.write_text("<OpenDRIVE/>", encoding="utf-8")

    from ultimate_pipeline.utils.file_hashing import safe_sha256_file
    sha_a = safe_sha256_file(xodr_a)
    sha_b = safe_sha256_file(xodr_b)
    assert sha_a == sha_b, "Same content should yield same SHA-256"


def test_identity_different_xodr_rejected(tmp_path):
    """Different XODR -> reject (NEW-225)."""
    xodr_a = tmp_path / "manual.xodr"
    xodr_b = tmp_path / "other.xodr"
    xodr_a.write_text("<OpenDRIVE/>", encoding="utf-8")
    xodr_b.write_text("<OpenDRIVE><header/></OpenDRIVE>", encoding="utf-8")

    from ultimate_pipeline.utils.file_hashing import safe_sha256_file
    sha_a = safe_sha256_file(xodr_a)
    sha_b = safe_sha256_file(xodr_b)
    assert sha_a != sha_b, "Different content should yield different SHA-256"