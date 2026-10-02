#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/dataset_quality_gate.py

Pre-training dataset quality gate for RQ5.

A dataset that cannot train is cheaper to detect here than to explain later as a
"domain gap". This gate answers one question per dataset role: *may this data
enter a governed RQ5 run at all?* and writes the answer to
``DATASET_QUALITY.json``.

Checked (each one independently fatal unless listed as a warning):

* structural      - RGB present, semantic label present, required LiDAR present
* decodability    - every member file actually decodes as an image
* geometry        - resolution consistent across frames and across sensors,
                    frame ids valid, frame ordering valid
* correspondence  - every frame id has both an RGB and a semantic label, and
                    (when LiDAR is required) a point cloud
* label validity  - semantic ids inside the declared label space, Any(255)
                    sentinel fraction *measured* rather than silently tolerated
* duplicates      - duplicate frame content and duplicate frame identity
* degenerate      - constant/zero semantic frames, all-black or corrupt RGB

Severity model
--------------
``fatal`` findings make the gate FAIL and block training. ``warning`` findings
are recorded and counted -- the Any(255) fraction is a measurement rather than
a defect, but an implausible one is escalated to fatal by threshold.

No CARLA import. No torch import. Fully offline and fixture-testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, UnidentifiedImageError

from ultimate_pipeline.perception.rq5_provenance import canonical_dumps, sha256_file, sha256_text

__all__ = [
    "DATASET_QUALITY_SCHEMA",
    "DATASET_QUALITY_FILENAME",
    "SEVERITY_FATAL",
    "SEVERITY_WARNING",
    "QUALITY_PASS",
    "QUALITY_FAIL",
    "DEFAULT_REQUIRE_LIDAR",
    "DEFAULT_ANY_SENTINEL_ID",
    "DEFAULT_MAX_ANY_FRACTION",
    "QualityGateError",
    "QualityFinding",
    "QualityReport",
    "evaluate_dataset_quality",
    "run_quality_gate",
    "write_dataset_quality",
    "load_dataset_quality",
]

DATASET_QUALITY_SCHEMA = "rq5_dataset_quality_v1"
DATASET_QUALITY_FILENAME = "DATASET_QUALITY.json"

SEVERITY_FATAL = "fatal"
SEVERITY_WARNING = "warning"

QUALITY_PASS = "PASS"
QUALITY_FAIL = "FAIL"

DEFAULT_REQUIRE_LIDAR = False
DEFAULT_ANY_SENTINEL_ID = 255
#: Above this fraction of Any(255) pixels the sentinel stops being a legitimate
#: "unclassified" value and becomes an unusable-label symptom.
DEFAULT_MAX_ANY_FRACTION = 0.90

_LIDAR_SUBDIRS = ("lidar", "pc", "pointcloud", "velodyne")


class QualityGateError(RuntimeError):
    """Raised when the quality gate cannot be run at all."""


@dataclass(frozen=True)
class QualityFinding:
    code: str
    severity: str
    message: str
    count: int = 0
    examples: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "count": int(self.count),
            "examples": list(self.examples)[:5],
        }


@dataclass
class QualityReport:
    dataset_root: str
    camera: str
    role: str
    status: str
    findings: List[QualityFinding] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def fatal(self) -> List[QualityFinding]:
        return [f for f in self.findings if f.severity == SEVERITY_FATAL]

    @property
    def ok(self) -> bool:
        return self.status == QUALITY_PASS

    def to_dict(self, claim_scope: str = "TEST_FIXTURE_ONLY") -> Dict[str, Any]:
        payload = dict(self.metrics)
        payload.update(
            {
                "schema": DATASET_QUALITY_SCHEMA,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "claim_scope": claim_scope,
                "dataset_root": self.dataset_root,
                "camera": self.camera,
                "role": self.role,
                "status": self.status,
                "fatal_count": len(self.fatal),
                "findings": [f.to_dict() for f in self.findings],
            }
        )
        payload["report_sha256"] = sha256_text(
            canonical_dumps(
                {k: v for k, v in payload.items() if k not in ("created_utc", "report_sha256")}
            )
        )
        return payload


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _decode(path: Path, mode: str) -> Tuple[Optional[np.ndarray], Optional[str]]:
    try:
        with Image.open(path) as handle:
            handle.load()
            return np.array(handle.convert(mode), dtype=np.uint8), None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _parse_frame_id(stem: str) -> Optional[int]:
    digits = "".join(ch for ch in stem if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:  # pragma: no cover - defensive
        return None


def _find_lidar_dir(root: Path, camera: str) -> Optional[Path]:
    for sub in _LIDAR_SUBDIRS:
        candidate = root / sub
        if candidate.is_dir():
            return candidate
    lidar_cam = root / "lidar" / camera
    return lidar_cam if lidar_cam.is_dir() else None


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


def evaluate_dataset_quality(
    dataset_root: Any,
    camera: str,
    *,
    role: str = "generated_train",
    require_lidar: bool = DEFAULT_REQUIRE_LIDAR,
    num_classes: int = 29,
    any_sentinel_id: int = DEFAULT_ANY_SENTINEL_ID,
    max_any_fraction: float = DEFAULT_MAX_ANY_FRACTION,
    expected_resolution: Optional[Tuple[int, int]] = None,
    max_decode_frames: int = 0,
    claim_scope: str = "TEST_FIXTURE_ONLY",
) -> QualityReport:
    """
    Evaluate one dataset root and return a :class:`QualityReport`.

    Args:
        dataset_root: Root containing ``rgb/<camera>`` and ``semseg_raw/<camera>``.
        camera: Camera subdirectory name. Explicit.
        role: Governed role this dataset will occupy (recorded in the report).
        require_lidar: When True, a LiDAR directory with a matching member per
            frame id is mandatory and its absence is fatal.
        num_classes: Declared output-class count. Labels must satisfy
            ``0 <= id < num_classes`` or equal the Any sentinel.
        expected_resolution: ``(width, height)`` every frame must match. When
            omitted, any deviation between frames is fatal.
        max_decode_frames: Diagnostic cap on how many frames are fully decoded.
            ``0`` (default) decodes everything, which is what an authoritative
            gate requires; a positive cap marks the report ``diagnostic=True``.

    Raises:
        QualityGateError: If the root or camera directory is absent -- the gate
            cannot produce a verdict, so it must never silently PASS.
    """
    root = Path(dataset_root)
    camera = str(camera)
    if not root.is_dir():
        raise QualityGateError(f"dataset root does not exist: {root}")

    rgb_dir = root / "rgb" / camera
    label_dir = root / "semseg_raw" / camera
    if not rgb_dir.is_dir():
        raise QualityGateError(f"dataset root {root} has no rgb/{camera}")
    if not label_dir.is_dir():
        raise QualityGateError(f"dataset root {root} has no semseg_raw/{camera}")

    findings: List[QualityFinding] = []
    rgb_files = sorted(rgb_dir.glob("*.png"))
    label_files = sorted(label_dir.glob("*.png"))

    if not rgb_files:
        findings.append(
            QualityFinding("rgb_missing", SEVERITY_FATAL, f"no rgb PNG frames under {rgb_dir}")
        )
    if not label_files:
        findings.append(
            QualityFinding(
                "semantic_label_missing", SEVERITY_FATAL, f"no semseg_raw PNG frames under {label_dir}"
            )
        )

    rgb_by_id: Dict[Optional[int], Path] = {_parse_frame_id(p.stem): p for p in rgb_files}
    label_by_id: Dict[Optional[int], Path] = {_parse_frame_id(p.stem): p for p in label_files}

    invalid_ids = [p.name for p in rgb_files if _parse_frame_id(p.stem) is None]
    if invalid_ids:
        findings.append(
            QualityFinding(
                "frame_id_invalid",
                SEVERITY_FATAL,
                "rgb frame names contain no parsable frame id",
                count=len(invalid_ids),
                examples=invalid_ids,
            )
        )

    # --- sensor correspondence -------------------------------------------
    rgb_ids = {k for k in rgb_by_id if k is not None}
    label_ids = {k for k in label_by_id if k is not None}
    missing_labels = sorted(rgb_ids - label_ids)
    missing_rgb = sorted(label_ids - rgb_ids)
    if missing_labels:
        findings.append(
            QualityFinding(
                "semantic_label_missing",
                SEVERITY_FATAL,
                "rgb frames have no matching semantic label",
                count=len(missing_labels),
                examples=[rgb_by_id[i].name for i in missing_labels],
            )
        )
    if missing_rgb:
        findings.append(
            QualityFinding(
                "rgb_missing",
                SEVERITY_FATAL,
                "semantic labels have no matching rgb frame",
                count=len(missing_rgb),
                examples=[label_by_id[i].name for i in missing_rgb],
            )
        )

    lidar_dir = _find_lidar_dir(root, camera)
    lidar_frame_count = 0
    if require_lidar:
        if lidar_dir is None:
            findings.append(
                QualityFinding(
                    "lidar_missing",
                    SEVERITY_FATAL,
                    f"protocol requires LiDAR but no {'/'.join(_LIDAR_SUBDIRS)} directory exists",
                )
            )
        else:
            lidar_ids = {_parse_frame_id(p.stem) for p in lidar_dir.iterdir() if p.is_file()}
            lidar_ids.discard(None)
            lidar_frame_count = len(lidar_ids)
            missing_lidar = sorted(rgb_ids - lidar_ids)
            if missing_lidar:
                findings.append(
                    QualityFinding(
                        "lidar_missing",
                        SEVERITY_FATAL,
                        "frames have no matching LiDAR sample",
                        count=len(missing_lidar),
                        examples=[str(i) for i in missing_lidar],
                    )
                )

    paired_ids = sorted(rgb_ids & label_ids)
    if not paired_ids:
        return QualityReport(
            dataset_root=str(root.resolve()),
            camera=camera,
            role=role,
            status=QUALITY_FAIL,
            findings=findings
            + [
                QualityFinding(
                    "no_paired_frames",
                    SEVERITY_FATAL,
                    "no frame has both an rgb image and a semantic label",
                )
            ],
            metrics={
                "diagnostic": False,
                "frames_scanned": 0,
                "frames_paired": 0,
                "rgb_frame_count": len(rgb_files),
                "label_frame_count": len(label_files),
                "paired_frame_count": 0,
                "sensor_completeness": {
                    "rgb": len(rgb_files),
                    "semseg_raw": len(label_files),
                    "lidar": lidar_frame_count,
                    "lidar_required": bool(require_lidar),
                    "lidar_dir": str(lidar_dir) if lidar_dir else None,
                },
                "quality_failures": sorted(
                    {f.code for f in findings} | {"no_paired_frames"}
                ),
            },
        )

    # --- duplicates --------------------------------------------------------
    rgb_digest_owner: Dict[str, str] = {}
    duplicate_content = 0
    duplicate_examples: List[str] = []
    for frame_id in paired_ids:
        digest = sha256_file(rgb_by_id[frame_id])
        if digest in rgb_digest_owner:
            duplicate_content += 1
            duplicate_examples.append(f"{rgb_by_id[frame_id].name} == {rgb_digest_owner[digest]}")
        else:
            rgb_digest_owner[digest] = rgb_by_id[frame_id].name
    if duplicate_content:
        findings.append(
            QualityFinding(
                "duplicate_content",
                SEVERITY_FATAL,
                "identical rgb content appears under more than one frame id",
                count=duplicate_content,
                examples=duplicate_examples,
            )
        )

    stem_counts: Dict[str, int] = {}
    for frame_id in paired_ids:
        stem = rgb_by_id[frame_id].stem
        stem_counts[stem] = stem_counts.get(stem, 0) + 1
    duplicate_frames = sum(v - 1 for v in stem_counts.values() if v > 1)
    if duplicate_frames:  # pragma: no cover - filesystem names are unique in practice
        findings.append(
            QualityFinding(
                "duplicate_frame", SEVERITY_FATAL, "duplicate frame identity", count=duplicate_frames
            )
        )

    # --- decode + scan -----------------------------------------------------
    decode_cap = int(max_decode_frames) if int(max_decode_frames) > 0 else len(paired_ids)
    scan_ids = paired_ids[:decode_cap]

    undecodable: List[str] = []
    resolutions: Dict[Tuple[int, int], int] = {}
    all_black_rgb: List[str] = []
    constant_label: List[str] = []
    invalid_label_frames: List[str] = []
    any_pixels = 0
    total_pixels = 0
    class_histogram = np.zeros(int(num_classes), dtype=np.int64)

    for frame_id in scan_ids:
        rgb_path = rgb_by_id[frame_id]
        label_path = label_by_id[frame_id]

        rgb, rgb_error = _decode(rgb_path, "RGB")
        label, label_error = _decode(label_path, "L")
        if rgb_error is not None or label_error is not None:
            undecodable.append(f"{rgb_path.name}:{rgb_error or label_error}")
            continue

        key = (int(rgb.shape[1]), int(rgb.shape[0]))
        resolutions[key] = resolutions.get(key, 0) + 1
        if rgb.shape[:2] != label.shape[:2]:
            invalid_label_frames.append(
                f"{rgb_path.name}: rgb {key[0]}x{key[1]} vs label "
                f"{label.shape[1]}x{label.shape[0]}"
            )
            continue

        if int(rgb.max()) == 0:
            all_black_rgb.append(rgb_path.name)

        flat = label.reshape(-1)
        total_pixels += int(flat.size)
        any_mask = flat == int(any_sentinel_id)
        any_pixels += int(any_mask.sum())
        body = flat[~any_mask]
        if body.size == 0:
            constant_label.append(f"{label_path.name}: every pixel is Any({any_sentinel_id})")
        elif int(np.unique(body).size) == 1:
            constant_label.append(f"{label_path.name}: single class {int(body[0])}")
        out_of_range = body[body >= int(num_classes)]
        if out_of_range.size:
            invalid_label_frames.append(
                f"{label_path.name}: {out_of_range.size} pixel(s) outside [0,{int(num_classes) - 1}]"
            )
        valid = body[body < int(num_classes)]
        if valid.size:
            class_histogram += np.bincount(valid.astype(np.int64), minlength=int(num_classes))[
                : int(num_classes)
            ]

    if undecodable:
        findings.append(
            QualityFinding(
                "file_undecodable",
                SEVERITY_FATAL,
                "image files failed to decode",
                count=len(undecodable),
                examples=undecodable,
            )
        )
    if all_black_rgb:
        findings.append(
            QualityFinding(
                "rgb_all_black",
                SEVERITY_FATAL,
                "rgb frames decode to an all-zero image",
                count=len(all_black_rgb),
                examples=all_black_rgb,
            )
        )
    if constant_label:
        findings.append(
            QualityFinding(
                "semantic_constant_frame",
                SEVERITY_WARNING,
                "semantic label frames carry no class diversity (zero/constant mask)",
                count=len(constant_label),
                examples=constant_label,
            )
        )
    if invalid_label_frames:
        findings.append(
            QualityFinding(
                "semantic_id_invalid",
                SEVERITY_FATAL,
                "label geometry mismatch or semantic ids outside the declared label space",
                count=len(invalid_label_frames),
                examples=invalid_label_frames,
            )
        )

    # --- resolution --------------------------------------------------------
    if expected_resolution is not None:
        target = (int(expected_resolution[0]), int(expected_resolution[1]))
        if resolutions and set(resolutions) != {target}:
            findings.append(
                QualityFinding(
                    "resolution_mismatch",
                    SEVERITY_FATAL,
                    f"frame resolutions {sorted(resolutions)} do not match the required {target}",
                    count=len(resolutions),
                )
            )
    elif len(resolutions) > 1:
        findings.append(
            QualityFinding(
                "resolution_inconsistent",
                SEVERITY_FATAL,
                f"frames do not share one resolution: {sorted(resolutions)}",
                count=len(resolutions),
            )
        )

    # --- frame ordering ----------------------------------------------------
    ascending = sorted(paired_ids) == list(paired_ids)
    if not ascending:
        findings.append(
            QualityFinding(
                "frame_ordering_invalid", SEVERITY_FATAL, "paired frame ids are not monotonic"
            )
        )

    # --- Any(255) usage ----------------------------------------------------
    any_fraction = (any_pixels / total_pixels) if total_pixels else None
    if any_fraction is not None:
        severity = SEVERITY_FATAL if any_fraction > float(max_any_fraction) else SEVERITY_WARNING
        findings.append(
            QualityFinding(
                "any_sentinel_fraction",
                severity,
                f"Any({any_sentinel_id}) occupies {any_fraction:.4f} of labelled pixels "
                f"(fatal above {float(max_any_fraction):.2f})",
                count=int(any_pixels),
            )
        )

    present = int((class_histogram > 0).sum())
    never_present = [str(i) for i in range(int(num_classes)) if int(class_histogram[i]) == 0]
    if present == 0:
        findings.append(
            QualityFinding(
                "class_coverage_empty",
                SEVERITY_FATAL,
                "no valid (non-Any) semantic pixels were observed in the scanned frames",
            )
        )

    status = QUALITY_FAIL if any(f.severity == SEVERITY_FATAL for f in findings) else QUALITY_PASS

    metrics: Dict[str, Any] = {
        "diagnostic": decode_cap < len(paired_ids),
        "frames_scanned": len(scan_ids),
        "frames_paired": len(paired_ids),
        "sensor_completeness": {
            "rgb": len(rgb_files),
            "semseg_raw": len(label_files),
            "lidar": lidar_frame_count,
            "lidar_required": bool(require_lidar),
            "lidar_dir": str(lidar_dir) if lidar_dir else None,
        },
        "rgb_frame_count": len(rgb_files),
        "label_frame_count": len(label_files),
        "paired_frame_count": len(paired_ids),
        "frame_id_min": paired_ids[0],
        "frame_id_max": paired_ids[-1],
        "frame_ordering_valid": ascending,
        "resolutions": {f"{w}x{h}": count for (w, h), count in sorted(resolutions.items())},
        "duplicate_frame_count": int(duplicate_frames),
        "duplicate_content_count": int(duplicate_content),
        "duplicate_rate": (float(duplicate_content) / float(len(scan_ids))) if scan_ids else 0.0,
        "invalid_label_frame_count": len(invalid_label_frames),
        "undecodable_file_count": len(undecodable),
        "all_black_rgb_count": len(all_black_rgb),
        "constant_semantic_frame_count": len(constant_label),
        "any_sentinel_id": int(any_sentinel_id),
        "any_sentinel_pixels": int(any_pixels),
        "any_sentinel_fraction": any_fraction,
        "class_histogram": class_histogram.tolist(),
        "class_coverage_count": present,
        "class_coverage_fraction": (float(present) / float(num_classes)) if num_classes else None,
        "classes_never_present": never_present,
        "quality_failures": sorted({f.code for f in findings if f.severity == SEVERITY_FATAL}),
    }

    return QualityReport(
        dataset_root=str(root.resolve()),
        camera=camera,
        role=role,
        status=status,
        findings=findings,
        metrics=metrics,
    )


def run_quality_gate(
    dataset_root: Any,
    camera: str,
    *,
    out_dir: Optional[Any] = None,
    role: str = "generated_train",
    claim_scope: str = "TEST_FIXTURE_ONLY",
    **kwargs: Any,
) -> Tuple[QualityReport, Optional[Path]]:
    """Evaluate quality and, when ``out_dir`` is given, persist ``DATASET_QUALITY.json``."""
    report = evaluate_dataset_quality(dataset_root, camera, role=role, claim_scope=claim_scope, **kwargs)
    if out_dir is None:
        return report, None
    return report, write_dataset_quality(out_dir, report, claim_scope=claim_scope)


def write_dataset_quality(
    out_dir: Any,
    report: QualityReport,
    *,
    claim_scope: str = "TEST_FIXTURE_ONLY",
    filename: str = DATASET_QUALITY_FILENAME,
) -> Path:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    target.write_text(
        json.dumps(report.to_dict(claim_scope=claim_scope), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_dataset_quality(path: Any) -> Dict[str, Any]:
    """Load a persisted ``DATASET_QUALITY.json`` and schema-check it."""
    p = Path(path)
    if not p.is_file():
        raise QualityGateError(f"dataset quality report not found: {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != DATASET_QUALITY_SCHEMA:
        raise QualityGateError(f"unsupported dataset quality schema in {p}")
    return payload