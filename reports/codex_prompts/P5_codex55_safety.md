# PROMPT P5 — CODEX 5.5 — Governance & Artifact-Safety Integration on the Approved Base

> Extracted from `osm_carla_bundle_current_state_adjustments_v4.md` and grounded in the **verified live state**
> of worktree `carla_-main` @ `integration/governed-map-quality-20260729` by Claude Opus 4.8 (P0 session), 2026-07-30.
> **Governance + artifact-safety only. NO map geometry repair, NO Unreal, NO CARLA, NO perception capture.**

## Model / difficulty
- Model: **Codex 5.5** · Difficulty: **8/10**.

## Prerequisite (hard gate)
```
P4 = ARCHITECTURE_APPROVED_FOR_CODEX_55   (from reports/architecture_gate/AG07_verdict)
```
Do **not** run directly after P0 or P3. If P4 is absent/unapproved → verdict `BLOCKED_INVALID_BASE`.

## Base selection
- Use the **exact branch/SHA approved by P4** (expected `integration/governed-map-quality-20260729`, tip ≥ P3 SHA).
- Create an isolated worktree only if that branch is already assigned to another live writer.
- **Acquire the canonical writer lock** via the existing impl:
  `ultimate_pipeline.contracts.writer_lock.WriterLock.acquire(root, branch, head_sha, owner="Codex 5.5", ...)`
  (schema `agent-writer-lock/v1`, path `.agent_locks/writer.lock`). Fail closed on a live conflict → `BLOCKED_CONCURRENT_WRITER`.

## Scope — ONLY these
```
canonical agent-sync enforcement ; governance enforcer ; content-addressed map registry ;
explicit calibration contract ; read-only elevation guard ; artifact transaction framework ;
failure injection ; rollback ; task-ledger reconciliation
```
## Explicitly OUT of scope
```
repair map geometry ; delete roads ; rewrite junctions ; rewrite LaneLinks ; fit elevation ;
import Unreal assets ; cook a map ; run CARLA ; capture perception data
```
`REAL MAP MUTATION AUTHORIZED` must remain **NO** in the final block.

## What already exists — WIRE/COMPLETE, DO NOT REINVENT (verified @ current tip)
- **Artifact framework 8/9 present** in `ultimate_pipeline/artifacts/`: `__init__.py, errors.py, model.py,
  promotion.py, recovery.py, semantic_diff.py, store.py, transaction.py`. **ADD the missing 2:** `hashing.py`
  and `locking.py`. `locking.py` must delegate to the canonical `ultimate_pipeline/contracts/writer_lock.py`
  (do not invent a second lock). Reconcile with `ultimate_pipeline/contracts/artifacts.py`.
- **Canonical lock + schema present:** `contracts/writer_lock.py`, `contracts/agent_sync.py`, plus `agent_sync.yaml`
  (created by P3) with `lock_policy.lock_file == .agent_locks/writer.lock`.
- **Elevation donor guard present:** `ultimate_pipeline/domain_gap/elevation_invariants.py` — **wire to it, do not
  recreate; do not promote the donor elevated map.** (Reference-only siblings: `submission/infrastructure/.../quality/check_elevation_*.py`.)
- **Map-registry reference impl present:** `submission/infrastructure/ultimate_pipeline/carla_tools/map_registry.py`
  — **adapt it into the active tree** (`ultimate_pipeline/carla_tools/map_registry.py`), don't start from zero.
- **Map-identity guard present but name-only:** `ultimate_pipeline/carla_tools/map_identity_guard.py`
  (Town-fallback + substring; NO XODR-SHA). P5 adds the content-hash identity binding via the registry.
- **Governance enforcer ABSENT** → create `ultimate_pipeline/governance/enforce.py`.

## Governance enforcer — `python -m ultimate_pipeline.governance.enforce`
Validate: repository · worktree · branch · allowed ancestry · local/remote equality · writer lock · allowed paths ·
agent_sync schema · canonical CLI (`python -m ultimate_pipeline.cli`) · map registry · map SHA · content family ·
readiness state · configuration hash · evidence root · toolchain profile.

## Content-addressed map registry (use FULL SHA-256, not prefixes)
Register: `AUTO_DOMINIK`, `GRID0821_RAW`, `GRID0828_RAW`, `GRID0821_DERIVED`, `GRID0828_DERIVED`.
- **Reject mislabeled files and ambiguous aliases. Do NOT silently fall back between Grid0821 and Grid0828.**
- Known provenance drift to encode as a rejection test (SHA-16 anchors from the audit; compute full hashes):
  - `carla_main/manual_maps/manual_ingolstadt_grid0828.xodr` → sha16 `5EAECE23…` but content is **Grid0821**
    (993r/119j/5000sig/2553elev) → registry must reject the name↔content mismatch.
  - true **Grid0828** = 972r/119j/4981sig/2507elev (sha16 `A42DDFEA…` / `932D5EF7…`).
  - true **Grid0821** = 993r/119j/5000sig/2553elev (sha16 `69EE3498…` / `67148D18…`).
  - `AUTO_DOMINIK` = 6040r/762j/0sig (sha16 `36F0429C…` / `52938F51…`).

## Calibration contract (directions per agent_sync.yaml)
Implement explicit: `T_camera_from_vehicle`, `T_vehicle_from_camera`, `T_vehicle_from_lidar`, `T_lidar_from_vehicle`,
using the P4-approved basis conversion + units and the agent_sync directions
(`use_K_undistortion=T, ignore_K=T, ignore_D=T, ctv_inverted=F, vtl_inverted=T`).
Add inverse, axis, ground-plane, and reprojection tests.

## Artifact transactions — required properties
`model.py, hashing.py, semantic_diff.py, store.py, transaction.py, promotion.py, recovery.py, locking.py, errors.py`
must together provide: immutable parent · isolated candidate · content+semantic hashes · mutation declaration ·
allowed/forbidden domains · read-only validator · validator input hash · protected metrics · candidate rejection ·
rejected-candidate retention · atomic promotion · manifest recovery · rollback · canonical writer lock.

## Failure injection (synthetic XODR only)
candidate creation failure · serialization failure · validator exception · validator input mutation ·
semantic-diff failure · promotion interruption · manifest corruption · wrong parent hash · lock contention ·
stale lock · rollback after partial promotion.

## Required tests
governance enforcer · map registry · mislabeled-map rejection · calibration · reprojection · elevation guard ·
artifact transaction · failure injection · rollback · **full non-CARLA suite (≥ current 323, 0 failed)** ·
geometry suite · `opendrive_geometry` cross-comparison (must remain PASS).
Run with `UP_DISABLE_CARLA=1` and the repo `.venv`.

## Required outputs
```
reports/codex55_safety/C55_00_identity.md/.json
reports/codex55_safety/C55_01_governance.md/.json
reports/codex55_safety/C55_02_map_registry.md/.json
reports/codex55_safety/C55_03_calibration.md/.json
reports/codex55_safety/C55_04_elevation_guard.md/.json
reports/codex55_safety/C55_05_artifacts.md/.json
reports/codex55_safety/C55_06_failure_injection.md/.json
reports/codex55_safety/C55_07_tests.md/.json
reports/codex55_safety/C55_08_final_status.md/.json
```

## Commit / push discipline
Atomic, narrowly-scoped commits; stage only required source/test/report files; **never** stage `nul`, `vehicle.`,
`.idea/`, `__pycache__/`, `.pytest_cache/`, `external/`, large XODR/datasets, secrets. Push the approved branch;
verify local==remote. Release the lock (or let the lease expire) at the end.

## Verdicts (choose one)
```
GOVERNANCE_AND_ARTIFACT_SAFETY_READY
PARTIAL_INTEGRATION
FAIL_GOVERNANCE
FAIL_MAP_IDENTITY
FAIL_CALIBRATION
FAIL_ARTIFACT_TRANSACTIONS
FAIL_ROLLBACK
FAIL_TESTS
BLOCKED_CONCURRENT_WRITER
BLOCKED_INVALID_BASE
```

## Final status block
```
CODEX 5.5 SAFETY VERDICT:

WORKTREE:
BRANCH:
BASE SHA:
FINAL LOCAL SHA:
FINAL REMOTE SHA:
LOCAL/REMOTE MATCH:

GOVERNANCE ENFORCER:
MAP REGISTRY:
GRID0821 SHA:
GRID0828 SHA:
MISLABELED FILE HANDLING:

CALIBRATION CONTRACT:
REPROJECTION:
ELEVATION GUARD:
DONOR MAP PROMOTED:        (must be NO)

ARTIFACT PACKAGE:
PROMOTION:
ROLLBACK:
VALIDATOR IMMUTABILITY:
FAILURE INJECTION:

FULL OFFLINE TESTS:
GEOMETRY TESTS:
CROSS-COMPARISON:
COMMITS:
PUSHED:

REAL MAP MUTATION AUTHORIZED:   NO
NEXT REQUIRED GATE:             independent artifact-safety review, then a separate structural-map-repair prompt
```
Stop after the safety verdict block. The next task is an **independent artifact-safety review**, followed by a
separate structural-map-repair prompt (P6). Do not begin map repair, Unreal, or CARLA here.
