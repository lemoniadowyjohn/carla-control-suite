# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/perception/capture_config.py.

Covers the RQ3 paired-capture protocol-mismatch fix (see
submission/results/perception_rq3_bounded/paired_metrics.json and
capture_attempt_log.txt, 2026-05-14): the generated-map and Town10HD sides
of a paired capture must be built from ONE shared `PairedCaptureConfig`, so
frame count and camera rig can never independently drift the way they did
in that recorded run (20 frames/1 camera vs. 8 frames/6 cameras).
"""
from __future__ import annotations

import json

from ultimate_pipeline.perception.capture_config import (
    PairedCaptureConfig,
    RIG_CAMERA_COUNTS,
    build_paired_capture_argvs,
    camera_count_for_config,
    record_route_argv,
)


def _argv_to_dict(argv):
    """Parse a flat CLI argv list into {flag: value_or_True} for assertions."""
    out = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                out[tok] = argv[i + 1]
                i += 2
            else:
                out[tok] = True
                i += 1
        else:
            i += 1
    return out


# ---------------------------------------------------------------------------
# (a) both sides get the same config when constructed from a shared spec
# ---------------------------------------------------------------------------


def test_build_paired_capture_argvs_share_frames_fps_rig_and_seg():
    config = PairedCaptureConfig(frames=20, fps=20, rig="thesis", seg=True)
    generated_argv, town10hd_argv = build_paired_capture_argvs(
        config,
        generated_map_xodr="/maps/generated.xodr",
        out_dir_generated="/out/generated",
        out_dir_town10hd="/out/town10hd",
        calib="/calib/calib_data.json",
    )
    gen = _argv_to_dict(generated_argv)
    t10 = _argv_to_dict(town10hd_argv)

    # The parameters that determine comparability must be IDENTICAL.
    for flag in ("--fps", "--duration", "--rig", "--lidar-format", "--vehicle"):
        assert gen[flag] == t10[flag], f"{flag} drifted between sides: {gen[flag]!r} vs {t10[flag]!r}"
    assert ("--seg" in gen) == ("--seg" in t10) == True

    # The only legitimate difference is the map source and output dir.
    assert "--xodr" in gen and "--xodr" not in t10
    assert "--town" in t10 and "--town" not in gen
    assert gen["--out-dir"] != t10["--out-dir"]


def test_build_paired_capture_argvs_share_front_only_flag():
    config = PairedCaptureConfig(frames=8, fps=10, rig="thesis", front_only=True, seg=False)
    generated_argv, town10hd_argv = build_paired_capture_argvs(
        config,
        generated_map_xodr="/maps/generated.xodr",
        out_dir_generated="/out/generated",
        out_dir_town10hd="/out/town10hd",
        calib="/calib/calib_data.json",
    )
    assert "--front-only" in generated_argv
    assert "--front-only" in town10hd_argv
    assert "--seg" not in generated_argv
    assert "--seg" not in town10hd_argv


def test_record_route_argv_duration_derived_from_frames_and_fps():
    config = PairedCaptureConfig(frames=100, fps=20)
    argv = record_route_argv(
        config,
        out_dir="/out",
        calib="/calib/calib_data.json",
        map_args=["--town", "Town10HD"],
    )
    parsed = _argv_to_dict(argv)
    assert float(parsed["--duration"]) == 5.0  # 100 frames / 20 fps


# ---------------------------------------------------------------------------
# camera_count_for_config
# ---------------------------------------------------------------------------


def test_camera_count_for_config_reads_real_calib_cameras_map(tmp_path):
    calib = tmp_path / "calib_data.json"
    calib.write_text(
        json.dumps(
            {
                "cameras": {
                    "front_left_camera": {},
                    "front_right_camera": {},
                    "left_camera": {},
                    "right_camera": {},
                    "back_left_camera": {},
                    "back_right_camera": {},
                }
            }
        ),
        encoding="utf-8",
    )
    config = PairedCaptureConfig(frames=8, fps=10, rig="thesis", front_only=False)
    assert camera_count_for_config(config, calib_path=str(calib)) == 6


def test_camera_count_for_config_front_only_counts_only_front_cameras(tmp_path):
    calib = tmp_path / "calib_data.json"
    calib.write_text(
        json.dumps(
            {
                "cameras": {
                    "front_left_camera": {},
                    "front_right_camera": {},
                    "left_camera": {},
                    "right_camera": {},
                    "back_left_camera": {},
                    "back_right_camera": {},
                }
            }
        ),
        encoding="utf-8",
    )
    config = PairedCaptureConfig(frames=8, fps=10, rig="thesis", front_only=True)
    assert camera_count_for_config(config, calib_path=str(calib)) == 2


def test_camera_count_for_config_falls_back_to_static_table_when_calib_unreadable():
    config = PairedCaptureConfig(frames=8, fps=10, rig="dominik")
    assert camera_count_for_config(
        config, calib_path="/does/not/exist/calib_data.json"
    ) == RIG_CAMERA_COUNTS["dominik"]


def test_camera_count_for_config_front_only_fallback_is_at_least_one():
    config = PairedCaptureConfig(frames=8, fps=10, rig="thesis", front_only=True)
    assert camera_count_for_config(
        config, calib_path="/does/not/exist/calib_data.json"
    ) == 1
