# Ownership, authorization and release gates

## Hard rules
- READ-ONLY first: all agents freeze exact PR HEAD, base, merge-base, status and tracked/untracked `git status` of each worktree before starting.
- OpenCode: may create/change **only** `tests/integration/opencode_v26_ci/`, `tests/integration/opencode_v26_research/`, `tests/integration/opencode_v27_ia/` and new external evidence under an isolated unique directory. Never edit production source, candidate final XODR, existing historical receipts or Codex-owned tests.
- Codex: source changes **only** after the responsible owner claims an exclusive worktree and exactly defined path ownership. A coordinating Codex may create read-only plans and no edits. Collisions are BLOCKED.
- Shared .git: all mutating Git metadata actions serialized under recognized authoritative common-Git lock; if lock implementation is itself suspect, use explicit human-operated single-actor serialization rather than trusting a broken lock.
- Windows named mutex is machine-wide; no fake Linux fallback for live CARLA/UE operations. Store lease owner process creation timestamp, session/run identity, exact resources, operation class and TTL. For real operations, require authoritative native mutex on Windows.
- No force-push, no merge to main/integration, no auto-merge, no live CARLA without explicit scope, no new ML training, no tolerance adjustments, no final-XODR patching, no unsupported PASS.
- AUTH-01...AUTH-10: validate authentic grant source per operation. Unknown or missing AUTH-08 means candidate b publication BLOCKED. Never treat enumeration of authorization IDs as grant evidence.

## Phased acceptance (all independent)
1. STATIC: source/import/risk evidence. Pass only for inspected SHA and appropriate files.
2. OFFLINE_REGRESSION: exact commands actually executed with exit 0, no known unclassified failures, negative controls fail before fixes and pass after.
3. PLATFORM: Windows-native lease, copy-on-write, and CARLA-bound operations tested on an authorized Windows executor; Linux skips don't count.
4. GEOMETRY: source-stage generation, coordinate/CRS, directed lane connectors, linkage continuity, topology witness and deterministic artifacts; no tolerance changes, no post-hoc cosmetic edits.
5. RQ1: actual run entrypoint, repeatable n runs, full provenance, no placeholders, within frozen expected tolerances.
6. RQ2: evidence on real maps / held-out topology and geometry, not only synthetic fixtures.
7. RQ3: independent paired capture artifact existence/digests, sensor/route/map identity, actual captured frame files, split integrity and scientific perception comparison where authorized.
8. RQ4: provenance-locked split de-dup by route/map/time/seed/location/derivative/scene, identical hashes and near-duplicates, graph topology and leakage negative controls.
9. RQ5: full Codex source chain, data/model lineage, frozen split, negative controls, cross-region held-out evaluation, uncertainty and ablation, no training without permission.
10. RUNTIME: actual authorized CARLA RPC result and version/world/map ID/nonce; mere import, socket or fake response is not live proof.
11. EXTERNAL: UE4.26 cook, map import, driving and integration runtime only if explicitly authorized and hardware available; otherwise BLOCKED_EXTERNAL.
12. GOVERNANCE: exact final candidate SHA, immutable receipts, real hosted CI and independent human/Claude review; operator decides merge/release. None of steps 1-11 is independently production approval.

## Evidence statuses
Use precisely PASS, FAIL, NOT_EXECUTED, BLOCKED_ENV, BLOCKED_AUTH, BLOCKED_EXTERNAL, PARTIAL, INCOMPLETE, REQUIRES_CHANGES. Never map missing/skip/xfailed to PASS. Always separate `schema_valid` from `scientifically_admitted`. Keep negative-control expected failures distinct from regressions.

## Known specialist worktrees (unverified reported paths)
- T2b `E:/wt/prod_68868f76` — Codex
- F15b `F:/wt-gap055-base` — Codex
- W-F `E:/wt/research-gap070-reversed-stubs-20261104` — specialist
- W-B `F:/carla-worktrees/rq5-sightb-20261009` — Codex
- W-D pending integration owner, 26 original test selection unknown
- candidate b AUTH-08 pending
These are *reported*, not verified handles. Every worker must first discover actual `git worktree list --porcelain` and all lock/process states, then reconcile branch tip SHA. If the filesystem changes or identity diverges, STOP.
