"""CLI tool for exporting and validating RoadRunner export inventories.

Scans an export directory, builds an ExportInventory, validates it
against all functional requirements, and writes a JSON report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from ultimate_pipeline.roadrunner.export_inventory import (
    BoundingBox,
    ExportInventory,
    FileRecord,
    LodEntry,
    MaterialRecord,
    MeshStats,
    SemanticGroupRecord,
    TileRecord,
    validate_export_inventory,
)


def _scan_directory(export_dir: Path) -> list[FileRecord]:
    """Scan directory and compute SHA-256 for each file."""
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


def _detect_export_type(export_dir: Path) -> str:
    """Detect export type from directory contents."""
    extensions: set[str] = set()
    for path in export_dir.rglob("*"):
        if path.is_file():
            extensions.add(path.suffix.lower())
    if ".fbx" in extensions:
        return "fbx"
    if ".udatasmith" in extensions:
        return "datasmith"
    if any(p.name.endswith(".xodr") for p in export_dir.rglob("*.xodr")):
        return "tiled_xodr"
    return "unknown"


def _detect_base_name(export_dir: Path) -> str:
    """Infer base name from directory name or file contents."""
    name = export_dir.name
    for suffix in ("_fbx", "_datasmith", "_tiled", "_mesh", "_export", "_rrscene"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def export_inventory(
    export_dir: Path,
    source_xodr_sha256: str,
    export_id: str | None = None,
) -> dict[str, Any]:
    """Build and validate an export inventory from a directory.

    Returns a JSON-serialisable dict with inventory metadata and
    validation results.
    """
    if not export_dir.is_dir():
        raise FileNotFoundError(f"export directory not found: {export_dir}")

    records = _scan_directory(export_dir)
    base_name = _detect_base_name(export_dir)
    export_type = _detect_export_type(export_dir)

    if export_id is None:
        export_id = f"export-{base_name}-{export_type}"

    inventory = ExportInventory(
        export_id=export_id,
        source_xodr_sha256=source_xodr_sha256,
        expected_files=tuple(records),
        base_name=base_name,
    )

    validation = validate_export_inventory(inventory, export_dir=export_dir)

    return {
        "export_id": export_id,
        "export_dir": export_dir.as_posix(),
        "export_type": export_type,
        "base_name": base_name,
        "file_count": len(records),
        "total_size_bytes": sum(r.size_bytes for r in records),
        "source_xodr_sha256": source_xodr_sha256,
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
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for inventory export and validation."""
    parser = argparse.ArgumentParser(
        description="Export and validate a RoadRunner export inventory.",
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
        result = export_inventory(
            export_dir=args.export_dir,
            source_xodr_sha256=args.source_xodr_sha256,
            export_id=args.export_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Inventory written to {args.output}", file=sys.stderr)
    else:
        print(output)

    if not result["validation"]["valid"]:
        print(
            f"FAIL: {result['validation']['error_count']} validation error(s)",
            file=sys.stderr,
        )
        return 1

    print("PASS: inventory validation succeeded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
