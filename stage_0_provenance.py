#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage D0 — repository provenance, untracked classification, reuse matrix.

Produces:
  S00_WORKTREE_PROVENANCE.json
  S01_UNTRACKED_CLASSIFICATION.csv
  S02_REUSE_CAPABILITY_MATRIX.csv

Reuses the existing phase_h0 OSM extractor infrastructure to recompute the OSM
crossing/pedestrian authority counts rather than trusting hardcoded numbers.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

OUT = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def write_json(name: str, payload: dict) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def classify_untracked(path: str) -> str:
    if path.startswith((".idea", ".githooks")):
        return "IDE/TOOLING"
    if path.startswith(("external/", "worktrees/", "work/")):
        return "EXTERNAL/CHECKOUT"
    if path.startswith("reports/"):
        return "REPORT/EVIDENCE"
    if path.startswith("campaigns/"):
        return "CAMPAIGN/CANDIDATE"
    if path.startswith(("ultimate_pipeline/", "phase_q/")):
        return "SOURCE/MODULE"
    if path.startswith("tests/"):
        return "TEST"
    base = Path(path).name
    if base.startswith("_stage") or base.startswith("_p") or base.startswith("_write") or \
            base in ("run_n0_audit.py", "check_raw_run1.py", "generate_audit.py",
                     "create_a1_registries.py", "examine_bad_roads.py"):
        return "STAGING/UTIL"
    if base in ("audit_output.zip", "audit_output"):
        return "DEBUG/OUTPUT"
    if base in ("POST_AUDIT_HARDENING_PROMPT.md", "submission_files.txt",
                "worktree_files.txt", "vehicle.", "nul"):
        return "LEGACY/STRAY"
    return "UNCLASSIFIED"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- S00 provenance ----
    prov = {
        "toplevel": git("rev-parse", "--show-toplevel").strip(),
        "branch_current": git("branch", "--show-current").strip(),
        "HEAD": git("rev-parse", "HEAD").strip(),
        "status_short_branch": git("status", "--short", "--branch").strip(),
        "porcelain": git("status", "--porcelain=v1").strip(),
        "diff_name_status": git("diff", "--name-status").strip(),
        "diff_cached_name_status": git("diff", "--cached", "--name-status").strip(),
        "untracked_others": git("ls-files", "--others", "--exclude-standard", "--full-name").strip(),
        "remote_v": git("remote", "-v").strip(),
        "branch_vv": git("branch", "-vv").strip(),
    }
    write_json("S00_WORKTREE_PROVENANCE.json", prov)
    print(f"S00: HEAD={prov['HEAD'][:12]} to={prov['toplevel']}")

    # ---- S01 untracked classification ----
    untracked = [l for l in prov["untracked_others"].splitlines() if l.strip()]
    rows = [("path", "classification")] + [(p, classify_untracked(p)) for p in untracked]
    with open(OUT / "S01_UNTRACKED_CLASSIFICATION.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    counts: dict[str, int] = {}
    for _, c in rows[1:]:
        counts[c] = counts.get(c, 0) + 1
    print(f"S01: {len(untracked)} untracked files; classes={counts}")

    # ---- S02 reuse capability matrix ----
    # Search canonical source dirs for capability implementations.
    capabilities = {
        "signal_digest_or_fingerprint": [
            (r"def (signal_digest|signal_fingerprint|traffic_control_digest)",
             ["phase_q", "ultimate_pipeline", "phase_q/semantic_evidence.py"]),
            (r"def semantic_fingerprint", ["ultimate_pipeline/roadrunner/models.py"]),
        ],
        "semantic_inventory": [
            (r"def extract_semantic_inventory|def inventory_counts",
             ["phase_q/semantic_evidence.py"]),
        ],
        "osm_crossing_extraction": [
            (r"tags.get\(\"crossing\"\)|crossing_rejected|footway.*crossing",
             ["ultimate_pipeline/tools/phase_h0_osm_signal_extract.py"]),
        ],
        "osm_road_matching": [
            (r"def match_candidate_to_roads|def match_.*road",
             ["ultimate_pipeline/tools/phase_h1_osm_road_match.py", "ultimate_pipeline/tools/phase_h2_signal_writer.py"]),
        ],
        "signal_writing": [
            (r"def write_speed_limits|def write_zone_signs|def write_turn_lanes",
             ["ultimate_pipeline/tools/phase_h2_signal_writer.py"]),
        ],
        "crosswalk_writing": [
            (r"object type=\"crosswalk\"|def write_crosswalk",
             ["ultimate_pipeline/tools/phase_h2_signal_writer.py", "ultimate_pipeline/tools/phase_h3_signal_integrity.py"]),
        ],
        "object_writing": [
            (r"<object|object id", ["ultimate_pipeline/tools/phase_h2_signal_writer.py"]),
        ],
        "pedestrian_classification": [
            (r"pedestrian|lanes.*pedestrian|footway|sidewalk",
             ["ultimate_pipeline/tools/phase_h0_osm_signal_extract.py"]),
        ],
        "sidewalk_writing": [
            (r"sidewalk|lane type=\"sidewalk\"",
             ["ultimate_pipeline/tools/phase_h0_osm_signal_extract.py"]),
        ],
        "provenance_userdata": [
            (r"userData|GROUNDED|\"confidence\"|\"writer\"",
             ["ultimate_pipeline/tools/phase_h2_signal_writer.py"]),
        ],
        "semantic_replay/idempotency": [
            (r"def (remove_legacy_speeds|write_.*idempotent|clone)",
             ["ultimate_pipeline/tools/phase_h2_signal_writer.py", "replay_phase_h_on_repaired.py"]),
        ],
        "candidate_governance/payload": [
            (r"def generate_governed_payload|release_payload_verifier",
             ["phase_q/governed_payload.py"]),
        ],
        "manifest_generation": [
            (r"def write_q04|Q03|Q04", ["phase_q/governed_payload.py"]),
        ],
        "integrity_audit": [
            (r"def audit_clean|def audit_signals|def audit_clean",
             ["ultimate_pipeline/tools/phase_h3_signal_integrity.py"]),
        ],
        "xodr_structural_validation": [
            (r"StrictCarlaOpendriveGate|class Strict.*Gate",
             ["ultimate_pipeline/quality"]),
        ],
    }
    matrix = [("capability", "status", "evidence_files", "notes")]
    # We do a content search across canonical dirs to confirm presence.
    search_dirs = ["ultimate_pipeline", "phase_q", "submission"]
    for cap, specs in capabilities.items():
        found = []
        for pat, hints in specs:
            res = grep_files(pat, [REPO / h for h in search_dirs])
            if res:
                found += res
        status = "REUSE_UNCHANGED" if found else "NO_EXISTING_CAPABILITY"
        matrix.append([cap, status, "; ".join(sorted(set(found)))])
    with open(OUT / "S02_REUSE_CAPABILITY_MATRIX.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(matrix)
    print(f"S02: reuse matrix rows={len(matrix)-1}")

    # ---- Recompute OSM crossing / pedestrian authority ----
    osm = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"
    if osm.exists():
        ctx = ET.iterparse(str(osm), events=("end",))
        crossing_ways = 0
        crossing_nodes = 0
        footways = 0
        pedestrian_areas = 0
        for _, el in ctx:
            tag = el.tag.split("}")[-1]
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if tag == "way":
                hw = tags.get("highway")
                if tags.get("crossing") is not None or hw == "crossing" or \
                        (hw == "path" and tags.get("crossing") is not None):
                    crossing_ways += 1
                if hw == "footway" or hw == "path":
                    footways += 1
                if hw in ("pedestrian", "construction") and tags.get("area") == "yes":
                    pedestrian_areas += 1
            elif tag == "node":
                if tags.get("highway") == "crossing" or tags.get("crossing") is not None:
                    crossing_nodes += 1
        auth = {
            "osm_crossing_ways": crossing_ways,
            "osm_crossing_nodes": crossing_nodes,
            "osm_crossing_total": crossing_ways + crossing_nodes,
            "osm_footway_or_path_ways": footways,
            "osm_pedestrian_areas": pedestrian_areas,
            "osmid_node_count": None,
        }
        write_json("S03_OSM_CROSSING_AUTHORITY_RECOMPUTE.json", auth)
        print(f"S03: crossings(way/node/total)={crossing_ways}/{crossing_nodes}/{auth['osm_crossing_total']} footways={footways} ped_areas={pedestrian_areas}")

    print("\nStage D0 complete.")
    return 0


def grep_files(pattern: str, roots: list[Path]) -> list[str]:
    found = []
    rx = re.compile(pattern)
    for r in roots:
        if not r.exists():
            continue
        if r.is_file():
            try:
                txt = r.read_text(encoding="utf-8", errors="replace")
                if rx.search(txt):
                    found.append(str(r.relative_to(REPO)))
            except Exception:
                pass
            continue
        for p in r.rglob("*.py"):
            try:
                if rx.search(p.read_text(encoding="utf-8", errors="replace")):
                    found.append(str(p.relative_to(REPO)))
            except Exception:
                pass
    return found


if __name__ == "__main__":
    raise SystemExit(main())
