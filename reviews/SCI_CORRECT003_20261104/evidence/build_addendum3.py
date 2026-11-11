"""Build the PROPOSED gap register addendum 3 (draft; nothing is committed)."""
import collections
import json
import sys

REPO, OUT = sys.argv[1], sys.argv[2]
INPUT = "45c52059ec5b7d8d1e5f2f90a2f814bde465a923e7e77768c5f5e660790c721c"
MOR = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"
A1 = REPO + "/reports/production_readiness/20261103T000000Z_GAP_REGISTER_ADDENDUM/GAP_REGISTER_ADDENDUM.json"
A2 = REPO + "/reports/production_readiness/20261104T000000Z_GAP_REGISTER_ADDENDUM_2/GAP_REGISTER_ADDENDUM_2.json"

gap070 = {
    "id": "GAP-070", "update_kind": "evidence_update", "previous_status": "open", "status": "open",
    "severity": "P2", "proposed_severity": "P1",
    "proposed_severity_reason": (
        "Lane-level measurement: the default-on snap shifts the lane centres of outer-lane connectors by whole "
        "lane widths (non-U-turn entry gaps > 1 m: 114 -> 863) and creates 3,617 U-turn exit kinks > 30 deg. "
        "The defect is in the pipeline default, not only in a report metric."),
    "subsystem": "map geometry (junction connectors); pipeline default UP_ENABLE_JUNCTION_CONNECTOR_SNAP (stage 05)",
    "description": (
        "Refines addendum 2. "
        "(a) DEFAULT-SNAP CORRUPTION: on the same input, the merged default snap (integration 1a36b560) raises "
        "lane-centre entry gaps > 1 m from 355 to 4,472 and exit kinks > 30 deg from 359 to 3,728, over 23,406 "
        "junction laneLinks. Its moves equal cumulative incoming lane widths in 4,024 of 4,025 cases, and 19,195 of "
        "22,588 connectors start on their laneLink from-lane inner border before the snap: the snap treats correct "
        "lane-border placement as displacement. "
        "(b) CANDIDATE 2cee039f REJECTED: its Hermite refit collapses 3,375 shared-reference U-turn connectors "
        "(3,367 reverse direction; 423-426 self-intersect) and leaves @length != arc length on 344 of 650 others "
        "(max 4.02x). "
        "(c) SAFE DEFAULT-OFF CONTAINMENT: in the snap-OFF measurement arm (UP_ENABLE_JUNCTION_CONNECTOR_SNAP=0 on the "
        "same input), 99.41% of non-U-turn laneLinks are lane-centre continuous (<= 1 m). A default-OFF change is "
        "PROPOSED in C1 (branch fix/gap070-connector-snap-safety-c1-20261104), which is UNCOMMITTED and NOT REVIEWED; "
        "this entry does not rely on it. Containment is not a fix for every connector defect. "
        "(d) REMAINING: U-turn lane-level discontinuities are tracked separately as GAP-080; 114 entry and 108 exit "
        "non-U-turn residuals > 1 m remain with the snap OFF. "
        "(e) MISSING: an independent validator (O13) and a second implementation of the lane-centre metric. "
        "(f) PENDING: a governed regeneration (X8) from raw OSM, with OFF and historical-default arms."),
    "fixing_commit": None,
    "file_line": ("ultimate_pipeline/pipeline_stages/stage_05_geometry.py:103 (default, 1a36b560); "
                  "ultimate_pipeline/tools/junction_connector_snap.py:289 (rotate in place, 1a36b560)"),
    "regression_test": None,
    "evidence_artifact": ("docs/reviews/ARCH003_20261104/evidence/lane_centre_continuity.py (sha256 75750d4104053b0a51ee31f0da6f10edfdc7132675680ebd1458f1394ae303da), "
                          "lcc_off_cls.json (5fceedcab72a5bc43153225155c5c5891ecb59937358920a839692bec941d207), "
                          "lcc_merged_cls.json (566f86c09dcd98a616e5654897ecd5f79a437fda64462314d21f99a0a8f6aac3); "
                          "docs/reviews/ARCH002_20261104/; docs/reviews/ARCH_X8_X9_20261104/ (review package, publication pending); "
                          "input 05_planview sha256 " + INPUT),
    "evidence_class": "LOCAL_REPRODUCED (one implementation); second implementation NOT_RUN",
    "residual_risk": (
        "Closure requires all of:\n"
        "- C1 committed and reviewed (residuals stay visible when the snap is disabled; opt-in refused under strict or release);\n"
        "- an independent lane-centre validator;\n"
        "- an X8 regeneration from raw OSM, measured at lane level;\n"
        "- no tolerance raised (EXIT_HEADING_DISCONTINUITY_DEG stays 30.0)."),
}
gap079 = {
    "id": "GAP-079", "update_kind": "evidence_update", "previous_status": "open", "status": "open", "severity": "P2",
    "subsystem": "map geometry (junction connectors); SOURCE ATTRIBUTION = UNKNOWN_PENDING_RAW_OSM_REPRODUCTION",
    "description": (
        "CORRECTS the attribution in addendum 2 ('CARLA Osm2Odr (stage 01) + netconvert repair (stage 02)'). "
        "Run 20261007_214826_524342 did not convert OSM: its run_manifest.json records inputs.INPUT_XODR.sha256 = "
        + MOR + " (the 2026-09-16 map-of-record), and its stage 01 is byte-identical to that pin. The counts stand as "
        "population counts on that run: 58 stubs present in the map-of-record (stage 01) and 81 after the pipeline "
        "re-applies netconvert (stage 02, +23). The origin of the 58, and the stub count of a raw-OSM conversion, "
        "are UNKNOWN until a fresh Osm2Odr conversion of the pinned OSM is measured stage by stage."),
    "fixing_commit": None, "file_line": None, "regression_test": None,
    "evidence_artifact": ("reports/rq1_trial_runs/run_01/20261007_214826_524342/run_manifest.json and settings_snapshot.json "
                          "(local); X9 inventory @06a31ed1 (local branch); docs/reviews/ARCH003_20261104/ERRATA_TO_PRIOR_REVIEWS.md (publication pending)"),
    "evidence_class": "LOCAL_REPRODUCED (counts and input lineage); origin NOT_RUN",
    "residual_risk": (
        "The X9b netconvert bisection must start from a fresh Osm2Odr conversion. The stubs carry routing and must "
        "not be removed for their length. Reversal semantics (legal reversed reference line vs true reversal) are "
        "still unclassified."),
}
gap080 = {
    "id": "GAP-080", "update_kind": "new", "status": "open", "severity": "P1",
    "subsystem": ("map geometry (U-turn junction connectors); present in map-of-record " + MOR[:8]
                  + "...; source stage UNKNOWN_PENDING_RAW_OSM_REPRODUCTION"),
    "description": (
        "U-turn junction connectors (incoming and exit lane travel headings differ by > 150 deg) are "
        "lane-discontinuous with NO snap applied. Of 3,947 U-turn laneLinks, 3,696 have an entry lane-centre gap "
        "> 0.5 m (exit: 3,705), and 3,716 have an entry heading difference > 10 deg (exit: 3,722). "
        "Entry distribution:\n"
        "- gap p25/p50/p75 = 0.7467/0.7467/0.7467 m, p95 = 1.458 m;\n"
        "- heading p25/p50/p75 = 26.565 deg (= atan(1/2)), p95 = 50.9 deg.\n"
        "The exit side is equivalent. Synthetic control C (a connector starting on the correct lane border, rotated by "
        "atan(1/2) about its start) reproduces exactly 0.7467 m / 26.565 deg, so the observed signature matches that "
        "geometric form. Hypothesis (untested): a systematic template geometry produced the rotation; its cause is "
        "unknown. Input: 05_planview_20261007_214826_524342.xodr, sha256 " + INPUT + " (a byte copy of stage 03 "
        "of a run whose input was the map-of-record). Method: lane-centre position and travel heading per OpenDRIVE "
        "(laneOffset + width polynomials + lane-id sign; kernel reference pose), at the incoming road's junction end "
        "vs the connector start, and at the connector end vs the exit lane named by the lane's successor link."),
    "fixing_commit": None, "file_line": None, "regression_test": None,
    "evidence_artifact": ("docs/reviews/SCI_CORRECT003_20261104/evidence/lane_centre_continuity_v2.py (sha256 645d06bfe23e3bfff988926fd9a11a6c44be477483cb5cd32cb2432f46899bcb) "
                          "+ lcc_off_v2.json (a638fcce982c74f44b5fa82d39765aac1f3124b70e340fad6a302311ba43ab7d); "
                          "synthetic controls docs/reviews/ARCH003_20261104/evidence/controls/ (C_kinked.result.json "
                          "7e7194b040ae29969a92b4c93458b70bd1f372cf07201ddadba83f33bd012c77) (publication pending)"),
    "evidence_class": "LOCAL_REPRODUCED (one implementation + synthetic controls); second implementation NOT_RUN",
    "residual_risk": (
        "NOT claimed: that these U-turns are physically impossible or undrivable. That would need a vehicle-specific "
        "turning envelope and a CARLA traversal; GAP-077 blocks runtime. Their pre-snap peak reference-line curvature "
        "is about 0.61 m^-1 (radius ~1.6 m) per ARCH-X8-X9; that is an operator drivability question, not a verdict.\n"
        "Requires:\n"
        "- a second, independent implementation of the lane-centre metric;\n"
        "- a raw-OSM per-stage reproduction to locate the source stage;\n"
        "- a remedy decision: source-stage U-turn rebuild, exclusion from routing, or accept with documentation.\n"
        "Disabling the snap does not fix this."),
}
issues = [gap070, gap079, gap080]

a1 = json.load(open(A1, encoding="utf-8-sig"))
a2 = json.load(open(A2, encoding="utf-8"))
status = {g["id"]: g["status"] for g in a1["issues"]}
status.update({g["id"]: g["status"] for g in a2["issues"]})
status.update({g["id"]: g["status"] for g in issues})
c = collections.Counter(status.values())
doc = {
    "run_id": "PROPOSED_GAP_REGISTER_ADDENDUM_3 (draft; not committed)",
    "schema_version": 1,
    "supersedes": None,
    "amends": ["20261103T000000Z_GAP_REGISTER_ADDENDUM", "20261104T000000Z_GAP_REGISTER_ADDENDUM_2"],
    "amends_sha256": {"GAP_REGISTER_ADDENDUM_2.json": "5f59fc60fadfe3e1b14c0436a3eda6bfd3e0b3167219a6f764d2089940c94b6b"},
    "continues_from_highest_existing_id": "GAP-079",
    "id_allocation_check": ("No GAP-080 or higher exists on any local or origin branch (git grep over all 808 refs, all text files except map/raster/model data; no hits; "
                            "2026-11-04). GAP-080..084 appear only in the unregistered draft "
                            "docs/reviews/ARCH_X8_X9_20261104/CODEX_OPENCODE_EXECUTION_BACKLOG.md; that numbering is "
                            "superseded by this allocation."),
    "id_range_used": "GAP-080..GAP-080",
    "append_only": "Addenda 1 and 2 are not modified; entries here amend by id (the later entry wins).",
    "schema_note": a2["schema_note"] + " Adds the optional fields evidence_class, proposed_severity and proposed_severity_reason.",
    "issues": issues,
    "counts": dict(collections.Counter(g["status"] for g in issues), total=len(issues)),
    "register_state_after": {
        "total": len(status),
        "fixed": c["fixed"], "open": c["open"], "blocked_external": c["blocked_external"],
        "open_ids": sorted(k for k, v in status.items() if v == "open"),
        "blocked_external_ids": sorted(k for k, v in status.items() if v == "blocked_external"),
    },
}
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    json.dump(doc, f, indent=1)
print(doc["counts"], doc["register_state_after"])
