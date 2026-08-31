# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/perception/perception_metrics.py.

Live via tools/run_perception_pair.py. Zero prior test coverage. No bug
found -- solid, defensive "best-effort" implementation matching its own
docstring ("Never raises").
"""
from __future__ import annotations

import struct

from ultimate_pipeline.perception.perception_metrics import (
    _extract_timestamp_from_name,
    _median,
    _read_bin_point_count,
    _read_ply_point_count,
    compute_perception_metrics,
)


# ---------------------------------------------------------------------------
# _median
# ---------------------------------------------------------------------------


def test_median_odd_count():
    assert _median([3.0, 1.0, 2.0]) == 2.0


def test_median_even_count_averages_middle_two():
    assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_median_empty_returns_none():
    assert _median([]) is None


# ---------------------------------------------------------------------------
# _extract_timestamp_from_name
# ---------------------------------------------------------------------------


def test_extract_timestamp_uses_last_number_in_name():
    assert _extract_timestamp_from_name("cam_front_00001234") == 1234


def test_extract_timestamp_no_digits_returns_none():
    assert _extract_timestamp_from_name("no_numbers_here") is None


# ---------------------------------------------------------------------------
# _read_bin_point_count
# ---------------------------------------------------------------------------


def test_read_bin_point_count_computes_from_file_size(tmp_path):
    p = tmp_path / "cloud.bin"
    p.write_bytes(b"\x00" * (16 * 5))  # 5 points, stride 16 bytes (4 floats)
    assert _read_bin_point_count(p) == 5


def test_read_bin_point_count_wrong_stride_returns_none(tmp_path):
    p = tmp_path / "cloud.bin"
    p.write_bytes(b"\x00" * 17)  # not a multiple of 16
    assert _read_bin_point_count(p) is None


def test_read_bin_point_count_empty_file_returns_none(tmp_path):
    p = tmp_path / "cloud.bin"
    p.write_bytes(b"")
    assert _read_bin_point_count(p) is None


# ---------------------------------------------------------------------------
# _read_ply_point_count
# ---------------------------------------------------------------------------


def test_read_ply_point_count_parses_header(tmp_path):
    p = tmp_path / "cloud.ply"
    p.write_bytes(
        b"ply\nformat ascii 1.0\nelement vertex 42\nproperty float x\nend_header\n"
    )
    assert _read_ply_point_count(p) == 42


def test_read_ply_point_count_missing_header_returns_none(tmp_path):
    p = tmp_path / "cloud.ply"
    p.write_bytes(b"not a ply file")
    assert _read_ply_point_count(p) is None


# ---------------------------------------------------------------------------
# compute_perception_metrics
# ---------------------------------------------------------------------------


def test_missing_run_dir_disabled():
    result = compute_perception_metrics("/does/not/exist/anywhere")
    assert result["enabled"] is False
    assert result["reason"] == "run_dir_missing"


def test_empty_run_dir_no_sensor_data(tmp_path):
    result = compute_perception_metrics(str(tmp_path))
    assert result["enabled"] is False
    assert result["reason"] == "no_sensor_data_found"


def test_lidar_bin_files_counted(tmp_path):
    lidar_dir = tmp_path / "lidar"
    lidar_dir.mkdir()
    for i in range(3):
        (lidar_dir / f"frame_{i:06d}.bin").write_bytes(b"\x00" * (16 * (10 + i)))

    result = compute_perception_metrics(str(tmp_path))
    assert result["enabled"] is True
    assert result["lidar"]["frames"] == 3
    assert result["lidar"]["point_counts"]["min"] == 10
    assert result["lidar"]["point_counts"]["max"] == 12
    assert result["lidar"]["point_counts"]["median"] == 11.0


def test_camera_images_counted_per_subdirectory(tmp_path):
    cam_dir = tmp_path / "camera_front"
    cam_dir.mkdir()
    from PIL import Image

    for i in range(2):
        Image.new("RGB", (64, 48), (i * 10, 0, 0)).save(cam_dir / f"img_{i}.png")

    result = compute_perception_metrics(str(tmp_path))
    assert result["enabled"] is True
    assert result["camera"]["counts"] == {"camera_front": 2}
    assert result["camera"]["total_frames"] == 2
    assert result["camera"]["resolution"] == {"width": 64, "height": 48}


def test_time_span_computed_from_extracted_timestamps(tmp_path):
    lidar_dir = tmp_path / "lidar"
    lidar_dir.mkdir()
    (lidar_dir / "frame_000100.bin").write_bytes(b"\x00" * 16)
    (lidar_dir / "frame_000500.bin").write_bytes(b"\x00" * 16)

    result = compute_perception_metrics(str(tmp_path))
    assert result["time_span"] == {"start": 100, "end": 500, "duration": 400}
