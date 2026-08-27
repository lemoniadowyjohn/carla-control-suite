"""ultimate_pipeline/perception/perception_metrics_simple.py -- lightweight, CARLA-free
recording-directory metrics + validation gate, wired into main_pipeline.py and the domain-gap/
GNN experiment tooling. Directly relevant to a known defect class from this session's earlier
whole-pipeline audit (perception writes EMPTY labels -> training blocked): this module is what
would (or should) catch that at the source, so its counting/validation logic matters. Found
untested via the orphaned-.pyc sweep.
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.perception.perception_metrics_simple import (
    compute_metrics,
    validate_recording,
)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

def test_compute_metrics_missing_dir_reports_not_exists(tmp_path: Path):
    metrics = compute_metrics(tmp_path / "does_not_exist")
    assert metrics["exists"] is False
    assert metrics["rgb_frames"] == 0
    assert metrics["lidar_frames"] == 0


def test_compute_metrics_counts_image_files_by_extension(tmp_path: Path):
    _touch(tmp_path / "rgb" / "0001.png")
    _touch(tmp_path / "rgb" / "0002.jpg")
    _touch(tmp_path / "rgb" / "0003.JPEG")  # uppercase extension must still count
    _touch(tmp_path / "rgb" / "readme.txt")  # non-image, must not count

    metrics = compute_metrics(tmp_path)

    assert metrics["exists"] is True
    assert metrics["total_images"] == 3
    assert metrics["rgb_frames"] == 3


def test_compute_metrics_counts_lidar_files_by_extension(tmp_path: Path):
    _touch(tmp_path / "lidar" / "0001.ply")
    _touch(tmp_path / "lidar" / "0002.pcd")
    _touch(tmp_path / "lidar" / "0003.bin")
    _touch(tmp_path / "lidar" / "0004.npz")
    _touch(tmp_path / "lidar" / "0005.txt")  # not a recognized lidar extension

    metrics = compute_metrics(tmp_path)

    assert metrics["lidar_frames"] == 4


def test_compute_metrics_flags_pngs_in_a_marked_subfolder(tmp_path: Path):
    # NOTE: pytest derives tmp_path from the test function's own name -- a test name
    # containing "seg" or "semantic" would pollute every path under tmp_path and defeat
    # this test (the heuristic matches on the FULL path string, not just the immediate
    # parent folder), so this test name deliberately avoids both substrings.
    marker_root = tmp_path / "capture_root"
    _touch(marker_root / "semantic_seg" / "0001.png")
    _touch(marker_root / "rgb" / "0001.png")

    metrics = compute_metrics(marker_root)

    assert metrics["semantic_frames"] == 1
    # semantic pngs also satisfy the generic image extension count (documented overlap,
    # not double-exclusion) -- both frames are .png so total_images counts both.
    assert metrics["total_images"] == 2


def test_compute_metrics_folder_inventory_depth_capped_at_two(tmp_path: Path):
    _touch(tmp_path / "a" / "b" / "c" / "d" / "file.png")

    metrics = compute_metrics(tmp_path)

    # "a", "a/b", "a/b/c" have <=2 slashes; "a/b/c/d" (3 slashes) must be excluded
    assert "a" in metrics["folders"]
    assert "a/b" in metrics["folders"]
    assert "a/b/c" in metrics["folders"]
    assert "a/b/c/d" not in metrics["folders"]


def test_compute_metrics_recording_dir_field_is_a_string():
    metrics = compute_metrics(Path("some") / "path")
    assert isinstance(metrics["recording_dir"], str)


# ---------------------------------------------------------------------------
# validate_recording
# ---------------------------------------------------------------------------

def test_validate_recording_missing_dir_fails():
    result = validate_recording({"exists": False, "rgb_frames": 0, "lidar_frames": 0})
    assert result["ok"] is False
    assert "recording_dir_missing" in result["reasons"]


def test_validate_recording_enough_rgb_frames_passes():
    result = validate_recording({"exists": True, "rgb_frames": 5, "lidar_frames": 0}, min_rgb=1)
    assert result["ok"] is True
    assert result["reasons"] == []


def test_validate_recording_zero_rgb_frames_fails_by_default():
    # This is exactly the failure mode this module exists to catch: a capture run that
    # produced a directory structure but zero actual RGB frames (empty-labels-class bug).
    result = validate_recording({"exists": True, "rgb_frames": 0, "lidar_frames": 0})
    assert result["ok"] is False
    assert any("rgb_frames" in r for r in result["reasons"])


def test_validate_recording_require_rgb_false_skips_rgb_check():
    result = validate_recording(
        {"exists": True, "rgb_frames": 0, "lidar_frames": 0}, require_rgb=False,
    )
    assert result["ok"] is True


def test_validate_recording_require_lidar_true_enforces_min_lidar():
    result = validate_recording(
        {"exists": True, "rgb_frames": 5, "lidar_frames": 0},
        require_lidar=True, min_lidar=1,
    )
    assert result["ok"] is False
    assert any("lidar_frames" in r for r in result["reasons"])


def test_validate_recording_multiple_failures_all_accumulate():
    result = validate_recording(
        {"exists": False, "rgb_frames": 0, "lidar_frames": 0},
        require_lidar=True, min_lidar=1,
    )
    assert result["ok"] is False
    assert len(result["reasons"]) == 3  # missing dir + rgb + lidar, none short-circuits


def test_validate_recording_handles_none_frame_counts_gracefully():
    # compute_metrics never produces None, but validate_recording is a public function that
    # could receive a hand-built metrics dict -- must not raise on missing/None keys.
    result = validate_recording({"exists": True, "rgb_frames": None, "lidar_frames": None})
    assert result["ok"] is False
    assert result["rgb_frames"] == 0


def test_compute_metrics_then_validate_recording_end_to_end_real_directory(tmp_path: Path):
    _touch(tmp_path / "rgb" / "0001.png")
    _touch(tmp_path / "rgb" / "0002.png")
    metrics = compute_metrics(tmp_path)
    result = validate_recording(metrics, min_rgb=2)
    assert result["ok"] is True
