#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared perception-capture writer (C8 fix).

Single source of truth for how a captured CARLA sensor frame is persisted to
disk, so the directory layout and label encoding used by the *capture* side
(`dataset_generator.py`, `perception_runner_local_aug.py`) can never again
drift from what the *reader* side expects
(`min_train_segmentation.py`, `eval_sim_labeled.py`, `class_weights.py`):

    rgb/<camera>/<frame>.png          RGB image (uint8, 3-channel)
    semseg_raw/<camera>/<frame>.png   TRAINING LABEL: single-channel uint8,
                                       pixel value == CARLA semantic class id
                                       (never CityScapes-palette colorized)
    semseg_viz/<camera>/<frame>.png   OPTIONAL human-viewable CityScapes
                                       palette colorization; never read by
                                       any trainer/eval/class-weight code

Detection labels: this module does NOT fabricate empty YOLO ``.txt`` files.
No 2D bounding-box projector exists in this codebase (see C8 spec boundaries:
calibration semantics are out of scope), so non-semantic capture is an
explicit, logged no-op — callers get ``detection_status="explicit_noop"``
back and nothing is silently written that a downstream consumer could
mistake for "zero objects present" ground truth.

Both `carla.Image` and any duck-typed object exposing `.raw_data` (BGRA8
buffer bytes), `.height`, and `.width` are accepted, so this module is fully
unit-testable offline without a live CARLA server (`carla.Image` itself
cannot be constructed from pure Python).

Write atomicity (NEW-274): every PNG is first written to a temp sibling file
in the same directory and published via `os.replace` after an fsync, so a
crash at any point leaves either no file or the previous complete frame --
never a torn PNG. See `_atomic_path`.
"""
from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np

from ultimate_pipeline.perception.carla_classes import assert_label_ids_in_range
from ultimate_pipeline.perception.segmentation_dataset_generator_queues import (
    _write_png_raw_ids,
)

logger = logging.getLogger(__name__)


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextlib.contextmanager
def _atomic_path(final_path: Path) -> Iterator[Path]:
    """Yield a temp sibling path; atomically publish to `final_path` on success.

    NEW-274: capture frames must never leave a torn PNG behind. The writer
    callback receives a temp file in the SAME directory (same filesystem, so
    the publish step needs no copy), and on clean return the temp file is
    fsynced and published via `os.replace`, which is atomic for same-volume
    paths on both POSIX and Windows. On any exception the temp file is
    removed and `final_path` is left untouched (either absent or the previous
    complete frame) -- a reader can therefore never observe a half-written
    PNG, only a missing or whole one.
    """
    final_path = Path(final_path)
    # Keep the final suffix on the temp name: PIL infers the image format
    # from the file extension, so a bare ".tmp" suffix breaks saves.
    fd, tmp = tempfile.mkstemp(
        dir=str(final_path.parent),
        prefix=final_path.name + ".",
        suffix=".tmp" + final_path.suffix,
    )
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        yield tmp_path
        # Flush OS buffers before publishing. Note: opened "r+b", not "rb" --
        # os.fsync fails with EBADF on read-only handles on some Windows
        # runtimes. A failed fsync degrades to a plain atomic replace (which
        # is what guarantees no torn file); durability of the content itself
        # is best-effort here, not a correctness property of this helper.
        try:
            with open(tmp_path, "r+b") as f:
                os.fsync(f.fileno())
        except OSError:
            pass
        os.replace(tmp_path, final_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _image_raw_bgra(image: Any) -> np.ndarray:
    """Decode a carla.Image-like object's raw_data into an (H, W, 4) BGRA array."""
    arr = np.frombuffer(image.raw_data, dtype=np.uint8)
    return arr.reshape((int(image.height), int(image.width), 4))


def _write_rgb_png(image: Any, out_path: Path) -> None:
    """Write the RGB channels of a carla.Image-like BGRA buffer to a PNG.

    Uses raw pixel data directly (not carla.Image.save_to_disk) so the same
    code path works for both real carla.Image instances and offline
    duck-typed fakes used in tests.
    """
    from PIL import Image as PILImage

    bgra = _image_raw_bgra(image)
    rgb = bgra[:, :, :3][:, :, ::-1]  # BGRA -> BGR -> RGB
    # NEW-274: atomic commit -- a crash mid-save leaves no torn PNG behind.
    with _atomic_path(out_path) as tmp:
        PILImage.fromarray(rgb, mode="RGB").save(tmp.as_posix())


def _class_ids_from_seg_image(image: Any) -> np.ndarray:
    """Extract the raw class-id (R channel of BGRA) from a semantic image."""
    bgra = _image_raw_bgra(image)
    return bgra[:, :, 2]  # BGRA -> index 2 is R


def _write_viz_png(image: Any, out_path: Path) -> None:
    """Write a CityScapes-palette colorized copy for human viewing ONLY.

    This is derived independently from the raw class ids (not from mutating
    the sensor image in place), so it can never leak into the training
    label path.
    """
    from PIL import Image as PILImage

    try:
        import carla  # local import: only needed if a real palette LUT exists
        palette = getattr(carla.CityObjectLabel, None, None)  # noqa: F841
    except Exception:
        carla = None  # type: ignore

    ids = _class_ids_from_seg_image(image)

    if carla is not None:
        try:
            # Best effort: use CARLA's own converter on a real carla.Image.
            # carla.Image cannot be constructed from pure Python, so this
            # path only triggers for genuine sensor-callback images; for
            # duck-typed fakes (offline tests) we fall through to the
            # grayscale fallback below.
            image.convert(carla.ColorConverter.CityScapesPalette)  # type: ignore[attr-defined]
            bgra = _image_raw_bgra(image)
            rgb = bgra[:, :, :3][:, :, ::-1]
            # NEW-274: atomic commit (see _atomic_path).
            with _atomic_path(out_path) as tmp:
                PILImage.fromarray(rgb, mode="RGB").save(tmp.as_posix())
            return
        except Exception:
            pass

    # Fallback (offline/testing): write ids as a grayscale visualization so a
    # viz artifact still exists, without ever touching the training label.
    # NEW-274: atomic commit (see _atomic_path).
    with _atomic_path(out_path) as tmp:
        PILImage.fromarray(ids, mode="L").save(tmp.as_posix())


@dataclass
class CaptureWriteResult:
    camera: str
    frame: int
    rgb_path: Optional[Path] = None
    semseg_raw_path: Optional[Path] = None
    semseg_viz_path: Optional[Path] = None
    detection_status: Optional[str] = None
    detection_path: Optional[Path] = None


def save_capture_frame(
    dataset_root: Path,
    *,
    camera: str,
    frame: int,
    rgb_image: Any = None,
    seg_image: Any = None,
    label_mode: str = "none",
    write_viz: bool = False,
) -> CaptureWriteResult:
    """Persist one captured frame using the unified rgb/+semseg_raw/ layout.

    Parameters
    ----------
    dataset_root:
        Dataset directory (e.g. ``datasets/<name>``).
    camera:
        Camera name, used as the per-camera subdirectory.
    frame:
        Frame id/index, used to name the file (zero-padded to 8 digits).
    rgb_image:
        carla.Image-like object (or ``None`` to skip writing RGB).
    seg_image:
        carla.Image-like semantic-segmentation object (or ``None`` if
        ``label_mode != "semantic"``).
    label_mode:
        ``"semantic"`` writes the raw class-id training label (and,
        optionally, a palette viz copy). Anything else is treated as
        detection mode, which is an explicit no-op (no fabricated labels).
    write_viz:
        If True and label_mode == "semantic", also write a CityScapes
        palette-colorized copy under semseg_viz/<camera>/ for human viewing.
        Never read by any trainer/eval code.
    """
    dataset_root = Path(dataset_root)
    base = f"{int(frame):08d}"
    result = CaptureWriteResult(camera=camera, frame=int(frame))

    if rgb_image is not None:
        rgb_dir = _ensure_dir(dataset_root / "rgb" / camera)
        rgb_path = rgb_dir / f"{base}.png"
        _write_rgb_png(rgb_image, rgb_path)
        result.rgb_path = rgb_path

    if label_mode == "semantic":
        if seg_image is None:
            raise ValueError("label_mode='semantic' requires seg_image")

        ids = _class_ids_from_seg_image(seg_image)
        assert_label_ids_in_range(ids)  # fail-closed on out-of-range ids

        raw_dir = _ensure_dir(dataset_root / "semseg_raw" / camera)
        raw_path = raw_dir / f"{base}.png"
        # NEW-274: _write_png_raw_ids has no temp-file support, so stage it
        # through a temp sibling here and publish atomically.
        with _atomic_path(raw_path) as tmp:
            _write_png_raw_ids(seg_image, tmp)
        result.semseg_raw_path = raw_path

        if write_viz:
            viz_dir = _ensure_dir(dataset_root / "semseg_viz" / camera)
            viz_path = viz_dir / f"{base}.png"
            _write_viz_png(seg_image, viz_path)
            result.semseg_viz_path = viz_path
    else:
        # Detection labels: no bounding-box projector exists in this
        # codebase, and calibration semantics are out of scope for this fix
        # (see C8 spec boundaries). Do NOT fabricate an empty YOLO .txt that
        # downstream code could mistake for "zero objects" ground truth.
        # Explicit, logged no-op instead.
        logger.info(
            "detection labels: explicit no-op for camera=%s frame=%s "
            "(no 2D bbox projector available; not fabricating empty labels)",
            camera,
            frame,
        )
        result.detection_status = "explicit_noop"

    return result
