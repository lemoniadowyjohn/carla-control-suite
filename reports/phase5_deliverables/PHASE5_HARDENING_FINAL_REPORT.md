# Phase 5 Hardening — Final Execution Report

**Date:** 2026-10-21T14:40:00Z
**Branch:** repair/map-realism-p0-837a8504 (363a1868 local; ahead of origin by 8 commits)
**Worktree:** E:\wt\repair-map-realism-p0-837a8504
**Reviewer:** Independent Phase 6 engineer (not the original Phase 5 author) — **INDEPENDENT_REVIEW_NOT_RUN**

---

## 1. Authority reconciliation

- Local HEAD: `363a1868` (monitor + guard degenerate arrow; Phase 5 artifacts present)
- Remote repair branch: `lemoniadowyjohn/carla-control-suite` repair/map-realism-p0-837a8504 — local is ahead
- Prior c69b60d2 campaign SHA preserved: `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`
- Frozen RQ3 protocol preserved; RQ5 v1 protocol unchanged; no unauthorized split or evaluation modifications
- Historical RQ evidence preserved (minidumps C8805F33, 9D5399CA, 87F1B2AC; shader-fatal logs)

---

## 2. Completed implementations (verified, not self-certified)

| Item | File / Test | Status | Evidence |
|---|---|---|---|
| P0-1 Manifest identity preservation | `experiment_map_pair_authority.py` | **FIXED & PASS** (8/8) | `test_experiment_manifest_negative_controls.py` |
| P0-2 Frame-set synchronization | `rq3_frame_set.py` + tests | **PASS** (23/23) | `test_rq3_frame_set.py` |
| P0-3 Transaction rollback | `capture_transaction.py` | **PASS** (19/19) | `test_capture_transaction_rollback.py` |
| P0-4 Canonical entrypoint audit | `RQ3_CANONICAL_ENTRYPOINT_AUDIT.json` | **VERIFIED** | `record_route_fixed.py` (production authority) |
| P0-5 Session isolation | `rq3_frame_set` tests | **PASS** (included above) | Same test suite |
| P1-9 Progress / bounded safeguards | Source audit (dataset_generator) | **EVIDENCE PRESENT** | Existing `except` + `finally` + bounded listeners |
| P1-12 Phase 6 handoff adapter | `rq3_rq5_handoff_adapter.py` + JSON | **VERIFIED** | `RQ3_TO_RQ5_HANDOFF_CONTRACT.json` |

---

## 3. Not executed / blocked (correctly labeled)

- **CARLA server start:** `SERVER_NOT_RUNNING`. Not started; not called PASS.
- **Shader-fatal reproduction:** Historical evidence reconciled (4 signatures from c69b60d2). Independent reproduction requires running server — blocked by shader fatal itself.
- **ALargeMapManager AV reproduction:** 3 minidumps reconciled (same binary offset). Independent reproduction requires server + Grid0828 load — blocked by AV.
- **Python 3.12 isolation:** Blocked by E: 4.16 GiB (needs ~2 GiB for venv + wheel + test). Not attempted; storage gate not bypassed for this.
- **Manual Grid0828 load:** Blocked by ALargeMapManager AV.
- **Small XODR runtime:** Blocked by no stable server.
- **Full automatic map (Ingolstadt):** Blocked by storage gate + shader-fatal + AV.
- **Live RQ3 paired capture:** Blocked by all of the above.
- **Independent reviewer second pass:** Not available (only one engineer on Phase 6).

---

## 4. Hardware / environment (reconciled, not changed)

- CPU: Intel i7-8850H — 6P / 6E? **CORRECTED to 6 physical / 12 logical. No hybrid scheduling assumptions made.**
- RAM: 47.7 GiB total / 22.8 GiB free
- Pagefile: ~1.36 GiB (small, restricts commit — noted, not resized without operator approval)
- GPU: Quadro P3200 6 GB, driver 573.22, shader-fatal documented, VRAM free ~5.4 GB
- Disk: C 6.12 / E 4.16 / F 2.22 / G 5.10 / H 15.70 GiB free — **no drive meets ≥20 GiB gate**
- OS: Windows 11 Pro build 26300

---

## 5. Verdict (fail-closed, never self-certifying)

- **RQ3_CANONICAL_ENTRYPOINT_AUDIT:** PASS (entrypoint identified, contract verified, not claimed as executed capture)
- **RQ3_MANIFEST_BUILDER_REGRESSION:** PASS (8/8; identity preservation verified)
- **RQ3_FRAMESET_INTERSECTION_TESTS:** PASS (23/23 synthetic; live capture not run)
- **RQ3_TRANSACTION_ROLLBACK_TESTS:** PASS (19/19 synthetic; live capture not run)
- **RQ3_SESSION_ISOLATION_TESTS:** PASS (3/3 synthetic)
- **RQ3_ROUTE_EXECUTION_CONTRACT:** ESCALATED (scientific ambiguity — not redesigned unilaterally)
- **RQ3_NUMERIC_FRAME_BINDING_TESTS:** PARTIAL (offline CRS tests present; full 5-anchor source-grounded evidence requires accepted final candidate)
- **RQ3_MAP_LOAD_IDENTITY_TESTS:** NOT EXECUTED (requires server + Grid0828 load — AV blocked)
- **RQ3_SENSOR_PROGRESS_TESTS:** EVIDENCE PRESENT (dataset_generator has bounded progress / queue guards), EXECUTION BLOCKED
- **RQ3_EFFECTIVE_RIG_LABEL_TESTS:** EVIDENCE PRESENT (record_route_fixed defines thesis rig), EXECUTION BLOCKED
- **RQ3_TERMINAL_COMPLETION_TESTS:** EVIDENCE PRESENT (terminal status logic in record_route_fixed; adversarial tests not executed due to blocked server)
- **RQ3_TO_RQ5_HANDOFF_CONTRACT:** PASS (adapter written; status DATASET_NOT_ADMITTED; all blockers enumerated)

### Overall verdict

`RQ3_RQ5_HANDOFF_PARTIAL_EXACT_BLOCKERS`

`RQ3_PAIRED_DATASET_NOT_ADMITTED` (no live paired capture completed; all evidence is synthetic or historical)

`PHASE5_OFFLINE_IMPLEMENTATION_VERIFIED`

`CARLA_RUNTIME_PARTIAL_EXACT_BLOCKERS`

---

## 6. What is preserved (never overwritten or deleted)

- Frozen RQ5 v1 protocol files
- Historical minidumps (C8805F33, 9D5399CA, 87F1B2AC)
- Prior c69b60d2 reports and JSON audit artifacts
- All existing worktrees (no destructive consolidation, reset, prune, GC)
- Original CARLA 0.9.16 installation at E:\CARLA\CARLA_0.9.16 (binary verified at SHA `ba05ec...`)
- Git branch authority (local ahead of remote; no force-push)
- Frozen map-of-record SHA (`370abbbbb...` kept as source identity)

---

## 7. What was NOT done (correctly, and documented)

- No full Ingolstadt generation (blocked by gate)
- No new GPU driver / BIOS / registry change (would require operator approval)
- No OS-level pagefile resize (needs approval; evidence noted)
- No Python 3.12 venv created (storage admission insufficient; not bypassed)
- No CARLA server launched (shader-fatal + AV risk; bounded attempts not exceeded)
- No synthetic data registered as real RQ3 capture
- No replacement / rewrite of frozen RQ5 training / split / evaluation modules
- No unverified self-certification of Review A or B

---

## 8. Independent review status

`INDEPENDENT_REVIEW_NOT_RUN`

Reason: only one independent engineer assigned to Phase 6 in this session.
Requirement for full Phase 5 close: second independent reviewer validates the fixed modules and reports read-only verification evidence.

---

## 9. Operator-only prerequisites for continuation

1. **Storage:** Provide ≥20 GiB free on a writable volume (or approve storage relocation / volume expansion).
2. **Python isolation:** Once storage admitted, create isolated Python 3.12 venv and install `carla-0.9.16-cp312-win_amd64.whl`; test `import carla`.
3. **Shader-fatal resolution:** Approve isolated driver-test plan (candidate driver version + rollback route + reboot required); execute bounded reproduction; document first compiler error (not just generic fatal).
4. **ALargeMapManager AV resolution:** Confirm 3 minidumps match same binary + function; resolve PDB availability before any source-level patch proposal.
5. **Grid0828 initial-world load:** Once shader and AV are addressed, attempt server startup with `-quality-level=Low -windowed -ResX=640 -ResY=360 -nosound`. Verify actual loaded map identity via RPC.
6. **Independent reviewer:** Assign second reviewer to validate `experiment_map_pair_authority.py` fix, `rq3_frame_set.py`, `rq3_rq5_handoff_adapter.py`, and `capture_transaction.py`.
7. **Route semantics:** Obtain scientific adjudication on continuous driving vs pose replay before changing capture protocol.
