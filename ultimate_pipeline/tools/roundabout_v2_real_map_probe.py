"""Run the opt-in Roundabout V2 analysis without modifying an OpenDRIVE map.

This tool deliberately has no pipeline or CARLA dependency.  It records whether
the current detector found candidates, the preserve/reconstruct decisions, and
whether V2's transactional API left the source XML tree untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

from ultimate_pipeline.topology.roundabout_v2 import RoundaboutV2Reconstructor


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


def probe_xodr(xodr_path: Path, *, osm_path: Path | None = None) -> dict[str, object]:
    """Return a machine-readable, non-mutating V2 analysis of ``xodr_path``."""
    xodr_path = xodr_path.resolve()
    resolved_osm_path = osm_path.resolve() if osm_path is not None else None
    root = ET.parse(xodr_path).getroot()
    before_tree_sha256 = _tree_digest(root)
    reconstructor = RoundaboutV2Reconstructor()
    models = reconstructor.analyze(root)
    clone, diagnostics = reconstructor.reconstruct_transactional(root)
    after_tree_sha256 = _tree_digest(root)
    records = [_model_record(model) for model in models]
    actions = Counter(record["action"] for record in records)
    reconstructed = sum(
        1
        for record in records
        if str(record["action"]).startswith("RECONSTRUCT")
    )
    acceptance = {
        "status": "NOT_RUN" if reconstructed == 0 else "INCOMPLETE",
        "reason": (
            "no_reconstructed_roundabout_candidates"
            if reconstructed == 0
            else "offline_probe_does_not_apply_or_certify_reconstructions"
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
            "candidates": records,
        },
        "source_osm": (
            _source_roundabout_counts(resolved_osm_path)
            if resolved_osm_path is not None
            else None
        ),
        "transaction": {
            "clone_distinct": clone is not root,
            "source_tree_sha256_before": before_tree_sha256,
            "source_tree_sha256_after": after_tree_sha256,
            "source_tree_unchanged": before_tree_sha256 == after_tree_sha256,
            "diagnostics": diagnostics,
        },
        "acceptance_delta": acceptance,
        "map_of_record_mutated": "NO",
        "live_carla": "NOT_RUN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xodr", required=True, type=Path, help="OpenDRIVE map to analyze")
    parser.add_argument("--osm", type=Path, help="Optional source OSM for semantic coverage evidence")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path")
    args = parser.parse_args(argv)
    report = probe_xodr(args.xodr, osm_path=args.osm)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
