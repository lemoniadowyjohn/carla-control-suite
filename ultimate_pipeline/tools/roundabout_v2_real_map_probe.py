"""Run the opt-in Roundabout V2 analysis and offline candidate materialization.

This tool deliberately has no pipeline or CARLA dependency.  It records whether
the current detector found candidates, the preserve/reconstruct decisions, and
whether V2's transactional API left the source XML tree untouched.  A caller
may request a separately written candidate XODR; it is never a pipeline output
and can never overwrite the input map.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from time import perf_counter
import xml.etree.ElementTree as ET

from ultimate_pipeline.topology.roundabout_v2 import (
    RoundaboutV2Reconstructor,
    detect_candidates,
    detect_osm_spatial_candidates,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_digest(root: ET.Element) -> str:
    return hashlib.sha256(ET.tostring(root, encoding="utf-8")).hexdigest()


def _source_roundabout_counts(osm_path: Path) -> dict[str, object]:
    counts: Counter[str] = Counter()
    ways_scanned = 0
    for _, element in ET.iterparse(osm_path, events=("end",)):
        if element.tag != "way":
            continue
        ways_scanned += 1
        tags = {tag.get("k"): tag.get("v") for tag in element.findall("tag")}
        junction = tags.get("junction")
        if junction in {"roundabout", "circular"}:
            counts[junction] += 1
        element.clear()
    return {
        "osm_path": str(osm_path),
        "osm_sha256": _sha256_file(osm_path),
        "ways_scanned": ways_scanned,
        "roundabout_way_counts": dict(sorted(counts.items())),
        "roundabout_way_total": sum(counts.values()),
    }


def _model_record(model: object) -> dict[str, object]:
    candidate = model.candidate
    return {
        "junction_ids": list(candidate.junction_ids),
        "source_road_ids": list(candidate.road_ids),
        "osm_way_ids": list(candidate.osm_way_ids),
        "detection_method": candidate.detection_method,
        "detection_confidence": candidate.detection_confidence,
        "detection_reason": candidate.reason,
        "action": model.action,
        "geometry_kind": model.geometry_kind,
        "sample_count": len(model.samples),
        "anchor_count": len(model.anchors),
        "circle_fit": model.circle_fit,
    }


def _structural_delta(source: ET.Element, candidate: ET.Element) -> dict[str, object]:
    """Describe exactly what materialization changed without normalizing XML."""
    source_roads = {road.get("id", ""): road for road in source.findall("road")}
    candidate_roads = {road.get("id", ""): road for road in candidate.findall("road")}
    source_junctions = {
        junction.get("id", ""): junction for junction in source.findall("junction")
    }
    candidate_junctions = {
        junction.get("id", ""): junction for junction in candidate.findall("junction")
    }
    changed_existing_roads = sorted(
        road_id
        for road_id, road in source_roads.items()
        if road_id not in candidate_roads
        or ET.tostring(road, encoding="utf-8")
        != ET.tostring(candidate_roads[road_id], encoding="utf-8")
    )
    changed_existing_junctions = sorted(
        junction_id
        for junction_id, junction in source_junctions.items()
        if junction_id not in candidate_junctions
        or ET.tostring(junction, encoding="utf-8")
        != ET.tostring(candidate_junctions[junction_id], encoding="utf-8")
    )
    return {
        "road_count_before": len(source_roads),
        "road_count_after": len(candidate_roads),
        "junction_count_before": len(source_junctions),
        "junction_count_after": len(candidate_junctions),
        "added_road_ids": sorted(set(candidate_roads) - set(source_roads)),
        "removed_road_ids": sorted(set(source_roads) - set(candidate_roads)),
        "changed_existing_road_ids": changed_existing_roads,
        "changed_existing_junction_ids": changed_existing_junctions,
    }


def probe_xodr(
    xodr_path: Path,
    *,
    osm_path: Path | None = None,
    materialized_xodr_path: Path | None = None,
) -> dict[str, object]:
    """Return a machine-readable, non-mutating V2 analysis of ``xodr_path``."""
    xodr_path = xodr_path.resolve()
    resolved_osm_path = osm_path.resolve() if osm_path is not None else None
    root = ET.parse(xodr_path).getroot()
    before_tree_sha256 = _tree_digest(root)
    reconstructor = RoundaboutV2Reconstructor()
    timings: dict[str, float] = {}
    started = perf_counter()
    candidates = detect_candidates(root)
    timings["legacy_detection_seconds"] = round(perf_counter() - started, 6)
    source_detection = None
    if resolved_osm_path is not None:
        started = perf_counter()
        spatial_candidates, source_detection = detect_osm_spatial_candidates(
            root, resolved_osm_path
        )
        timings["source_aware_detection_seconds"] = round(
            perf_counter() - started, 6
        )
        candidates = sorted(
            [*candidates, *spatial_candidates],
            key=lambda candidate: (
                candidate.detection_method,
                candidate.osm_way_ids,
                candidate.junction_ids,
                candidate.road_ids,
            ),
        )
    started = perf_counter()
    models = reconstructor.analyze(root, candidates=candidates)
    timings["model_analysis_seconds"] = round(perf_counter() - started, 6)
    started = perf_counter()
    clone, diagnostics = reconstructor.reconstruct_transactional(
        root, candidates=candidates
    )
    timings["transactional_diagnostics_seconds"] = round(
        perf_counter() - started, 6
    )
    after_tree_sha256 = _tree_digest(root)
    records = [_model_record(model) for model in models]
    actions = Counter(record["action"] for record in records)
    applied = [
        record
        for record in diagnostics
        if record.get("materialization", {}).get("status") == "PASS"
    ]
    structural_delta = _structural_delta(root, clone)
    materialized_output = None
    if materialized_xodr_path is not None:
        output_path = materialized_xodr_path.resolve()
        if output_path == xodr_path:
            raise ValueError("materialized candidate must not overwrite its source XODR")
        if applied:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            ET.ElementTree(clone).write(output_path, encoding="utf-8", xml_declaration=True)
            materialized_output = {
                "status": "WRITTEN",
                "xodr_path": str(output_path),
                "xodr_sha256": _sha256_file(output_path),
            }
        else:
            materialized_output = {
                "status": "NOT_WRITTEN",
                "reason": "no_roundabout_candidate_materialized",
                "xodr_path": str(output_path),
            }
    acceptance = {
        "status": "NOT_RUN",
        "reason": (
            "no_roundabout_candidate_materialized"
            if not applied
            else "materialized_candidate_requires_external_acceptance_comparison"
        ),
    }
    return {
        "schema_version": 1,
        "tool": "ultimate_pipeline.tools.roundabout_v2_real_map_probe",
        "input": {
            "xodr_path": str(xodr_path),
            "xodr_sha256": _sha256_file(xodr_path),
        },
        "analysis": {
            "candidate_count": len(records),
            "action_counts": dict(sorted(actions.items())),
            "detection_method_counts": dict(
                sorted(Counter(record["detection_method"] for record in records).items())
            ),
            "candidates": records,
        },
        "source_osm": (
            _source_roundabout_counts(resolved_osm_path)
            if resolved_osm_path is not None
            else None
        ),
        "source_aware_detection": source_detection,
        "transaction": {
            "clone_distinct": clone is not root,
            "source_tree_sha256_before": before_tree_sha256,
            "source_tree_sha256_after": after_tree_sha256,
            "source_tree_unchanged": before_tree_sha256 == after_tree_sha256,
            "diagnostics": diagnostics,
            "applied_candidate_count": len(applied),
            "structural_delta": structural_delta,
            "materialized_output": materialized_output,
        },
        "acceptance_delta": acceptance,
        "timings_seconds": timings,
        "map_of_record_mutated": "NO",
        "live_carla": "NOT_RUN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xodr", required=True, type=Path, help="OpenDRIVE map to analyze")
    parser.add_argument("--osm", type=Path, help="Optional source OSM for semantic coverage evidence")
    parser.add_argument(
        "--materialized-xodr",
        type=Path,
        help="Write the offline V2 candidate here; refusing to overwrite --xodr",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path")
    args = parser.parse_args(argv)
    report = probe_xodr(
        args.xodr,
        osm_path=args.osm,
        materialized_xodr_path=args.materialized_xodr,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
