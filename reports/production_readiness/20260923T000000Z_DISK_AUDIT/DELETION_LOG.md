# Disk reclamation — deletion log

Executed 2026-09-23 by the coordinator, following review of
`CANDIDATES.md` (Codex audit, commit `da7e02ac`) and explicit user
confirmation of the "preserve small evidence, delete large binaries"
approach.

## Verification performed before deletion

- Current governed map-of-record: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr`,
  149,799,632 bytes, sha256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`
  (confirmed on disk, matches the session's pinned record).
- Listed the full contents of `campaigns/ingolstadt_cooked_perception_v1/regen/`
  directly: exactly the 18 directories Codex's audit flagged, newest dated
  `20260905T195239Z` — 10+ days older than the current map-of-record's
  generation timestamp (`20260916_232831`). No later regen run exists that
  could be the current pin's source.
- No `final_artifact_receipt.json` exists anywhere in the repo (the new
  receipt-authority system postdates all 18 of these runs), so there is no
  receipt-based provenance chain pointing into any of them either.

## What was preserved

Every file `<=1MiB` from each of the 18 regen directories was copied,
preserving relative path, to
`reports/production_readiness/preserved_regen_evidence/<run_id>/` before
deletion. This captures all the named summary/report/audit JSON files
(`audit_summary.json`, `continuity_stability.json`, `bbox.json`,
`crs_comparability.json`, `rebase_report.json`, `carla_compat_report.json`,
`carla_reachability.json`, `continuity_debug.json`, `*.qa.json`,
`*_lane_connectivity_report.json`, etc.) while excluding a small number of
disproportionately large per-run data dumps that are not curated evidence
(`stage6_containment_runtime.json` at 647.8MiB each x15 instances,
`strict_xodr_validation.json` at ~53MiB each, `cumulative_gate_report.json`
up to 78MiB in the two EXPERIMENTAL runs) — these are raw bulk data, not
summaries, and their absence does not remove any documented finding.

Total preserved: 2.29 GiB (9,127 files) under `reports/production_readiness/
preserved_regen_evidence/`.

## What was deleted

All 18 directories under `campaigns/ingolstadt_cooked_perception_v1/regen/`,
in full, after the preservation step above:

| Run ID | Original size |
|---|---:|
| 20260817T202220Z | 1.43 GiB |
| 20260817T211027Z | 2.11 GiB |
| 20260817T221616Z | 3.42 GiB |
| 20260817T234901Z | 0.16 GiB |
| 20260819T142310Z | 3.41 GiB |
| 20260819T150903Z | 3.41 GiB |
| 20260819T153954Z | 3.41 GiB |
| 20260827T135439Z_EXPERIMENTAL_heading_smoothing | 2.94 GiB |
| 20260902T124414Z_EXPERIMENTAL_heading_smoothing_v2_recompute | 2.88 GiB |
| 20260902T151513Z | 3.95 GiB |
| 20260904T193213Z | 3.45 GiB |
| 20260904T203247Z | 1.72 GiB |
| 20260904T210614Z | 3.59 GiB |
| 20260905T115232Z | 1.45 GiB |
| 20260905T124135Z | 3.59 GiB |
| 20260905T152438Z | 3.59 GiB |
| 20260905T173020Z | 3.59 GiB |
| 20260905T195239Z | 3.59 GiB |
| **Total** | **51.72 GiB** |

Net reclaimed on C: (regen dirs only): **49.43 GiB**.

Also removed, per the audit's other findings (all clearly rebuildable,
no evidence value):
- `build/lib` at repo root (C:) and at
  `F:\carla-control-suite-worktrees\runtime-tile-subset-v1-20260914\build\lib`.
- `__pycache__` and `.pytest_cache` trees across C: (full repo) and the
  top-level of registered F: worktrees.

The 414 duplicate `*_TILE_BASED_FBX_GENERATION_PROBE` directories and the
16 probe replicas without a summary JSON were **not** touched this pass —
Codex's audit correctly flagged the latter as unsafe to delete without a
replacement summary, and the former (203 MiB total) is low-value enough to
defer to a future pass rather than rush.

## Result

C: went from 98% used (~11-24GiB free, depending on measurement time) to
**85% used, 74GiB free**. F: remains critical (741MiB free) — this pass
only removed trivial caches there; F:'s real constraint is the number of
active worktrees it hosts, a separate decision not in scope for this audit.
