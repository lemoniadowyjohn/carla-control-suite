"""Record offline F1 CRS and optional structure-elevation gate evidence.

The probe only reads its XODR, OSM, and DEM inputs.  It intentionally does not
repair geometry, write the map, or invoke CARLA.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from ultimate_pipeline.dem.dem_crs_contract import verify_crs_contract
from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter
from ultimate_pipeline.enrichment.structure_classifier import classify_xodr_roads
from ultimate_pipeline.quality.check_structure_elevation_plausibility import (
    check_structure_elevation_plausibility,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _classification_summary(record: dict[str, object]) -> dict[str, object]:
    return {
        key: record[key]
        for key in (
            "verdict",
            "ok",
            "roads_total",
            "class_counts",
            "matched_length_m",
            "total_length_m",
            "matched_fraction",
            "buffer_m",
            "class_fraction",
            "sample_spacing_m",
            "structure_way_ids_matched",
        )
    }


def _gate_summary(record: dict[str, object]) -> dict[str, object]:
    records = list(record.get("records", []))
    by_class = Counter(item["class"] for item in records)
    return {
        "status": record["status"],
        "ok": record["ok"],
        "thresholds": record["thresholds"],
        "checked_road_count": record["checked_road_count"],
        "status_counts": record["status_counts"],
        "checked_class_counts": dict(sorted(by_class.items())),
        "skipped_terrain_ambiguous_class_counts": record[
            "skipped_terrain_ambiguous_class_counts"
        ],
        "failures": [item for item in records if item["status"] == "FAIL"],
        "incomplete": [item for item in records if item["status"] == "INCOMPLETE"],
    }


def probe_xodr(
    xodr_path: Path,
    *,
    osm_path: Path | None = None,
    dem_path: Path | None = None,
    run_gate: bool = False,
) -> dict[str, object]:
    """Return read-only F1 evidence and optionally execute the DEM gate."""
    xodr_path = xodr_path.resolve()
    resolved_osm_path = osm_path.resolve() if osm_path is not None else None
    resolved_dem_path = dem_path.resolve() if dem_path is not None else None
    before_sha256 = _sha256_file(xodr_path)
    crs = verify_crs_contract(
        str(xodr_path), osm_path=str(resolved_osm_path) if resolved_osm_path else None
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "tool": "ultimate_pipeline.tools.structure_elevation_crs_probe",
        "input": {
            "xodr_path": str(xodr_path),
            "xodr_sha256": before_sha256,
            "osm_path": str(resolved_osm_path) if resolved_osm_path else None,
            "osm_sha256": _sha256_file(resolved_osm_path)
            if resolved_osm_path
            else None,
            "dem_path": str(resolved_dem_path) if resolved_dem_path else None,
            "dem_sha256": _sha256_file(resolved_dem_path)
            if resolved_dem_path
            else None,
        },
        "crs_contract": crs,
        "structure_elevation_gate": {
            "status": "NOT_RUN",
            "reason": "run_gate_not_requested",
        },
        "map_of_record_mutated": "NO",
        "live_carla": "NOT_RUN",
    }
    if run_gate:
        if resolved_osm_path is None or resolved_dem_path is None:
            raise ValueError("--run-gate requires both --osm and --dem")
        classification = classify_xodr_roads(
            str(xodr_path), osm_path=str(resolved_osm_path)
        )
        sampler = ElevationImporter.make_raster_sampler(
            str(resolved_dem_path),
            xodr_path=str(xodr_path),
            osm_path=str(resolved_osm_path),
        )
        classes = {
            road_id: item["class"]
            for road_id, item in classification["per_road"].items()
        }
        gate = check_structure_elevation_plausibility(
            str(xodr_path), road_classes=classes, terrain_sampler=sampler
        )
        report["structure_classification"] = _classification_summary(classification)
        report["structure_elevation_gate"] = _gate_summary(gate)
    report["source_xodr_sha256_after"] = _sha256_file(xodr_path)
    report["source_xodr_unchanged"] = before_sha256 == report["source_xodr_sha256_after"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xodr", required=True, type=Path)
    parser.add_argument("--osm", type=Path)
    parser.add_argument("--dem", type=Path)
    parser.add_argument("--run-gate", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = probe_xodr(
        args.xodr, osm_path=args.osm, dem_path=args.dem, run_gate=args.run_gate
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
