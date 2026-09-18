#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Perception artifact validation helpers (offline-safe).

These are meant for quick debugging and regression tests:
- Verify that a perception run wrote the expected JSON files.
- Optionally verify that at least N images were saved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


@dataclass
class PerceptionValidation:
    ok: bool
    reason: str
    recording_status: str
    frames_recorded: int
    frames_requested: int
    rgb_dir: str
    lidar_dir: str
    recording_summary_path: str


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_perception_output(
    out_dir: Path | str, *, min_frames: int = 1
) -> PerceptionValidation:
    out_dir = Path(out_dir)
    rec_path = out_dir / "recording_summary.json"
    manifest_path = out_dir / "pair_manifest.json"
    status_path = out_dir / "carla_status.json"

    if not rec_path.exists():
        return PerceptionValidation(
            ok=False,
            reason="missing_recording_summary",
            recording_status="MISSING",
            frames_recorded=0,
            frames_requested=0,
            rgb_dir="",
            lidar_dir="",
            recording_summary_path=str(rec_path),
        )

    try:
        rec = _read_json(rec_path)
    except Exception as exc:  # noqa: BLE001
        return PerceptionValidation(
            ok=False,
            reason=f"invalid_recording_summary_json: {exc}",
            recording_status="INVALID",
            frames_recorded=0,
            frames_requested=0,
            rgb_dir="",
            lidar_dir="",
            recording_summary_path=str(rec_path),
        )

    frames_recorded = int(
        rec.get("frames_recorded")
        or rec.get("rgb_png_total")
        or rec.get("images_saved")
        or 0
    )
    frames_requested = int(
        rec.get("frames_requested") or rec.get("frames") or rec.get("frames_total") or 0
    )
    recording_status = str(rec.get("status") or "").upper() or ""
    if not recording_status:
        # Older/minimal summaries sometimes omit status; infer from frames.
        recording_status = "PASS" if frames_recorded > 0 else "FAIL"

    rgb_dir = ""
    lidar_dir = ""
    if manifest_path.exists():
        try:
            man = _read_json(manifest_path)
            rgb_dir = str(((man.get("outputs") or {}).get("rgb_frames_dir")) or "")
            lidar_dir = str(((man.get("outputs") or {}).get("lidar_dir")) or "")
        except Exception:
            pass

    # Primary signal: PASS + enough frames
    if recording_status == "PASS" and frames_recorded >= int(min_frames):
        return PerceptionValidation(
            ok=True,
            reason="ok",
            recording_status=recording_status,
            frames_recorded=frames_recorded,
            frames_requested=frames_requested,
            rgb_dir=rgb_dir,
            lidar_dir=lidar_dir,
            recording_summary_path=str(rec_path),
        )

    # Otherwise, classify why
    if recording_status in ("SKIP", "SKIPPED"):
        reason = str(rec.get("failure_reason") or "skipped")
    else:
        reason = str(rec.get("failure_reason") or "perception_failed_or_zero_frames")

    return PerceptionValidation(
        ok=False,
        reason=reason,
        recording_status=recording_status,
        frames_recorded=frames_recorded,
        frames_requested=frames_requested,
        rgb_dir=rgb_dir,
        lidar_dir=lidar_dir,
        recording_summary_path=str(rec_path),
    )


def render_lidar_bev(
    lidar_path: Path | str,
    out_path: Path | str,
    *,
    img_size: int = 512,
    range_m: float = 50.0,
) -> bool:
    """Render a simple LiDAR BEV image from a PLY or NPZ point cloud."""
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return False

    points = _load_lidar_points(Path(lidar_path))
    if points is None or len(points) == 0:
        return False

    x = points[:, 0]
    y = points[:, 1]

    # Normalize to image coordinates
    x_img = ((x + range_m) / (2.0 * range_m) * img_size).astype(np.int32)
    y_img = ((y + range_m) / (2.0 * range_m) * img_size).astype(np.int32)

    valid = (x_img >= 0) & (x_img < img_size) & (y_img >= 0) & (y_img < img_size)
    x_img = x_img[valid]
    y_img = y_img[valid]

    img = np.zeros((img_size, img_size), dtype=np.uint8)
    img[y_img, x_img] = 255

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(str(out_path))
    return True


def _load_lidar_points(path: Path) -> Optional["np.ndarray"]:
    try:
        import numpy as np
    except Exception:
        return None

    if not path.exists():
        return None

    if path.suffix.lower() == ".npz":
        try:
            data = np.load(str(path))
            points = data.get("points", data.get("arr_0", None))
            if points is None:
                return None
            return np.asarray(points, dtype=float)
        except Exception:
            return None

    if path.suffix.lower() != ".ply":
        return None

    try:
        with path.open("rb") as f:
            header_lines = []
            vertex_count = 0
            fmt = "ascii"
            prop_count = 0
            while True:
                line = f.readline()
                if not line:
                    return None
                line_str = line.decode("utf-8", errors="ignore").strip()
                header_lines.append(line_str)
                if line_str.startswith("format"):
                    parts = line_str.split()
                    if len(parts) >= 2:
                        fmt = parts[1].strip().lower()
                if line_str.startswith("element vertex"):
                    vertex_count = int(line_str.split()[-1])
                if line_str.startswith("property"):
                    prop_count += 1
                if line_str == "end_header":
                    break

            if vertex_count <= 0:
                return None

            if fmt == "ascii":
                pts = []
                for _ in range(vertex_count):
                    line = f.readline()
                    if not line:
                        break
                    parts = line.decode("utf-8", errors="ignore").strip().split()
                    if len(parts) < 3:
                        continue
                    try:
                        pts.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except Exception:
                        continue
                if not pts:
                    return None
                return np.asarray(pts, dtype=float)

            if fmt.startswith("binary"):
                if prop_count <= 0:
                    prop_count = 4
                count = vertex_count * prop_count
                raw = np.frombuffer(f.read(count * 4), dtype=np.float32)
                if raw.size < count:
                    return None
                raw = raw[:count].reshape(-1, prop_count)
                return raw[:, :3].astype(float)
    except Exception:
        return None

    return None
