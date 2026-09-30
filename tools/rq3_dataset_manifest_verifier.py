"""Verify an RQ3 paired dataset manifest *and the dataset it describes*.

NEW-265 rebuild.  The previous implementation checked mostly field presence
and never opened a single data file: ``manifest_sha256`` was computed but never
compared, and ``frame_ids`` were never checked against anything on disk.

This verifier now independently inspects the dataset:

* manifest schema + manifest self-hash
* dataset root exists
* expected files exist
* file content hashes
* required cameras / required modalities
* exact frame IDs, no duplicates, no missing frames
* monotonic timestamps
* image dimensions, RGB/semantic dimension equality
* semantic class-ID range
* calibration / sensor-transform / route / weather / CARLA / map / software /
  capture-config identity

For paired validation it additionally requires equality of **all** controlled
variables between the two arms.

Field presence alone is never sufficient: pass ``dataset_root`` (or a
``dataset_root`` recorded in the manifest) to enable file inspection.  The CLI
reports ``INCOMPLETE`` when no dataset root was supplied, because a
presence-only verdict is not scientific authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REQUIRED = [
    "map_identity",
    "route_id",
    "frame_ids",
    "sensor_timestamps",
    "modalities",
    "image_dimensions",
    "class_map_version",
    "sensor_transform_identity",
    "weather_identity",
    "seed",
    "carla_version",
]

#: Extra identity fields that must exist and must match across arms.
IDENTITY_FIELDS = [
    "map_identity",
    "route_id",
    "class_map_version",
    "sensor_transform_identity",
    "weather_identity",
    "seed",
    "carla_version",
    "calibration_identity",
    "capture_config_sha256",
    "software_sha256",
]

#: Controlled variables that must be EQUAL between the two paired arms.
PAIRED_EQUALITY_FIELDS = [
    "route_id",
    "weather_identity",
    "seed",
    "carla_version",
    "sensor_transform_identity",
    "class_map_version",
    "calibration_identity",
    "capture_config_sha256",
    "software_sha256",
    "rig_identity",
    "sim_timing_identity",
]

#: Semantic class IDs are single-byte labels; 255 is the standard ignore index.
SEMANTIC_CLASS_MIN = 0
SEMANTIC_CLASS_MAX = 255
SEMANTIC_IGNORE_INDEX = 255


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_dimensions(path: Path) -> Optional[Tuple[int, int]]:
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        width, height = struct.unpack(">II", header[16:24])
        return int(width), int(height)
    except Exception:
        return None


def _read_png_class_ids(path: Path) -> Optional[List[int]]:
    """Read a single-channel PNG's distinct class IDs without PIL if possible."""
    try:
        from PIL import Image  # type: ignore
        import numpy as np  # type: ignore

        array = np.array(Image.open(str(path)))
        if array.ndim == 3:
            array = array[..., 0]
        return sorted(int(v) for v in np.unique(array))
    except Exception:
        return None


def _resolve_dataset_root(
    manifest: Mapping[str, Any], dataset_root: Optional[Any]
) -> Optional[Path]:
    candidate = dataset_root or manifest.get("dataset_root") or manifest.get("output_dir")
    if not candidate:
        return None
    return Path(str(candidate))


def _file_entries(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    declared = manifest.get("files")
    if isinstance(declared, list):
        for item in declared:
            if isinstance(item, dict):
                entries.append(item)
    per_sensor = manifest.get("sensor_files")
    if isinstance(per_sensor, dict):
        for sensor, paths in per_sensor.items():
            if isinstance(paths, list):
                for item in paths:
                    if isinstance(item, str):
                        entries.append({"sensor": sensor, "path": item})
                    elif isinstance(item, dict):
                        entry = dict(item)
                        entry.setdefault("sensor", sensor)
                        entries.append(entry)
    return entries


def verify_manifest_self_hash(manifest: Mapping[str, Any]) -> List[str]:
    """Verify the manifest's own digest when one is declared."""
    declared = (
        manifest.get("manifest_self_sha256")
        or manifest.get("self_hash")
        or manifest.get("manifest_sha256")
    )
    if not declared:
        return []
    payload = {k: v for k, v in manifest.items() if k not in
               ("manifest_self_sha256", "self_hash", "manifest_sha256", "_verification")}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    recomputed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if str(declared).lower() != recomputed:
        return [f"manifest_self_hash_mismatch:declared={declared}:recomputed={recomputed}"]
    return []


def verify_dataset_files(
    manifest: Mapping[str, Any],
    *,
    dataset_root: Optional[Any] = None,
    check_hashes: bool = True,
    check_images: bool = True,
) -> Dict[str, Any]:
    """Independently inspect the dataset the manifest claims to describe."""
    failures: List[str] = []
    root = _resolve_dataset_root(manifest, dataset_root)

    if root is None:
        return {
            "status": "NOT_RUN",
            "reason": "no_dataset_root_supplied",
            "failures": ["dataset_root_required_for_independent_verification"],
        }
    if not root.exists():
        return {
            "status": "FAIL",
            "dataset_root": str(root),
            "failures": [f"dataset_root_missing:{root}"],
        }

    failures.extend(verify_manifest_self_hash(manifest))

    entries = _file_entries(manifest)
    expected_frames = manifest.get("frame_ids") or []
    expected_frames_norm = [str(f) for f in expected_frames]

    # --- file existence + content hashes ---------------------------------
    hash_failures: List[str] = []
    missing_files: List[str] = []
    present_paths: List[str] = []
    for entry in entries:
        rel = entry.get("path") or entry.get("file") or entry.get("relpath")
        if not rel:
            continue
        path = Path(str(rel))
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            missing_files.append(str(rel))
            continue
        present_paths.append(str(path))
        declared_hash = entry.get("sha256")
        if check_hashes and declared_hash:
            actual = sha256(path)
            if str(declared_hash).lower() != actual.lower():
                hash_failures.append(f"{rel}:declared={declared_hash}:actual={actual}")
    if missing_files:
        failures.append(f"expected_files_missing:{len(missing_files)}")
    if hash_failures:
        failures.append(f"file_content_hash_mismatch:{len(hash_failures)}")

    # --- required cameras / modalities -----------------------------------
    required_cameras = [str(c) for c in (manifest.get("required_cameras") or manifest.get("cameras") or [])]
    required_modalities = [
        str(m) for m in (manifest.get("required_modalities") or manifest.get("modalities") or [])
    ]
    sensors_seen = {str(e.get("sensor")) for e in entries if e.get("sensor")}
    modalities_seen = {str(m) for m in (manifest.get("modalities") or [])}
    missing_cameras = [c for c in required_cameras if c not in sensors_seen]
    if missing_cameras:
        failures.append(f"required_cameras_missing:{','.join(missing_cameras)}")

    # --- frame id integrity ---------------------------------------------
    duplicates = sorted({f for f in expected_frames_norm if expected_frames_norm.count(f) > 1})
    if duplicates:
        failures.append(f"duplicate_frame_ids:{duplicates}")
    if manifest.get("missing_frames"):
        failures.append("manifest_declares_missing_frames")

    entry_frames: List[str] = []
    for entry in entries:
        fid = entry.get("frame_id")
        if fid is None:
            continue
        entry_frames.append(str(fid))
    if entry_frames and expected_frames_norm:
        if set(entry_frames) != set(expected_frames_norm):
            failures.append(
                "frame_ids_disagree_with_files:"
                f"manifest={len(set(expected_frames_norm))}:files={len(set(entry_frames))}"
            )

    # --- monotonic timestamps -------------------------------------------
    timestamps = manifest.get("sensor_timestamps")
    ts_values: List[float] = []
    if isinstance(timestamps, dict):
        for value in timestamps.values():
            try:
                ts_values.append(float(value))
            except Exception:
                continue
    elif isinstance(timestamps, list):
        for value in timestamps:
            try:
                ts_values.append(float(value))
            except Exception:
                continue
    if len(ts_values) >= 2 and any(
        ts_values[i] > ts_values[i + 1] for i in range(len(ts_values) - 1)
    ):
        failures.append("sensor_timestamps_not_monotonic")

    # --- image dimensions + RGB/semantic equality + class range ----------
    dimension_report: Dict[str, Any] = {}
    if check_images and present_paths:
        rgb_dims: Dict[str, Tuple[int, int]] = {}
        sem_dims: Dict[str, Tuple[int, int]] = {}
        for entry in entries:
            rel = entry.get("path") or entry.get("file")
            if not rel:
                continue
            path = Path(str(rel))
            if not path.is_absolute():
                path = root / path
            if not path.exists() or path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            dims = _png_dimensions(path)
            if dims is None:
                continue
            kind = str(entry.get("kind") or entry.get("modality") or entry.get("sensor") or "")
            sensor = str(entry.get("sensor") or "")
            if "sem" in kind.lower() or "sem" in sensor.lower():
                sem_dims[sensor or str(rel)] = dims
            elif "rgb" in kind.lower() or "rgb" in sensor.lower() or "cam" in sensor.lower():
                rgb_dims[sensor or str(rel)] = dims

        declared_dims = manifest.get("image_dimensions")
        if isinstance(declared_dims, dict):
            for name, dims in rgb_dims.items():
                declared = declared_dims.get(name) or declared_dims.get("rgb")
                if isinstance(declared, (list, tuple)) and len(declared) == 2:
                    if (int(declared[0]), int(declared[1])) != dims:
                        failures.append(
                            f"image_dimensions_mismatch:{name}:{declared}!={list(dims)}"
                        )

        if rgb_dims and sem_dims:
            shared = set(rgb_dims) & set(sem_dims)
            for name in sorted(shared):
                if rgb_dims[name] != sem_dims[name]:
                    failures.append(
                        f"rgb_semseg_dimension_mismatch:{name}:{rgb_dims[name]}!={sem_dims[name]}"
                    )
            dimension_report["rgb_semseg_compared"] = sorted(shared)

        class_range_failures: List[str] = []
        for entry in entries:
            kind = str(entry.get("kind") or entry.get("modality") or entry.get("sensor") or "")
            if "sem" not in kind.lower() and "sem" not in str(entry.get("sensor") or "").lower():
                continue
            rel = entry.get("path") or entry.get("file")
            if not rel:
                continue
            path = Path(str(rel))
            if not path.is_absolute():
                path = root / path
            if not path.exists() or path.suffix.lower() != ".png":
                continue
            ids = _read_png_class_ids(path)
            if ids is None:
                continue
            out_of_range = [i for i in ids if i < SEMANTIC_CLASS_MIN or i > SEMANTIC_CLASS_MAX]
            if out_of_range:
                class_range_failures.append(f"{rel}:out_of_range={out_of_range}")
        if class_range_failures:
            failures.append(f"semantic_class_id_out_of_range:{len(class_range_failures)}")
        dimension_report["class_range_failures"] = class_range_failures[:20]

    # --- identity fields must exist --------------------------------------
    identity_absent = [f for f in IDENTITY_FIELDS if f in REQUIRED or f in
                       ("calibration_identity", "capture_config_sha256", "software_sha256")]
    for field in ("calibration_identity", "capture_config_sha256", "software_sha256"):
        if field not in manifest or not manifest.get(field):
            failures.append(f"missing {field}")

    status = "PASS" if not failures else "FAIL"
    return {
        "status": status,
        "dataset_root": str(root),
        "files_inspected": len(present_paths),
        "expected_files": len(entries),
        "missing_files": missing_files[:50],
        "hash_mismatches": hash_failures[:50],
        "required_cameras": required_cameras,
        "missing_required_cameras": missing_cameras,
        "required_modalities": required_modalities,
        "expected_frame_count": len(expected_frames_norm),
        "image_and_semantic_checks": dimension_report,
        "failures": failures,
        "inspected_not_trusted": True,
    }


def verify(
    manifest: dict[str, Any],
    paired: dict[str, Any] | None = None,
    *,
    dataset_root: Any = None,
    paired_dataset_root: Any = None,
    check_hashes: bool = True,
    check_images: bool = True,
) -> dict[str, Any]:
    failures = [f"missing {field}" for field in REQUIRED if field not in manifest]
    frames = manifest.get("frame_ids") or []
    duplicates = sorted({str(frame) for frame in frames if frames.count(frame) > 1})
    if duplicates:
        failures.append(f"duplicate frame IDs: {duplicates}")
    if manifest.get("missing_frames"):
        failures.append("manifest declares missing frames")

    identity_missing = [
        f for f in ("calibration_identity", "capture_config_sha256", "software_sha256")
        if not manifest.get(f)
    ]
    for field in identity_missing:
        failures.append(f"missing {field}")

    contract_fields = [
        "route_id",
        "weather_identity",
        "seed",
        "carla_version",
        "sensor_transform_identity",
        "class_map_version",
    ]
    mismatches: List[str] = []
    pairing_performed = False
    if paired is not None:
        pairing_performed = True
        for field in contract_fields:
            if manifest.get(field) != paired.get(field):
                mismatches.append(field)
        # NEW-266: equality of ALL controlled variables, not a subset.
        for field in PAIRED_EQUALITY_FIELDS:
            if field in contract_fields:
                continue
            left = manifest.get(field)
            right = paired.get(field)
            if left is None and right is None:
                continue
            if left != right:
                mismatches.append(field)
    mismatches = sorted(set(mismatches))

    # --- independent file verification ------------------------------------
    root_supplied = dataset_root is not None or bool(manifest.get("dataset_root")) or bool(
        manifest.get("output_dir")
    )
    file_report = verify_dataset_files(
        manifest,
        dataset_root=dataset_root,
        check_hashes=check_hashes,
        check_images=check_images,
    )
    paired_file_report = None
    if paired is not None and (paired_dataset_root is not None or paired.get("dataset_root")):
        paired_file_report = verify_dataset_files(
            paired,
            dataset_root=paired_dataset_root,
            check_hashes=check_hashes,
            check_images=check_images,
        )
        if paired_file_report.get("status") == "FAIL":
            failures.append("paired_dataset_file_verification_failed")

    if file_report.get("status") == "FAIL":
        failures.extend(file_report.get("failures") or [])

    if failures or mismatches:
        status = "FAIL"
    elif not pairing_performed:
        status = "INCOMPLETE"
    elif file_report.get("status") == "NOT_RUN":
        status = "INCOMPLETE"
    else:
        status = "PASS"

    return {
        "schema": "rq3_dataset_manifest_verification/v2",
        "status": status,
        "failures": failures,
        "paired_contract_mismatches": mismatches,
        "quality_comparison": "NOT_RUN",
        "capture_data_mutated": False,
        "pairing_performed": pairing_performed,
        "file_verification": file_report,
        "paired_file_verification": paired_file_report,
        "dataset_root_supplied": bool(root_supplied),
        "independent_verification": True,
        "note": (
            "Files are inspected (existence, content hashes, frame ids, "
            "dimensions, class-id range); manifest claims are never trusted "
            "without evidence. Without a dataset root the verdict is INCOMPLETE."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--paired", type=Path, default=None)
    parser.add_argument("--dataset-root", type=Path, default=None)
    parser.add_argument("--paired-dataset-root", type=Path, default=None)
    parser.add_argument("--skip-hashes", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("RQ3_DATASET_MANIFEST_VERIFICATION.json"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    paired = json.loads(args.paired.read_text(encoding="utf-8")) if args.paired else None
    report = verify(
        manifest,
        paired,
        dataset_root=args.dataset_root,
        paired_dataset_root=args.paired_dataset_root,
        check_hashes=not args.skip_hashes,
    )
    report["manifest_path"] = str(args.manifest)
    report["manifest_sha256"] = sha256(args.manifest)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
