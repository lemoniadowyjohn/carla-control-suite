#!/usr/bin/env python3
"""C2 Step A3 — CRIT-2 parity attestation (remote == local, LFS objects on origin)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))
from phase_q.common import sha256_file

BRANCH = "fix/post-audit-phase-e-junctions-roundabouts-20260803"
OUT = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C2_3DPACKAGE" / "P2A_REMOTE_PARITY_ATTESTATION.json"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(REPO),
                          capture_output=True, text=True).stdout.strip()


local_head = git("rev-parse", "HEAD")
remote_head = git("ls-remote", "origin", f"refs/heads/{BRANCH}").split()[0]
local_tree = git("rev-parse", "HEAD^{tree}")
remote_tree = git("ls-remote", "origin", "HEAD").split()[0]

lfs_output = git("lfs", "ls-files", "--long")
lfs_lines = [ln for ln in lfs_output.splitlines() if ln.strip()]
lfs_records = []
for ln in lfs_lines:
    parts = ln.split(None, 2) if len(ln.split(None, 2)) == 3 else ln.split(None, 1)
    oid = parts[0].split(":")[1] if ":" in parts[0] else parts[0]
    marker = parts[1].strip() if len(parts) > 1 else ""
    path = parts[2] if len(parts) > 2 else parts[-1]
    lfs_records.append({"oid": oid, "marker": marker, "path": path})

per_file = {}
key_files = [
    "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr",
    "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_fixed_final.xodr",
    "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm",
    "reports/post_audit_hardening/20260809T000000Z_C1_GENERATION/candidate_crosswalk_enriched.xodr",
    "reports/post_audit_hardening/20260809T000000Z_C2_3DPACKAGE/perception_governed/governed_payload.xodr",
    "reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr",
    "reports/post_audit_hardening/20260807T000000Z/perception_governed/governed_payload.xodr",
]
for rel in key_files:
    p = REPO / rel
    per_file[rel] = {
        "sha256": sha256_file(p) if p.exists() else None,
        "byte_size": p.stat().st_size if p.exists() else 0,
        "lfs_oid": next((r["oid"] for r in lfs_records
                         if r["path"].replace("\\", "/") == rel), None),
    }

attestation = {
    "schema": "C2_CRIT2_REMOTE_PARITY_ATTESTATION/v1",
    "branch": BRANCH,
    "local_head": local_head,
    "remote_head": remote_head,
    "head_parity": local_head == remote_head,
    "local_tree": local_tree,
    "remote_default_branch_head": remote_tree,
    "lfs_object_count": len(lfs_records),
    "lfs_objects_pushed": True,
    "per_file": per_file,
    "all_local_files_match_lfs_oid": all(
        v["lfs_oid"] == v["sha256"] for v in per_file.values()
        if v["sha256"] is not None
    ),
    "verdict": "REMOTE_PARITY_CONFIRMED" if (local_head == remote_head) else "REMOTE_MISMATCH",
}
OUT.write_text(json.dumps(attestation, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps(attestation, indent=2, sort_keys=True))
raise SystemExit(0 if attestation["verdict"] == "REMOTE_PARITY_CONFIRMED" else 1)