#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 Step A — govern + promote the accepted C1 candidate (16ea2ec1...).

A1: byte-exact governed load payload via governed_payload_identity_guard/v1
    (temp -> fsync -> reopen -> declared==disk -> atomic rename -> reverify).
A2: promote to campaign candidate:

    * write governed payload bytes to
      campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr
      (LFS-tracked) with the same identity guard;
    * update campaigns/.../candidate/manifest.json and the top-level campaign
      manifest: retire the stale ff2a05e7 candidate_xodr pointer,
      perception_candidate -> governed payload hash, repaired parent and
      semantic parent labels preserved.

Evidence outputs (20260809T000000Z_C2_3DPACKAGE/perception_governed/):
    Q03_LOAD_PAYLOAD_MANIFEST.json   (manifest v1 + identity_guard record)
    Q04_GEOREFERENCE_SEMANTIC_DIFF.json
    PROMOTION_RECORD.json            (identity pass + manifest diff summary)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from phase_q.common import sha256_bytes, sha256_file, sha256_text
from phase_q.governed_payload import (
    atomic_write_payload_bytes,
    generate_governed_payload,
    generate_semantic_diff,
    verify_payload_identity,
)

RUN_DIR = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C2_3DPACKAGE"
GOV_DIR = RUN_DIR / "perception_governed"
CANDIDATE = (REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C1_GENERATION"
             / "candidate_crosswalk_enriched.xodr")
CAMPAIGN_CAND_FILE = (REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate"
                      / "ingolstadt_perception_final.xodr")
CAND_MANIFEST = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "manifest.json"
CAMPAIGN_MANIFEST = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "manifest.json"
REPAIRED = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_fixed_final.xodr"
SEMANTIC_PARENT = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z" / "candidate_g_semantic_enriched.xodr"

EXPECTED_CANDIDATE_RAW = "16ea2ec134b10d07518c63e1bd42c4ffd8b96113d1a52c0fe448f201c004d11f"
STALE_POINTER_SHA = "ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d"
PRODUCER_COMMIT = "8b400351d13634104090b31e535ced6e6d748648"


def main() -> int:
    GOV_DIR.mkdir(parents=True, exist_ok=True)

    candidate_raw = sha256_file(CANDIDATE)
    if candidate_raw != EXPECTED_CANDIDATE_RAW:
        print(f"HARD FAIL: candidate raw sha={candidate_raw} != {EXPECTED_CANDIDATE_RAW}")
        return 1
    candidate_text = CANDIDATE.read_text(encoding="utf-8", errors="replace")
    candidate_lf = sha256_text(candidate_text)
    print(f"candidate raw={candidate_raw[:16]} lf={candidate_lf[:16]} (lf==raw expected)")

    # ---- A1: generate governed payload (loader normalization) ----
    manifest = generate_governed_payload(
        candidate_text, PRODUCER_COMMIT,
        candidate_name="ingolstadt_perception_candidate_crosswalk")
    payload_text = manifest.pop("payload_text", "")
    payload_declared_sha = manifest["payload"]["sha256"]
    payload_bytes = payload_text.encode("utf-8")

    # ---- A2: identity-guarded writes (canonical campaign file + local copy) ----
    campaign_identity = atomic_write_payload_bytes(CAMPAIGN_CAND_FILE, payload_bytes)
    gov_copy = atomic_write_payload_bytes(GOV_DIR / "governed_payload.xodr", payload_bytes)
    reverify = verify_payload_identity(
        CAMPAIGN_CAND_FILE, campaign_identity["declared_sha256"],
        campaign_identity["declared_size"])
    if not reverify["identity_pass"]:
        print("HARD FAIL: post-write identity verification failed")
        return 1
    disk_sha = campaign_identity["post_rename_sha256"]
    if disk_sha != payload_declared_sha:
        print(f"HARD FAIL: declared={payload_declared_sha} disk={disk_sha}")
        return 1
    print(f"governed payload sha={disk_sha} size={campaign_identity['declared_size']}")

    manifest["perception_candidate_sha256"] = disk_sha
    manifest["identity_guard"] = {
        "campaign_file": campaign_identity,
        "run_dir_copy": gov_copy,
        "independent_reverify": reverify,
        "declared_vs_disk_equal": True,
    }
    q03 = GOV_DIR / "Q03_LOAD_PAYLOAD_MANIFEST.json"
    q03.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    q04 = GOV_DIR / "Q04_GEOREFERENCE_SEMANTIC_DIFF.json"
    q04.write_text(json.dumps(
        generate_semantic_diff(manifest), indent=2, sort_keys=True), encoding="utf-8")

    # ---- A2: manifest updates (retire ff2a05e7 pointer) ----
    def _retire(path: Path) -> dict:
        doc = json.loads(path.read_text(encoding="utf-8"))
        old = doc.get("candidate_xodr")
        retired = False
        if old is not None:
            if (old.get("sha256") or "").startswith(STALE_POINTER_SHA):
                doc["retired_candidate_xodr"] = {
                    "path": old.get("path"),
                    "sha256": old.get("sha256"),
                    "retired": True,
                    "retired_by": "C2 Step A promotion (CLAUDE_SEMANTIC_CANDIDATE_ACCEPTED); "
                                  "replaced by governed perception candidate",
                }
                retired = True
            del doc["candidate_xodr"]
        doc["perception_candidate"] = {
            "role": "governed perception load payload",
            "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr",
            "sha256": disk_sha,
            "byte_size": campaign_identity["declared_size"],
            "candidate_sha256": EXPECTED_CANDIDATE_RAW,
            "transformation": manifest["transformation_name"],
            "transformation_version": manifest["transformation_version"],
            "identity_guard": "governed_payload_identity_guard/v1",
            "promoted_from": "reports/post_audit_hardening/20260809T000000Z_C1_GENERATION/candidate_crosswalk_enriched.xodr",
        }
        doc["repaired_parent"] = {
            "role": "repaired parent",
            "path": str(REPAIRED.relative_to(REPO)).replace("\\", "/"),
            "sha256_bytes": sha256_file(REPAIRED),
        }
        doc["semantic_parent"] = {
            "role": "semantic parent",
            "path": "reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr",
            "sha256_lf_text": sha256_text(
                SEMANTIC_PARENT.read_text(encoding="utf-8", errors="replace")),
        }
        path.write_text(json.dumps(doc, indent=2, sort_keys=False), encoding="utf-8")
        return {"retired": retired, "perception_candidate_sha256": disk_sha}

    cand_upd = _retire(CAND_MANIFEST)
    camp_upd = _retire(CAMPAIGN_MANIFEST)

    record = {
        "run_id": "20260809T000000Z_C2",
        "stage": "C2-A",
        "event": "CLAUDE_SEMANTIC_CANDIDATE_ACCEPTED -> govern + promote",
        "producer": "stage_c2_govern_promote.py",
        "candidate": {
            "path": "reports/post_audit_hardening/20260809T000000Z_C1_GENERATION/candidate_crosswalk_enriched.xodr",
            "sha256_raw": EXPECTED_CANDIDATE_RAW,
            "sha256_lf_text": candidate_lf,
            "byte_size": CANDIDATE.stat().st_size,
        },
        "governed_payload": {
            "sha256": disk_sha,
            "byte_size": campaign_identity["declared_size"],
            "identity_guard_pass": reverify["identity_pass"],
            "post_rename_sha256": campaign_identity["post_rename_sha256"],
            "transformation_version": manifest["transformation_version"],
        },
        "promoted_file": str(CAMPAIGN_CAND_FILE.relative_to(REPO)).replace("\\", "/"),
        "manifest_updates": {
            "candidate_manifest": cand_upd,
            "campaign_manifest": camp_upd,
        },
        "stale_pointer_retired": STALE_POINTER_SHA,
        "parents": {
            "repaired_parent": "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_fixed_final.xodr",
            "semantic_parent": "reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr",
        },
        "verdict": "GOVERNED_AND_PROMOTED",
    }
    (GOV_DIR / "PROMOTION_RECORD.json").write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())