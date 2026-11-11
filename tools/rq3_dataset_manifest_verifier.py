"""Verify an RQ3 paired dataset manifest without comparing perception quality."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED = ["map_identity", "route_id", "frame_ids", "sensor_timestamps", "modalities", "image_dimensions", "class_map_version", "sensor_transform_identity", "weather_identity", "seed", "carla_version"]

CONTRACT_FIELDS = ["route_id", "weather_identity", "seed", "carla_version", "sensor_transform_identity", "class_map_version"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _check_frame_ids(manifest: dict[str, Any]) -> list[str]:
    failures = []
    frames = manifest.get("frame_ids")
    if isinstance(frames, list):
        if not frames:
            failures.append("empty frame_ids")
        else:
            duplicates = sorted({str(frame) for frame in frames if frames.count(frame) > 1})
            if duplicates:
                failures.append(f"duplicate frame IDs: {duplicates}")
    return failures


def _check_timestamps(manifest: dict[str, Any]) -> list[str]:
    failures = []
    timestamps = manifest.get("sensor_timestamps")
    frames = manifest.get("frame_ids")
    if isinstance(timestamps, list) and isinstance(frames, list):
        if not timestamps:
            failures.append("empty sensor_timestamps")
        elif len(timestamps) != len(frames):
            failures.append(
                f"frame/timestamp length mismatch: {len(frames)} frames vs {len(timestamps)} timestamps"
            )
    return failures


def _check_dimensions(manifest: dict[str, Any]) -> list[str]:
    failures = []
    dims = manifest.get("image_dimensions")
    if isinstance(dims, list) and dims:
        for entry in dims:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                failures.append(f"invalid image_dimensions entry: {entry}")
                continue
            w, h = entry
            if not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
                failures.append(f"invalid image_dimensions values: {entry}")
    return failures


def _check_modalities(manifest: dict[str, Any]) -> list[str]:
    failures = []
    modalities = manifest.get("modalities")
    if isinstance(modalities, list) and modalities:
        valid = {"rgb", "depth", "semantic_segmentation", "instance_segmentation", "lidar", "gnss", "imu"}
        for mod in modalities:
            if mod not in valid:
                failures.append(f"unknown modality: {mod}")
    return failures


def _check_capture_files(manifest: dict[str, Any]) -> list[str]:
    failures = []
    capture_files = manifest.get("capture_files")
    if isinstance(capture_files, list) and capture_files:
        missing = []
        for entry in capture_files:
            path = entry if isinstance(entry, str) else entry.get("path", "")
            if not path:
                missing.append("<missing path>")
        if missing:
            failures.append(f"missing capture file paths: {missing[:5]}")
    return failures


def _check_missing_frames(manifest: dict[str, Any]) -> list[str]:
    failures = []
    missing_frames = manifest.get("missing_frames")
    if missing_frames:
        failures.append("manifest declares missing frames")
    return failures


def _check_map_identity(manifest: dict[str, Any], paired: dict[str, Any] | None) -> list[str]:
    failures = []
    if paired is not None:
        if manifest.get("map_identity") != paired.get("map_identity"):
            failures.append("map_identity mismatch between paired manifests")
        if manifest.get("map_identity") == paired.get("map_identity") and paired.get("distinct_arms_required"):
            if manifest.get("arm_id") == paired.get("arm_id"):
                failures.append("same map arm used where distinct arms are required")
    return failures


def _check_sensor_transform(manifest: dict[str, Any], paired: dict[str, Any] | None) -> list[str]:
    failures = []
    if paired is not None:
        if manifest.get("sensor_transform_identity") != paired.get("sensor_transform_identity"):
            failures.append("sensor_transform_identity mismatch between paired manifests")
    return failures


def _check_class_map(manifest: dict[str, Any], paired: dict[str, Any] | None) -> list[str]:
    failures = []
    if paired is not None:
        if manifest.get("class_map_version") != paired.get("class_map_version"):
            failures.append("class_map_version mismatch between paired manifests")
    return failures


def _check_route(manifest: dict[str, Any], paired: dict[str, Any] | None) -> list[str]:
    failures = []
    if paired is not None:
        if manifest.get("route_id") != paired.get("route_id"):
            failures.append("route_id mismatch between paired manifests")
    return failures


def _check_quality_evaluated(manifest: dict[str, Any]) -> list[str]:
    failures = []
    quality = manifest.get("quality_evaluation")
    if isinstance(quality, dict) and not quality.get("performed", False):
        failures.append("quality_evaluation not performed")
    return failures


def verify(manifest: dict[str, Any], paired: dict[str, Any] | None = None) -> dict[str, Any]:
    failures = [f"missing {field}" for field in REQUIRED if field not in manifest]
    failures.extend(_check_frame_ids(manifest))
    failures.extend(_check_timestamps(manifest))
    failures.extend(_check_dimensions(manifest))
    failures.extend(_check_modalities(manifest))
    failures.extend(_check_capture_files(manifest))
    failures.extend(_check_missing_frames(manifest))
    failures.extend(_check_map_identity(manifest, paired))
    failures.extend(_check_sensor_transform(manifest, paired))
    failures.extend(_check_class_map(manifest, paired))
    failures.extend(_check_route(manifest, paired))
    failures.extend(_check_quality_evaluated(manifest))

    mismatches = []
    pairing_performed = False
    if paired is not None:
        pairing_performed = True
        for field in CONTRACT_FIELDS:
            if manifest.get(field) != paired.get(field):
                mismatches.append(field)

    if not failures and not mismatches:
        if pairing_performed:
            status = "PASS"
        else:
            status = "INCOMPLETE"
    else:
        status = "FAIL"

    return {
        "schema": "rq3_dataset_manifest_verification/v1",
        "status": status,
        "failures": failures,
        "paired_contract_mismatches": mismatches,
        "quality_comparison": "NOT_RUN",
        "capture_data_mutated": False,
        "pairing_performed": pairing_performed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--paired", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("RQ3_DATASET_MANIFEST_VERIFICATION.json"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    paired = json.loads(args.paired.read_text(encoding="utf-8")) if args.paired else None
    report = verify(manifest, paired)
    report["manifest_path"] = str(args.manifest)
    report["manifest_sha256"] = sha256(args.manifest)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())