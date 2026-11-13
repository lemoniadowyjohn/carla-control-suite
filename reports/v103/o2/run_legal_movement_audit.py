"""V103-O2 -- run the OSM legal-movement audit over the pinned real inputs.

Verifies the OSM bytes against the pinned manifest (a Git-LFS pointer is
NOT acceptable input), reads the OSM through the safe admission boundary,
builds the directed movement graph for one actor class, and emits the
versioned ``AllowedMovementReport``.

When an XODR map is supplied, the graph is ALSO joined to that map through
O1's oriented source correspondence, and every generated junction
connection is compared with the OSM movement that corresponds to it.  The
comparison is **non-destructive**: nothing in the map is rewritten.

Every unsatisfied precondition is reported as ``BLOCKED_INPUT`` and the
script exits non-zero.  Nothing here can report PASS on absent evidence.

Usage:
    py reports/v103/o2/run_legal_movement_audit.py [--vehicle motor_vehicle]
                                                     [--no-default-permission]
                                                     [--xodr <path>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from ultimate_pipeline.enrichment.osm_legal_movement import (  # noqa: E402
    SCHEMA_VERSION,
    build_allowed_movement_report,
    build_movement_graph,
    compare_with_junction_connections,
    render_report,
)
from ultimate_pipeline.enrichment.osm_restrictions import (  # noqa: E402
    OsmSourceError,
    read_osm_document,
)

SRC = Path("campaigns/ingolstadt_cooked_perception_v1/source")
OSM_REL = f"{SRC}/ingolstadt_authoritative.osm"
MANIFEST_REL = f"{SRC}/INPUTS_MANIFEST.json"
OUT_DIR = REPO / "reports/v103/o2"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def render_summary(report, *, per_status: int = 200) -> dict:
    """A compact, committable view of the report.

    The full movement listing for a real map runs to tens of megabytes
    (64,860 movements on the pinned Ingolstadt OSM), so the committed
    artifact carries the complete COUNTS, the complete restriction
    statistics, and a bounded sample per verdict.  The full listing is
    written separately and is not committed.
    """
    payload = report.to_dict()
    sample: list[dict] = []
    for status in sorted({m.status for m in report.movements}):
        subset = [m for m in report.movements if m.status == status]
        for movement in subset[:per_status]:
            sample.append(movement.to_dict())
    payload["movements"] = sample
    payload["movements_sampled"] = True
    payload["movements_total"] = len(report.movements)
    payload["movements_sample_per_status"] = per_status
    payload["note"] = (
        "movements is a bounded sample per verdict; the complete listing is "
        "written to the full report path and is not committed"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vehicle", default="motor_vehicle")
    parser.add_argument(
        "--no-default-permission",
        action="store_true",
        help="report an ungoverned movement as UNKNOWN_NO_SOURCE instead of the "
        "OSM data model's default permission",
    )
    parser.add_argument("--xodr", default="", help="an XODR map to join")
    args = parser.parse_args()

    out: dict = {
        "schema": "v103_o2_legal_movement_audit/v1",
        "report_schema_version": SCHEMA_VERSION,
        "vehicle_class": args.vehicle,
        "status": "NOT_RUN",
    }

    # --- verify the pinned OSM bytes ------------------------------------
    manifest_path = REPO / MANIFEST_REL
    if not manifest_path.is_file():
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = f"{MANIFEST_REL} missing"
        print(json.dumps(out, indent=2))
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["inputs"]["roads_osm"]
    osm_path = REPO / entry["path"]
    if not osm_path.is_file():
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = "pinned OSM missing (LFS object not resolved)"
        print(json.dumps(out, indent=2))
        return 1
    head = osm_path.open("rb").read(64)
    if head.startswith(b"version https://git-lfs.github.com/spec"):
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = "the pinned OSM is still a Git-LFS pointer, not map bytes"
        print(json.dumps(out, indent=2))
        return 1
    actual = sha256_file(osm_path)
    out["osm_source"] = {
        "path": entry["path"],
        "expected_sha256": entry["sha256"],
        "actual_sha256": actual,
        "expected_bytes": entry["bytes"],
        "actual_bytes": osm_path.stat().st_size,
        "sha256_match": actual == entry["sha256"],
        "bytes_match": osm_path.stat().st_size == entry["bytes"],
    }
    if actual != entry["sha256"]:
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = "the pinned OSM SHA-256 does not match the manifest"
        print(json.dumps(out, indent=2))
        return 1

    # --- read the OSM through the safe boundary -------------------------
    try:
        document = read_osm_document(osm_path)
    except OsmSourceError as exc:
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = f"OSM source could not be admitted: {exc}"
        print(json.dumps(out, indent=2))
        return 1

    out["osm_document"] = {
        "sha256": document.sha256,
        "bytes": document.byte_size,
        "node_count": len(document.nodes),
        "way_count": len(document.ways),
        "relation_count": document.relation_count,
        "restriction_relation_count": document.restriction_relation_count,
        "complete": document.complete,
        "generator": document.generator,
    }

    graph = build_movement_graph(document, vehicle_class=args.vehicle)
    report = build_allowed_movement_report(
        graph, default_permission=not args.no_default_permission
    )

    # --- optional XODR join through O1's oriented correspondence --------
    if args.xodr:
        xodr_path = Path(args.xodr)
        if not xodr_path.is_absolute():
            xodr_path = REPO / xodr_path
        if not xodr_path.is_file():
            out["xodr_join"] = {
                "status": "BLOCKED_INPUT",
                "reason": f"XODR map not found: {xodr_path}",
            }
        else:
            out["xodr_join"] = _join_to_xodr(xodr_path, graph, osm_path)

    out["report"] = report.to_dict()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"LEGAL_MOVEMENT_{args.vehicle.upper()}"
    full_path = OUT_DIR / f"{stem}_FULL.json"
    summary_path = OUT_DIR / f"{stem}_SUMMARY.json"

    # The complete listing is written but NOT committed: it is tens of
    # megabytes on a real map.
    full_path.write_text(render_report(report), encoding="utf-8")
    summary = render_summary(report)
    if "xodr_join" in out:
        # The XODR comparison is part of the evidence and must be
        # persisted, not only printed.  On the real map it is 22,589
        # connections, so it is sampled like the movements.
        join = dict(out["xodr_join"])
        comparisons = join.pop("comparisons", [])
        join["comparison_count"] = len(comparisons)
        join["comparison_sample"] = comparisons[:200]
        join["comparison_sampled"] = True
        summary["xodr_join"] = join
    summary["audit"] = {
        "osm_source": out.get("osm_source"),
        "osm_document": out.get("osm_document"),
        "vehicle_class": args.vehicle,
        "default_permission": not args.no_default_permission,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    out["written_summary"] = str(summary_path.relative_to(REPO))
    out["written_full_not_committed"] = str(full_path.relative_to(REPO))

    counts = report.counts
    print(f"vehicle_class      : {args.vehicle}")
    print(f"OSM sha256         : {document.sha256}")
    print(f"ways / relations   : {len(document.ways)} / {document.relation_count}")
    print(f"restriction rels   : {document.restriction_relation_count}")
    print(f"candidate movements: {len(report.movements)}")
    for status, count in sorted(counts.items()):
        if count:
            print(f"   {status:<26} {count}")
    print(f"restrictions applied / undecidable / malformed : "
          f"{report.restrictions_applied} / {report.undecidable_restrictions} / "
          f"{report.restrictions_ambiguous}")
    print(f"WROTE {summary_path}")
    print(f"WROTE {full_path}  (not committed: the full listing is large)")
    return 0


def _join_to_xodr(xodr_path: Path, graph, osm_path: Path) -> dict:
    """Join the movement graph to an XODR map through O1's correspondence."""
    try:
        from ultimate_pipeline.enrichment.osm_meta_index import (
            extract_structural_osm_lane_metadata_ways,
            project_positioned_osm_metadata_ways,
        )
        from ultimate_pipeline.enrichment.osm_xodr_correspondence import (
            build_metadata_associations,
        )

        root = ET.parse(str(xodr_path)).getroot()
        ways = extract_structural_osm_lane_metadata_ways(str(osm_path))
        projected = project_positioned_osm_metadata_ways(ways, root)
        associations, correspondence = build_metadata_associations(projected, root)
        comparisons = compare_with_junction_connections(root, graph, associations)
        counts: dict[str, int] = {}
        for comparison in comparisons:
            counts[comparison.status] = counts.get(comparison.status, 0) + 1
        return {
            "status": "PASS",
            "xodr": str(xodr_path.name),
            "xodr_road_count": len(root.findall("./road")),
            "junction_connection_count": len(comparisons),
            "correspondence_eligible_road_count": correspondence.get("eligible_road_count"),
            "counts": counts,
            "comparisons": [c.to_dict() for c in comparisons],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "BLOCKED_INPUT",
            "reason": f"{type(exc).__name__}: {exc}",
        }


if __name__ == "__main__":
    raise SystemExit(main())
