"""Build a CARLA import manifest from RoadRunner export inventory.

Scans an export directory, validates the inventory against expected
files and hashes, and produces a CARLA-ready import manifest JSON
without claiming FBX existence proves CARLA readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from ultimate_pipeline.roadrunner.export_inventory import (
    ExportInventory,
    FileRecord,
    validate_export_inventory,
)


def _scan_export_directory(export_dir: Path) -> list[FileRecord]:
    """Recursively scan an export directory and compute SHA-256 for each file."""
    records: list[FileRecord] = []
    for path in sorted(export_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(export_dir).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(
            FileRecord(
                rel_path=rel,
                sha256=digest,
                size_bytes=path.stat().st_size,
            )
        )
    return records


def _extract_base_name(export_dir: Path) -> str:
    """Infer base name from the export directory name."""
    name = export_dir.name
    for suffix in ("_fbx", "_datasmith", "_tiled", "_mesh", "_export"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def build_carla_import_manifest(
    export_dir: Path,
    source_xodr_sha256: str,
    export_id: str | None = None,
) -> dict[str, Any]:
    """Build a CARLA import manifest from an export directory.

    Validates the inventory and returns a JSON-serialisable dict.
    Does NOT claim FBX existence equals CARLA readiness.
    """
    if not export_dir.is_dir():
        raise FileNotFoundError(f"export directory not found: {export_dir}")

    records = _scan_export_directory(export_dir)
    base_name = _extract_base_name(export_dir)

    if export_id is None:
        export_id = f"carla-import-{base_name}"

    inventory = ExportInventory(
        export_id=export_id,
        source_xodr_sha256=source_xodr_sha256,
        expected_files=tuple(records),
        base_name=base_name,
    )

    validation = validate_export_inventory(inventory, export_dir=export_dir)

    manifest: dict[str, Any] = {
        "manifest_id": export_id,
        "source_xodr_sha256": source_xodr_sha256,
        "export_dir": export_dir.as_posix(),
        "base_name": base_name,
        "file_count": len(records),
        "total_size_bytes": sum(r.size_bytes for r in records),
        "validation": {
            "valid": validation.valid,
            "error_count": len(validation.errors),
            "errors": list(validation.errors),
        },
        "files": [
            {
                "rel_path": r.rel_path,
                "sha256": r.sha256,
                "size_bytes": r.size_bytes,
            }
            for r in records
        ],
        "carla_readiness_note": (
            "FBX presence alone does not prove CARLA readiness. "
            "XODR authority and proper material/semantic mapping are required."
        ),
    }

    fbx_files = [r for r in records if r.rel_path.lower().endswith(".fbx")]
    xodr_files = [r for r in records if r.rel_path.lower().endswith(".xodr")]

    manifest["has_fbx"] = len(fbx_files) > 0
    manifest["has_xodr"] = len(xodr_files) > 0
    manifest["carla_ready"] = validation.valid and len(xodr_files) > 0

    return manifest


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for building CARLA import manifests."""
    parser = argparse.ArgumentParser(
        description="Build a CARLA import manifest from a RoadRunner export directory.",
    )
    parser.add_argument("export_dir", type=Path, help="Path to the export directory.")
    parser.add_argument(
        "--source-xodr-sha256",
        required=True,
        help="SHA-256 of the source XODR file.",
    )
    parser.add_argument(
        "--export-id",
        default=None,
        help="Override export identifier.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON file path. Defaults to stdout.",
    )
    args = parser.parse_args(argv)

    try:
        manifest = build_carla_import_manifest(
            export_dir=args.export_dir,
            source_xodr_sha256=args.source_xodr_sha256,
            export_id=args.export_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output = json.dumps(manifest, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Manifest written to {args.output}", file=sys.stderr)
    else:
        print(output)

    if not manifest.get("carla_ready", False):
        print(
            "WARNING: Export is not CARLA-ready. "
            "Check validation errors and ensure XODR authority is present.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
