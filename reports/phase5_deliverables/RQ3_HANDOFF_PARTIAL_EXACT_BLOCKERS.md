RQ3 HANDOFF — FINAL VERDICT
============================
Implementation SHA tested: 9e777a270f91299bd20efcc879919029e2956e45 (short: 9e777a27)
Receipt SHA (this document): will be assigned at commit time (separate from implementation SHA to avoid self-reference).

VERDICT: RQ3_HANDOFF_PARTIAL_EXACT_BLOCKERS

NOT READY FOR PRODUCTION MERGE.
Not self-certified as independent-verified.
Real paired dataset remains: RQ3_PAIRED_DATASET_NOT_ADMITTED.

BLOCKERS (preserved, not masked):
- INDEPENDENT_REVIEW_NOT_RUN: Only one engineer executed; no external Codex reviewer executed the final SHA.
- CARLA_SERVER_STARTUP: Blocked (shader-fatal + ALargeMapManager AV + storage gate); no runtime capture qualified.
- RQ3_PAIRED_DATASET_NOT_ADMITTED: Actual paired Ingolstadt runtime capture not completed; dataset admission requires verified live-capture artifacts + independent review approval.
- Some pre-existing unrelated contract/import failures remain in the wider regression suite (18 failures out of 130 targeted). These are not masked by this remediation.

FIXES COMMITTED AT SHA 9e777a27:
1. Strict CLI dispatch (record_route_fixed.py): main() routes --strict-rq3 explicitly to run_strict_capture_entrypoint; no silent legacy capture; __main__ guard at file end after definitions.
2. Synthetic-to-authoritative promotion eliminated (rq3_evidence_gate.py): separate structural/synthetic/real-capture/dataset-admission/evidence-authority states; synthetic fixtures pass structural checks but claim stays SYNTHETIC_TEST_ONLY.
3. Manifest promotion repaired (experiment_map_pair_authority.py): derived pair_valid computed from evidence predicates, not caller flag; strict validator applied to derived candidate; claim downgraded to CLAIM_UNPAIRED_CAPTURE when invalid.
4. Artifact byte verification (rq3_evidence_gate.py + tests): verifies file bytes (sha256 of content), rejects traversal, stale session id, uncommitted staging, duplicate identity with different content, truncated/modified files; verifies rgb/semantic/lidar members.
5. Frozen protocol authority recovered (configs/rq3_protocol_freeze_v1.json, SHA-256 5aa8ae2...): tracked, unedited, included in reproducible source lineage.
6. Reproducible environment (C:\temp\py312_venv): Python 3.12.2, pytest 9.1.1 installed; exact interpreter used for regression; editable package present.
7. All required RQ3 modules tracked: rq3_evidence_gate, rq3_frame_set, rq3_rq5_handoff_adapter, capture_transaction, experiment_map_pair_authority (edited), rq3_capture_contract (existing tracked, preserved; claim downgrade logic confirmed).
8. Targeted regression executed: 112 PASS / 18 FAIL (core RQ3 artifact/strict/gate tests pass; failures are pre-existing unrelated contract/import errors, not regression from this fix).

ROUTES ENFORCING NON-PROMOTION (tested offline):
- Helper API (rq3_evidence_gate.evaluate_strict_evidence): synthetic=True -> claim SYNTHETIC_TEST_ONLY, authoritative False.
- Manifest builder (create_experiment_manifest): complete synthetic-shaped fixture passes structural checks; claim stays CLAIM_UNPAIRED_CAPTURE; derived pair_valid requires complete evidence; false caller pair_valid ignored.
- Strict CLI (--strict-rq3): routes to strict entrypoint; authoritative requires live_capture=True + independent_review_status==APPROVED + verified artifacts + terminal COMPLETED.
- Dataset handoff adapter (rq3_rq5_handoff_adapter): uses strict evidence verdict; synthetic fixtures never promoted.

EVIDENCE RECEIPTS:
- RQ3_EVIDENCE_RECEIPT_20261022_9e777a27.json (bound to 9e777a27)
- RQ3_PATCH_MANIFEST.json (updated in reports/)
- RQ3_INDEPENDENT_REVIEW_REQUEST.md (request for Codex re-review of 9e777a27)

REQUIRED NEXT MOVES (NOT EXECUTED HERE):
1. Independent Codex review of exact SHA 9e777a27 + evidence receipts.
2. Live CARLA server startup (resolve shader + ALargeMapManager + storage gate) before paired dataset admission.
3. Independent review approval of dataset content after verified runtime capture completes.
4. Only after (1)-(3) can claim transition from SYNTHETIC_TEST_ONLY / UNPAIRED_CAPTURE to EXPERIMENTAL_EVIDENCE_AUTHORITATIVE / PAIRED_INGOLSTADT_CAPTURE.

No full CARLA server started. No RQ5 file changed. No synthetic promoted to real. No force push performed. Branch preserved.
