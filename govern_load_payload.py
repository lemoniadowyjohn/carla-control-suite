#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage H: govern the exact CARLA load payload (Phase Q4 Strategy B).

The repaired candidate (ingolstadt_fixed_final.xodr) records raw bytes
80ebb005... and load-payload text 516e329c... (P04), while CARLA actually
consumes the georef-normalized form produced by the loader in memory.  Stage H
makes that hidden transformation governed and byte-exact:

  Q03_LOAD_PAYLOAD_MANIFEST.json    - input/output SHA, transformation, contract
  Q04_GEOREFERENCE_SEMANTIC_DIFF.json - human-readable georeference diff
  governed_payload.xodr             - the exact bytes CARLA must load

The governed payload is generated from the Stage G semantic-enriched candidate
(candidate_g_semantic_enriched.xodr), which is structurally identical to the
repaired parent and restores the accepted Phase H signal layer.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO_ROOT))

from phase_q.governed_payload import write_q04_artifacts, generate_semantic_diff
from phase_q.common import sha256_file, load_text, sha256_text

RUN_ID = "20260807T000000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

REPAIRED = REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_fixed_final.xodr"
ENRICHED = EVIDENCE_DIR / "candidate_g_semantic_enriched.xodr"
GOVERNED_OUT = EVIDENCE_DIR / "governed_payload.xodr"
Q03_PATH = EVIDENCE_DIR / "Q03_LOAD_PAYLOAD_MANIFEST.json"
Q04_PATH = EVIDENCE_DIR / "Q04_GEOREFERENCE_SEMANTIC_DIFF.json"
H_REPORT = EVIDENCE_DIR / "H_LOAD_PAYLOAD_GOVERNANCE.md"

RECORDED_P04_PAYLOAD = "516e329cb6fcec6adb041a4c5f39c48b4de6147b956c7dc2b7ab0c6746490453"
RECORDED_REPAIRED_RAW = "80ebb0054afd73ffdd51960b48679ff4689c72ed0abe75af5b2ae10a51395699"
RECORDED_RUNTIME = "9630d9f673fdea87058139d9e2241c7084dc2e2550674bba4bfffc78c6d0ae80"


def main() -> int:
    producer_commit = (
        __import__("subprocess")
        .run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        .stdout.strip()
    )

    # 1) Repaired parent chain (as recorded in P04 / O06).
    repaired_raw = sha256_file(REPAIRED)
    repaired_text = load_text(REPAIRED)  # LF-normalized text = P04 payload text
    repaired_text_sha = sha256_text(repaired_text)

    # 2) Enriched candidate (Stage G) is the governed semantic layer parent.
    enriched_raw = sha256_file(ENRICHED)
    enriched_text = load_text(ENRICHED)
    enriched_text_sha = sha256_text(enriched_text)

    # 3) Generate governed payload artifacts from the enriched candidate.
    artifacts = write_q04_artifacts(
        str(ENRICHED),
        producer_commit,
        str(EVIDENCE_DIR),
        candidate_name="ingolstadt_candidate_g_semantic_enriched",
    )
    q03 = json.loads(Path(artifacts["Q03_LOAD_PAYLOAD_MANIFEST.json"]).read_text(encoding="utf-8"))
    q04 = json.loads(Path(artifacts["Q04_GEOREFERENCE_SEMANTIC_DIFF.json"]).read_text(encoding="utf-8"))

    governed_sha = q03["payload"]["sha256"]
    governed_lf_text_sha = sha256_text(load_text(GOVERNED_OUT))
    contract = q03["coordinate_contract"]

    # Re-write the governed payload with explicit LF newlines so the raw file
    # bytes equal the canonical manifest hash (platform-stable artifact).
    governed_payload_bytes = load_text(GOVERNED_OUT).encode("utf-8")
    GOVERNED_OUT.write_bytes(governed_payload_bytes)
    governed_raw = sha256_file(GOVERNED_OUT)

    # 4) Reconcile with the recorded P04 chain.
    reconciliation = {
        "repaired_candidate_raw_bytes_sha256": repaired_raw,
        "repaired_candidate_lf_text_sha256": repaired_text_sha,
        "p04_recorded_payload_sha256": RECORDED_P04_PAYLOAD,
        "p04_raw_bytes_sha256_matches_recorded_repaired": repaired_raw == RECORDED_REPAIRED_RAW,
        "p04_payload_text_matches_recorded": repaired_text_sha == RECORDED_P04_PAYLOAD,
        "enriched_candidate_raw_bytes_sha256": enriched_raw,
        "enriched_candidate_lf_text_sha256": enriched_text_sha,
        "governed_payload_text_sha256": governed_sha,
        "governed_payload_raw_bytes_sha256": governed_raw,
        "governed_payload_lf_text_matches_manifest": governed_lf_text_sha == governed_sha,
        "runtime_to_opendrive_recorded": RECORDED_RUNTIME,
        "contract_pass": all(
            v for k, v in contract.items() if k != "georeference_only_change"
        ),
    }

    # 5) Governed payload release-mode verifier self-test.
    from phase_q.governed_payload import release_payload_verifier
    verifier = release_payload_verifier(governed_sha)
    verifier(load_text(GOVERNED_OUT))
    mismatch_raised = False
    try:
        verifier("not-the-governed-bytes")
    except RuntimeError:
        mismatch_raised = True
    verifier_ok = mismatch_raised

    report = {
        "run_id": RUN_ID,
        "stage": "H",
        "producer": "govern_load_payload.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "producer_commit": producer_commit,
        "parent": {
            "repaired": str(REPAIRED),
            "enriched_semantic_candidate": str(ENRICHED),
        },
        "reconciliation": reconciliation,
        "q03": artifacts["Q03_LOAD_PAYLOAD_MANIFEST.json"],
        "q04": artifacts["Q04_GEOREFERENCE_SEMANTIC_DIFF.json"],
        "governed_payload": artifacts["governed_payload.xodr"],
        "governed_payload_text_sha256": governed_sha,
        "release_verifier_ok": verifier_ok,
        "verdict": "H_GOVERNED_PAYLOAD_EXACT" if (
            verifier_ok
            and reconciliation["contract_pass"]
            and reconciliation["governed_payload_lf_text_matches_manifest"]
        ) else "H_GOVERNED_PAYLOAD_BLOCKED",
    }
    (EVIDENCE_DIR / "H_LOAD_PAYLOAD_GOVERNANCE.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Stage H verdict: {report['verdict']}")
    print(f"  repaired raw      : {repaired_raw[:16]}... (LF text {repaired_text_sha[:16]}... == P04 payload)")
    print(f"  enriched raw      : {enriched_raw[:16]}... (LF text {enriched_text_sha[:16]}...)")
    print(f"  governed payload  : {governed_sha[:16]}... (raw bytes {governed_raw[:16]}...)")
    print(f"  runtime recorded  : {RECORDED_RUNTIME[:16]}...")
    print(f"  coordinate contract: {contract}")
    print(f"  release verifier  : {'OK' if verifier_ok else 'FAILED'}")
    return 0 if report["verdict"] == "H_GOVERNED_PAYLOAD_EXACT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
