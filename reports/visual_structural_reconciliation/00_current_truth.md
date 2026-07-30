# 00 — Current Truth (Coordinator)

**Date:** 2026-07-31 · **Coordinator:** Claude Opus 4.8 · **Verified from git, not asserted.**

## Base (writer target after discovery)
- Worktree `carla_-main`, branch `integration/governed-map-quality-20260729`, HEAD `02bdc100`, **local==remote**, tracked tree **clean**.
- Previous writer `P4-REVERIFY-DOCS` **released** with final SHA `02bdc100` → **handoff complete**.
- Prior gate state: AG07 (re-verified @ `02bdc100`) = `REQUIRES_BASE_CORRECTION`; B1 closed; **B2/B3/B4 open**; Codex 5.5 NOT authorized.

## Repo family
One git repo, 10 worktrees (see R00). Governance donor `carla_main_governed` is **dirty** (read-only donor only). RoadRunner donor `carla_rr_recovery`. Junction-snap donor `codex-jsnap-20260428`. Full-pipeline-rerun donor `codex-full-pipeline-rerun-20260427`. Orphaned pointer `carla_governed/` (pruned gitlink).

## Campaign boundary
- `run_11` (+ `08_final_structural_gap.xodr`, `scenario_b_audit/contract_run/`) = **historical evidence only**; user reports unresolved XODR defects → **not** the new structural base. Preserve, never overwrite.
- New campaign **`ingolstadt_cooked_perception_v1`** under `campaigns/ingolstadt_cooked_perception_v1/`: new governed XODR from a verified OSM source, paired with a visual mesh from the **same** source identity + coordinate contract.

## What is NOT yet known (must come from delegated discovery — not fabricated here)
- Authoritative OSM + its sha256/bounds/validity (Claude §11.3, needs DSV02).
- Per-subsystem best donors (DSV01 visual, DSV02 structural).
- Projected CRS / geoReference / header offset / OSM2World projection / Blender+FBX+Unreal units & axes / vertical datum (C44V01).
- Whether existing FBX shares the XODR's OSM source identity → FBX reuse decision (C44V01 → Claude §11.2).

## Hook-evidence caveat
This coordinator process is NOT fresh-session hook evidence (prompt §2). Canonical = `FCH01` (Haiku 4.5 @ `b6c09340`).
