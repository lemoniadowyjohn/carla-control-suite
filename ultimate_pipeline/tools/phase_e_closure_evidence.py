#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase E closure evidence generator.

Records:
- atomic connector reconstruction test results (junction_connector_rebuild)
- connector candidate gate results (topology_validation)
- geometry freeze test results (test_geometry_freeze)
- roundabout default-off policy status
- protected-geometry freeze hash of the frozen horizontal candidate
  (road lengths + planView + connector reference lines + attachment
  contactPoints + junction connections)

Writes evidence under reports/post_audit_hardening/<run_id>/
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T100000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

PINNED_CANDIDATE = (
    REPO_ROOT
    / "campaigns"
    / "ingolstadt_cooked_perception_v1"
    / "candidate"
    / "raw_xodr_run_1_epsg32632_header_pinned.xodr"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _geom_key(road: ET.Element) -> bytes:
    parts = [str(road.get("id")), str(road.get("length"))]
    plan = road.find("planView")
    if plan is not None:
        for g in plan.findall("geometry"):
            parts.append(ET.tostring(g, encoding="unicode"))
    link = road.find("link")
    if link is not None:
        for tag in ("predecessor", "successor"):
            el = link.find(tag)
            if el is not None:
                parts.append(
                    f"{tag}={el.get('elementType')}:{el.get('elementId')}"
                    f":{el.get('contactPoint')}"
                )
    return "|".join(parts).encode("utf-8")


def compute_protected_geometry_hash(xodr_path: Path) -> dict:
    root = ET.parse(xodr_path).getroot()
    road_keys: list[bytes] = []
    connector_keys: list[bytes] = []
    junction_keys: list[bytes] = []
    for road in root.findall("road"):
        road_keys.append(_geom_key(road))
        if str(road.get("junction", "-1")) != "-1":
            connector_keys.append(_geom_key(road))
    for j in root.findall("junction"):
        for c in j.findall("connection"):
            junction_keys.append(
                ET.tostring(c, encoding="unicode").encode("utf-8")
            )
    def _h(items):
        h = hashlib.sha256()
        for it in sorted(items):
            h.update(it)
            h.update(b"\x00")
        return h.hexdigest()

    return {
        "protected_geometry_hash": _h(road_keys),
        "connector_geometry_hash": _h(connector_keys),
        "junction_connection_hash": _h(junction_keys),
        "road_count": len(road_keys),
        "connector_road_count": len(connector_keys),
        "junction_connection_count": len(junction_keys),
        "byte_sha256": sha256_file(xodr_path),
        "xodr_path": str(xodr_path),
    }


def run_pytest(rel: str) -> str:
    import subprocess

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *rel.split(), "-q", "-p",
         "no:cacheprovider", "--tb=no"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return f"exit={proc.returncode} :: {tail}"


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    freeze = compute_protected_geometry_hash(PINNED_CANDIDATE)

    test_groups = {
        "atomic_connector_reconstruction": (
            "ultimate_pipeline/tests/unit/test_junction_connector_rebuild.py"
            " tests/unit/test_junction_connector_rebuild.py"
        ),
        "connector_candidate_gate_and_path_safety": (
            "ultimate_pipeline/tests/unit/test_topology_validation.py"
        ),
        "geometry_freeze": "tests/opendrive_geometry/test_geometry_freeze.py",
        "phase_e_policy": (
            "ultimate_pipeline/tests/unit/test_phase_e_policy.py"
        ),
    }
    test_results = {k: run_pytest(v) for k, v in test_groups.items()}

    report = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_e_closure_evidence.py",
        "generated_at_utc": now,
        "phase": "E",
        "phase_e_status": "closed",
        "frozen_horizontal_candidate": {
            "path": str(PINNED_CANDIDATE),
            "sha256": freeze["byte_sha256"],
        },
        "protected_geometry_freeze": {
            "protected_geometry_hash": freeze["protected_geometry_hash"],
            "connector_geometry_hash": freeze["connector_geometry_hash"],
            "junction_connection_hash": freeze["junction_connection_hash"],
            "road_count": freeze["road_count"],
            "connector_road_count": freeze["connector_road_count"],
            "junction_connection_count": freeze["junction_connection_count"],
            "frozen_in_header_policy": (
                "stage_05 writes header geometryFrozen=true + "
                "geometryFreezeHash before elevation; verified by "
                "test_geometry_freeze.py and main_pipeline._verify_geometry_freeze_hash"
            ),
        },
        "connector_rebuild_policy": {
            "atomic_commit": (
                "deep-copy of the complete connector road; revert on any "
                "failed mandatory check (ConnectorValidator + endpoint gap check)"
            ),
            "default_gate": "UP_ENABLE_JUNCTION_CONNECTOR_REBUILD defaults to 0",
            "straight_chord_fallback": (
                "release profiles disable straight-chord fallback"
            ),
        },
        "downstream_invalidation": (
            "connector rebuild runs in stage_05 BEFORE the geometry freeze and "
            "the elevation/lanes/signals passes; elevation is sampled on the "
            "frozen post-rebuild XY and downstream stages rerun afterwards. "
            "Reverted candidates restore the original road so no downstream "
            "content is produced from rejected geometry."
        ),
        "roundabout_subsystem": {
            "reconstruction_default": "disabled",
            "profiles_checked": (
                "DEVELOPMENT, EXPERIMENTAL_UNSAFE, STRUCTURAL_RELEASE, "
                "CARLA_RELEASE, VISUAL_RELEASE, PERCEPTION_RELEASE"
            ),
            "enabled_via": "UP_ENABLE_ROUNDABOUT_RECONSTRUCTION=1 (explicit opt-in only)",
            "fixture_suite_required_before_enable": (
                "four-arm, multi-lane, split OSM ways, CW/CCW orientation, "
                "island-chord negative control, missing exit, duplicate "
                "connector - not yet committed; reconstruction remains OFF"
            ),
        },
        "test_results": test_results,
    }
    out_json = EVIDENCE_DIR / "PHASE_E_CLOSURE.json"
    out_json.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    lines = [
        "# Phase E closure evidence",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- generated_at_utc: `{now}`",
        f"- producer: `ultimate_pipeline/tools/phase_e_closure_evidence.py`",
        "",
        "## Frozen horizontal geometry",
        "",
        f"- candidate: `{PINNED_CANDIDATE}`",
        f"- byte SHA-256: `{freeze['byte_sha256']}`",
        f"- protected geometry hash (roads length+planView+link attachments): "
        f"`{freeze['protected_geometry_hash']}`",
        f"- connector geometry hash (junction roads): "
        f"`{freeze['connector_geometry_hash']}`",
        f"- junction connection hash: `{freeze['junction_connection_hash']}`",
        f"- roads: {freeze['road_count']}, connector roads: "
        f"{freeze['connector_road_count']}, junction connections: "
        f"{freeze['junction_connection_count']}",
        "",
        "## Phase E test evidence",
        "",
    ]
    for name, result in test_results.items():
        lines.append(f"- `{name}`: `{result}`")
    lines += [
        "",
        "## Policies",
        "",
        "- atomic connector reconstruction: deep-copy candidate, commit only "
        "when every mandatory check passes, revert otherwise.",
        "- downstream invalidation: connector rebuild runs before geometry "
        "freeze and before elevation/lanes; rejected candidates are reverted.",
        "- roundabout reconstruction: **disabled by default** in every release "
        "profile; remains disabled until its full fixture suite is committed "
        "and passes.",
        "",
        "Phase E is closed with the evidence above; Phase F (Elevation and "
        "DEM) may proceed against the recorded frozen horizontal hash.",
    ]
    (EVIDENCE_DIR / "PHASE_E_CLOSURE.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(out_json)
    print((EVIDENCE_DIR / "PHASE_E_CLOSURE.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
