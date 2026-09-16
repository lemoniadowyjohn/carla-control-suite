#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/capture_config.py

Shared configuration for RQ3 "paired capture" runs.

Background (see submission/results/perception_rq3_bounded/paired_metrics.json
and capture_attempt_log.txt, dated 2026-05-14): a paired perception capture
compares the SAME route captured from (a) the auto-generated map and (b) the
Town10HD ground-truth control map, so downstream perceptual metrics
(KL-divergence, histogram intersection, ...) can compare the two frame sets.

The 2026-05-14 attempt used two INDEPENDENTLY specified configs for the two
sides: the generated-map side used 20 frames with a single lightweight
camera, while the Town10HD side used 8 frames with a 6-camera rig (and hit a
60s process-budget timeout before finishing). Because frame counts and
camera setups didn't match, every pixel-level metric in paired_metrics.json
came back `null` -- the comparison was structurally impossible to compute.

This module fixes that class of bug by construction: `PairedCaptureConfig`
is a single, frozen (immutable) spec that BOTH capture invocations must be
built from via `record_route_argv()` / `build_paired_capture_argvs()`, so the
two sides of a paired capture can never independently drift apart again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Fallback camera-count table, used only when the calib JSON can't be read
# (e.g. in a unit test with no fixture file, or a future rig name). The
# authoritative source of truth is always the calib file's "cameras" map
# (see camera_count_for_config()) -- this table exists purely so callers
# without a calib file still get a sane, documented default.
#   - "dominik": conventionally a single forward-facing lightweight probe
#     camera (see the legacy generated-map "perception_probe" capture mode).
#   - "thesis": the full Dominik-calibrated 6-camera rig (front/back left,
#     front/back right, left, right) as loaded from calib_data.json.
RIG_CAMERA_COUNTS: Dict[str, int] = {
    "dominik": 1,
    "thesis": 6,
}

_DEFAULT_CALIB_PATH = str(
    Path(__file__).resolve().parent.parent / "sensors" / "calib_data.json"
)


@dataclass(frozen=True)
class PairedCaptureConfig:
    """Capture parameters shared by BOTH sides of an RQ3 paired capture.

    Both the generated-map run and the Town10HD control run MUST be built
    from the same `PairedCaptureConfig` instance (see
    `build_paired_capture_argvs`) -- frame count and camera rig are the two
    knobs that determine whether the resulting frame sets are directly
    comparable, so neither side may specify them independently.
    """

    frames: int
    fps: int = 20
    rig: str = "thesis"
    front_only: bool = False
    seg: bool = True
    lidar_format: str = "npz"
    vehicle: str = "vehicle.audi.a2"
    spawn_index: int = 0
    seed: int = 0
    # None => auto-computed from frames/fps/camera_count (see
    # run_perception_safe._compute_record_route_timeout_s). Set explicitly
    # to override.
    record_route_timeout_s: Optional[float] = None

    def duration_s(self) -> float:
        return float(self.frames) / float(max(1, int(self.fps)))


def camera_count_for_config(
    config: PairedCaptureConfig, *, calib_path: Optional[str] = None
) -> int:
    """Best-effort authoritative camera count for a config.

    Reads the "cameras" map out of the calib JSON (the real source of truth
    for how many cameras a rig spawns) when available; falls back to the
    static `RIG_CAMERA_COUNTS` table otherwise. When `config.front_only` is
    set, only cameras whose name contains "front" are counted (mirroring
    `record_route_fixed._apply_front_only_profile`, which drops all
    non-front cameras); if none match, 1 is used since front-only always
    keeps at least one camera.
    """
    resolved_calib_path = str(calib_path) if calib_path else _DEFAULT_CALIB_PATH
    camera_names: Optional[List[str]] = None
    try:
        raw = json.loads(Path(resolved_calib_path).read_text(encoding="utf-8"))
        cameras = raw.get("cameras") if isinstance(raw, dict) else None
        if isinstance(cameras, dict) and cameras:
            camera_names = list(cameras.keys())
    except Exception:
        camera_names = None

    if camera_names is None:
        base_count = int(RIG_CAMERA_COUNTS.get(str(config.rig), 1))
        if not config.front_only:
            return max(1, base_count)
        # No calib data to filter by name; front-only is at least 1 camera.
        return 1

    if config.front_only:
        front = [n for n in camera_names if "front" in str(n).strip().lower()]
        return max(1, len(front))
    return max(1, len(camera_names))


def record_route_argv(
    config: PairedCaptureConfig,
    *,
    out_dir: str,
    calib: str,
    map_args: Sequence[str],
    host: str = "127.0.0.1",
    port: int = 2000,
    extra: Optional[Sequence[str]] = None,
) -> List[str]:
    """Build the record_route(_fixed) CLI argv for one side of a paired capture.

    `map_args` supplies the mutually-exclusive map source flags, e.g.
    `["--xodr", str(xodr_path)]` or `["--town", "Town10HD"]` -- that is the
    ONE thing that legitimately differs between the two sides of a paired
    capture. Everything else comes from `config`.
    """
    argv: List[str] = list(map_args) + [
        "--calib", str(calib),
        "--out-dir", str(out_dir),
        "--host", str(host),
        "--port", str(int(port)),
        "--fps", str(int(config.fps)),
        "--duration", f"{config.duration_s():.3f}",
        "--rig", str(config.rig),
        "--lidar-format", str(config.lidar_format),
        "--vehicle", str(config.vehicle),
        "--spawn-index", str(int(config.spawn_index)),
        "--seed", str(int(config.seed)),
    ]
    if config.seg:
        argv.append("--seg")
    if config.front_only:
        argv.append("--front-only")
    if extra:
        argv.extend(extra)
    return argv


def build_paired_capture_argvs(
    config: PairedCaptureConfig,
    *,
    generated_map_xodr: str,
    out_dir_generated: str,
    out_dir_town10hd: str,
    calib: str,
    town10hd_town: str = "Town10HD",
    host: str = "127.0.0.1",
    port: int = 2000,
) -> Tuple[List[str], List[str]]:
    """Build BOTH sides of a paired capture from a single shared config.

    Returns (generated_map_argv, town10hd_argv). Both argvs are built from
    the SAME `config` instance, so frame count and camera rig are guaranteed
    identical by construction -- the only difference is the map source flag
    (`--xodr ...` vs `--town Town10HD`) and the output directory.
    """
    generated_map_argv = record_route_argv(
        config,
        out_dir=out_dir_generated,
        calib=calib,
        map_args=["--xodr", str(generated_map_xodr)],
        host=host,
        port=port,
    )
    town10hd_argv = record_route_argv(
        config,
        out_dir=out_dir_town10hd,
        calib=calib,
        map_args=["--town", str(town10hd_town)],
        host=host,
        port=port,
    )
    return generated_map_argv, town10hd_argv
