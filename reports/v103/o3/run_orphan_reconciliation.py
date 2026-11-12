"""V103-O3 — OSM-04: per-ID reconciliation of the six historically flagged roads.

Registry issue **R15** / adversarial row **OSM-04**: the six historically
flagged orphan road ids must each be resolved with evidence, or explicitly
reported as unresolved -- never inferred from an old report.

The script uses the real map-of-record candidate and the pinned OSM source
(digest-verified), and writes
``reports/v103/o3/ORPHAN_ROAD_SOURCE_RECONCILIATION.csv``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

HISTORICAL_IDS = ("42367", "43405", "46369", "46698", "48129", "51657")

#: The registry key of the audited map.  V104 review 4551845563: the map
#: under audit must be resolved and verified through the registry pin, not
#: through a hardcoded path -- otherwise a re-pinned map-of-record would
#: still be audited through this stale file and the report would claim the
#: historical ids were absent from the *current* map.
CANDIDATE_REGISTRY_KEY = "auto_map_of_record"

#: Retained for the human-readable report label only; the authoritative
#: resolution is the registry lookup below.
CANDIDATE = (
    "campaigns/ingolstadt_cooked_perception_v1/candidate/"
    "ingolstadt_perception_map_of_record_20260916_232831.xodr"
)
OSM = (
    "campaigns/ingolstadt_cooked_perception_v1/source/"
    "ingolstadt_authoritative.osm"
)
MANIFEST = (
    "campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out_dir = REPO / "reports/v103/o3"
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "schema": "v103_o3_orphan_road_reconciliation/v1",
        "historical_ids": list(HISTORICAL_IDS),
        "candidate": CANDIDATE,
        "status": "NOT_RUN",
        "rows": [],
    }

    osm_path = REPO / OSM

    # V104 review 4551845563: resolve the audited map through the registry
    # and verify its bytes.  A hardcoded path is not authority.
    candidate_path = None
    registry_entry = {}
    try:
        from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

        registry_entry = verify_pinned_map(CANDIDATE_REGISTRY_KEY, base_dir=REPO)
        raw = registry_entry.get("path") or registry_entry.get("relative_path")
        if raw:
            candidate_path = Path(raw)
            if not candidate_path.is_absolute():
                candidate_path = (REPO / candidate_path).resolve()
        report["candidate_registry_key"] = CANDIDATE_REGISTRY_KEY
        report["candidate_registry_sha256"] = registry_entry.get("sha256")
        report["candidate_registry_path"] = str(candidate_path or "")
    except Exception as exc:
        report["status"] = "BLOCKED_INPUT"
        report["reason"] = f"map_of_record_pin_unverified:{type(exc).__name__}: {exc}"
        (out_dir / "ORPHAN_ROAD_SOURCE_RECONCILIATION.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
        return 1

    if not osm_path.is_file() or candidate_path is None or not candidate_path.is_file():
        report["status"] = "BLOCKED_INPUT"
        report["reason"] = "OSM source or candidate map missing"
        (out_dir / "ORPHAN_ROAD_SOURCE_RECONCILIATION.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
        return 1

    # --- verify the pinned OSM digest -------------------------------------
    manifest = json.loads((REPO / MANIFEST).read_text(encoding="utf-8"))
    expected = manifest["inputs"]["roads_osm"]["sha256"]
    actual = sha256_file(osm_path)
    report["osm_source"] = {
        "path": OSM,
        "expected_sha256": expected,
        "actual_sha256": actual,
        "sha256_match": expected == actual,
    }
    if expected != actual:
        report["status"] = "BLOCKED_INPUT"
        report["reason"] = "OSM SHA-256 does not match the pinned manifest"
        (out_dir / "ORPHAN_ROAD_SOURCE_RECONCILIATION.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
        return 1

    report["candidate_sha256"] = sha256_file(candidate_path)
    # The registry already verified the bytes; record the comparison so a
    # drift is visible in the evidence rather than assumed.
    pinned_sha = str(registry_entry.get("sha256") or "")
    if pinned_sha:
        report["candidate_matches_registry_pin"] = (
            report["candidate_sha256"] == pinned_sha
        )
        if not report["candidate_matches_registry_pin"]:
            report["status"] = "BLOCKED_INPUT"
            report["reason"] = "candidate_digest_differs_from_registry_pin"

    from ultimate_pipeline.enrichment.osm_meta_index import (
        extract_structural_osm_lane_metadata_ways,
        project_positioned_osm_metadata_ways,
    )
    from ultimate_pipeline.enrichment.osm_xodr_correspondence import (
        build_metadata_associations,
    )
    from ultimate_pipeline.quality.osm_road_link_topology import (
        extract_osm_highway_ways,
    )
    from ultimate_pipeline.topology.orphan_road_repair import (
        ORPHAN_STATUS_REPAIRED,
        ORPHAN_STATUS_UNRESOLVED,
        find_orphan_roads,
        find_unreachable_roads,
        reconcile_orphan_roads,
    )

    root = ET.parse(str(candidate_path)).getroot()
    roads = {str(r.get("id")): r for r in root.findall("./road") if r.get("id")}
    report["candidate_road_count"] = len(roads)

    orphans = set(find_orphan_roads(root))
    unreachable = set(find_unreachable_roads(root))
    report["candidate_orphan_count"] = len(orphans)
    report["candidate_unreachable_count"] = len(unreachable)
    report["candidate_unreachable_sample"] = sorted(unreachable)[:50]

    # --- OSM correspondence over the real candidate -----------------------
    source_ways = extract_structural_osm_lane_metadata_ways(str(osm_path))
    projected = project_positioned_osm_metadata_ways(source_ways, root)
    associations, corr_report = build_metadata_associations(projected, root)
    report["correspondence"] = {
        "source_way_count": corr_report.get("source_way_count"),
        "eligible_road_count": corr_report.get("eligible_road_count"),
        "match_class_counts": corr_report.get("match_class_counts"),
    }

    # --- reconcile the orphans --------------------------------------------
    highway_ways = extract_osm_highway_ways(str(osm_path))
    candidates = reconcile_orphan_roads(
        root,
        osm_ways=highway_ways,
        associations=associations,
    )
    by_id = {c.xodr_road_id: c for c in candidates}

    # --- the six historical ids ------------------------------------------
    rows = []
    for road_id in HISTORICAL_IDS:
        road = roads.get(road_id)
        if road is None:
            rows.append(
                {
                    "xodr_road_id": road_id,
                    "status": "ABSENT_FROM_CURRENT_MAP",
                    "reason": "road id does not exist in the current map-of-record candidate",
                    "source_way_id": "",
                    "neighbour_way_id": "",
                    "shared_node_id": "",
                    "neighbour_xodr_road_id": "",
                    "gap_m": "",
                    "dz_m": "",
                    "evidence": f"candidate={CANDIDATE}",
                }
            )
            continue
        candidate = by_id.get(road_id)
        association = associations.get(road_id)
        if candidate is None:
            rows.append(
                {
                    "xodr_road_id": road_id,
                    "status": "NOT_AN_ORPHAN",
                    "reason": "road declares a road-level link",
                    "source_way_id": str((association or {}).get("osm_way_id", "")),
                    "neighbour_way_id": "",
                    "shared_node_id": "",
                    "neighbour_xodr_road_id": "",
                    "gap_m": "",
                    "dz_m": "",
                    "evidence": "is_orphan=false",
                }
            )
            continue
        row = candidate.to_row()
        rows.append(row)

    report["rows"] = rows
    report["status"] = "PASS"
    report["reconciliation"] = {
        "orphan_count": len(candidates),
        "repaired_count": sum(1 for c in candidates if c.status == ORPHAN_STATUS_REPAIRED),
        "unresolved_count": sum(
            1 for c in candidates if c.status == ORPHAN_STATUS_UNRESOLVED
        ),
    }

    csv_path = out_dir / "ORPHAN_ROAD_SOURCE_RECONCILIATION.csv"
    fieldnames = [
        "xodr_road_id",
        "status",
        "reason",
        "source_way_id",
        "neighbour_way_id",
        "shared_node_id",
        "neighbour_xodr_road_id",
        "gap_m",
        "dz_m",
        "evidence",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    (out_dir / "ORPHAN_ROAD_SOURCE_RECONCILIATION.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "OSM_XODR_ROAD_GRAPH_AUDIT.json").write_text(
        json.dumps(
            {
                "schema": "osm_xodr_road_graph_audit/v1",
                "candidate": CANDIDATE,
                "candidate_sha256": report["candidate_sha256"],
                "osm_source": report["osm_source"],
                "correspondence": report["correspondence"],
                "orphan_count": len(orphans),
                "orphan_sample": sorted(orphans)[:50],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, sort_keys=True)[:6000])
    print("WROTE", csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
