# Repo state sync — 2026-10-07

Scope: honest point-in-time record of this checkout. Nothing in this file
claims work is done unless it is committed on an authoritative branch.
Pending work is labeled PENDING/UNMERGED.

## Baseline (verified `git log` / `git status`, 2026-10-07)

- This document is committed directly on
  `origin/integration/production-large-map-20260918`, introduced by commit
  `67da84bc`. It is not a review-branch document and carries no
  self-referential branch claim; verify placement with
  `git branch --contains 67da84bc`.
- Source checkout HEAD at time of writing: `462f816d`
  (`review/carla-production-convergence-20261002`).
- Authoritative production branch per `AGENTS.md`:
  `integration/production-large-map-20260918`, tip `65eb0f14`
  (`docs(gap-register): record production-tip verification result + GAP-016`).
- `review/carla-production-convergence-20261002` is a review/convergence
  branch, not the production branch. `git diff --stat
  integration/production-large-map-20260918...HEAD` reports ~960 files
  changed — i.e. this review line has diverged massively from production;
  do not treat review-branch commits as production state.

## MERGED (committed on this review branch, not production)

Verified in `git log --oneline -8` on `462f816d`:

- `462f816d` fix(process-control): bind lease owner identity to
  owner-published authority
- `a78c423a` feat(batch16): UE4.26 source authority, SCW build, session
  hardening, import receipt
- `3a8491ec` feat(wave-b): execute RQ1B probe, harden five-run driver,
  reconcile at a7a2a0a2
- `a7a2a0a2` docs(wave-b): record substantive commit rather than
  self-referential SHA
- `0e93ee2a` docs(wave-b): final verdict NOT_PRODUCTION_READY with exact
  blockers
- `76db7320` ci(offline): trigger on review/** and hardening/**, add
  evidence-graph gate
- `89519281` feat(runtime): add PID-owned CARLA shutdown guard
- `5b4169fe` feat(runtime): qualify CARLA/Blender/OSM2World, resolve P0-4,
  classify placement metric

Wave-B verdict on this branch is NOT_PRODUCTION_READY (committed docs).
That verdict stands; this sync doc does not override it.

## PENDING / UNMERGED (do not cite as done)

1. Working-tree modifications — 9 files, uncommitted at time of writing
   (`git diff HEAD --stat`):
   - `tests/unit/test_a1_a2_path_and_frame_resolution.py` (+9:
     OSM2World fallback isolation via empty REPO_ROOT)
   - `tests/unit/test_carla_runtime_load_safety.py` (+128)
   - `tests/unit/test_writer_lock_atomic_publication.py` (+2)
   - `tests/unit/test_writer_lock_concurrency.py` (+3)
   - `ultimate_pipeline/carla_tools/map_runtime_identity.py`
     (fingerprint schema v1 -> v2: typed planView geometry params,
     junction connection/laneLink topology, mismatch reporting)
   - `ultimate_pipeline/config/settings.py` (+1: OSM_FILE fallback to
     `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm`)
   - `ultimate_pipeline/enrichment/blender_runner.py` (+274: generator-stage
     mesh governance — sanitize, normals, per-object box-projection UVs,
     FACE smoothing with 30-degree sharp edges, fail-closed REJECTED path)
   - `ultimate_pipeline/geometry/__init__.py` (+29: re-export mesh_quality gate)
   - `ultimate_pipeline/main_pipeline.py` (+69: FINAL_RUN_VERDICT /
     SUCCESS_MARKER producers)
   - Plus new untracked module `ultimate_pipeline/geometry/mesh_forensics.py`
     / `mesh_quality.py` (untracked, see below).
   Status: PENDING — uncommitted, unreviewed, not on any branch tip.
2. Fingerprint + OSM pytest run — PENDING. The operator reports this run is
   still in progress and will be pushed separately. No PASS is claimed here.
   Treat `map_structural_fingerprint_v2`, the OSM fallback path, and any
   related pytest outcome as UNVERIFIED until that run's output lands.
3. Untracked files — ~200+ paths (`git status --porcelain=v1`), NOT merged:
   root-level audit JSONs (`*_AUDIT.json`, `*_RECEIPT.json`, `GAP026_*`,
   `TOWN10HD_*`, `UE426_*`, etc.), `reports/` subtrees (including
   `reports/production_readiness/20261002/`, `reports/geometry/`,
   `reports/carla_runtime/`, `reports/rq1b_runs/`), `scripts/` diagnostics,
   `tools/` preflight/contract scripts, one-off root scripts
   (`apply_all3_options.py`, `build_lineage.py`, `pass8/9/10/11_*.py`,
   `create_*_data.py`, `execute_phases_1-3.py`), and
   `FINAL_COMPLETION_REPORT.md` (job-market workbook report — unrelated to
   the CARLA pipeline; untracked noise, not repo state).
   Status: UNMERGED — present on disk only, no commit, no review.

## Stale / contradictory docs (known, not silently fixed)

- `README.md:16` pins map-of-record
  `ingolstadt_perception_map_of_record_20260905_202847.xodr`. Registry
  (`ultimate_pipeline/carla_tools/map_registry.py::PINNED_MAP_REGISTRY`),
  `docs/runtime/MAP_OF_RECORD.md`, and `CURRENT_MAP_STATIC_RELEASE_MATRIX.json`
  all pin `ingolstadt_perception_map_of_record_20260916_232831.xodr`
  (SHA `370abbbb...c8c8`, 149799632 bytes). README is STALE on this point;
  the registry + MAP_OF_RECORD.md are authoritative. README was not edited
  in this doc-only sync to avoid mixing a content fix into a state record —
  PENDING a separate README fix.
- RQ4 status conflict: `README.md:22,81` says NOT_CURRENTLY_CITABLE pending
  a leak-free retrain; `docs/research/THESIS_TO_CURRENT_PROGRESS.md`
  (RQ4 row) claims AUTHORITATIVE (leak-free, 2026-09-24, cosine_distance
  mean 0.9207, CI [0.845, 0.976]) with evidence at
  `reports/production_readiness/20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN/`
  (present in this checkout) and
  `reports/production_readiness/20260924T120000Z_RQ1_RQ4_MASTER_CLOSE/`.
  The retrain-evidence paths reference a `G:\gap010-rq4-retrain-20260924`
  worktree for checkpoints, so provenance is worktree-external. Treat RQ4
  as CONTESTED between these two docs until README and the RQ4 evidence
  are reconciled on a production branch — PENDING, not resolved here.
- `docs/index.md` cites baseline `2e020d9b`
  (`review/claude-independent-audit-20260906`) — old pointer, superseded by
  later production-tip history. Informational staleness only.
- `RESULTS.md` (2026-09-24, tracked) reports CARLA 0.9.16 source build
  NOT_FOUND / RPC NOT_RUN / GAP-017 undetermined. That INCOMPLETE verdict
  is the last committed runtime truth; no newer committed runtime receipt
  overrides it in this checkout.

## Map / runtime truth (committed, evidence-backed)

- Auto map-of-record: `..._20260916_232831.xodr` via
  `verify_pinned_map('auto_map_of_record')`; manual reference
  `Grid0828.xodr`. Verify live; do not trust filenames.
- CARLA source runtime: INCOMPLETE (no source checkout/build found;
  packaged `E:\CARLA\CARLA_0.9.16` only; RPC handshake NOT_RUN). Port
  listening alone is not success per `AGENTS.md`.
- RQ posture per committed docs: RQ1 structural AUTHORITATIVE / byte
  BOUNDED; RQ2 BOUNDED (local hull-footprint ~2.7–3.8x); RQ3 DEFERRED
  (runtime blocked); RQ5 DEFERRED; RQ4 CONTESTED as above.

## Documentation & Commit Hygiene

1. Non-aspirational wording only: MERGED means committed on the named
   branch tip; everything else is PENDING/UNMERGED with location
   (working tree, untracked path, external worktree, or unfinished run).
2. No unexecuted command is reported as PASS. Missing evidence is
   NOT_RUN/INCOMPLETE/BLOCKED_EXTERNAL, never a pass.
3. One concern per commit; docs-only sync commits touch `docs/` only and
   never mix code fixes with state records.
4. Doc branches (`docs/*`) are never merged to production by the author;
   they are pushed for review and merged via PR only.
5. Stale pointers are called out with file:line and the authoritative
   source named; stale docs are not silently overwritten in a sync commit.
6. Map identity is resolved via `verify_pinned_map`, never by
   mtime/glob. Frozen `submission/` material is never edited.
7. Every state claim cites its verification command (`git log`,
   `git status --porcelain=v1`, `git diff HEAD --stat`, registry verify).
   This doc's own provenance is commit `67da84bc` on production; do not cite a
   moving HEAD for it.

## What this sync deliberately did NOT do

- No code changes committed; the 9 modified files stay uncommitted.
- No untracked evidence files added to git.
- No README/RQ4/map-pin content fix (recorded as PENDING above instead).
- No merge to any branch other than production, where this document lives.
- No claim about the in-flight fingerprint+OSM pytest run outcome.
