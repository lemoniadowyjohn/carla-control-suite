"""Verify an RQ3 paired dataset manifest without comparing perception quality."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED = ["map_identity", "route_id", "frame_ids", "sensor_timestamps", "modalities", "image_dimensions", "class_map_version", "sensor_transform_identity", "weather_identity", "seed", "carla_version"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify(manifest: dict[str, Any], paired: dict[str, Any] | None = None) -> dict[str, Any]:
    failures = [f"missing {field}" for field in REQUIRED if field not in manifest]
    frames = manifest.get("frame_ids") or []
    duplicates = sorted({str(frame) for frame in frames if frames.count(frame) > 1})
    if duplicates:
        failures.append(f"duplicate frame IDs: {duplicates}")
    if manifest.get("missing_frames"):
        failures.append("manifest declares missing frames")
    contract_fields = ["route_id", "weather_identity", "seed", "carla_version", "sensor_transform_identity", "class_map_version"]
    mismatches = []
    if paired is not None:
        for field in contract_fields:
            if manifest.get(field) != paired.get(field):
                mismatches.append(field)
    return {"schema": "rq3_dataset_manifest_verification/v1", "status": "PASS" if not failures and not mismatches else "FAIL", "failures": failures, "paired_contract_mismatches": mismatches, "quality_comparison": "NOT_RUN", "capture_data_mutated": False}


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
