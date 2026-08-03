# 00_CURRENT_REPOSITORY_STATE.md

**Generated:** 2026-08-02
**Coordinator:** Prompt 01 — Campaign Coordinator
**Mode:** Plan (reports only; no fixes in this prompt)

## Identity

| Field | Value |
|---|---|
| Repo root | `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main` |
| Current branch | `integration/governed-map-quality-20260729` |
| HEAD | `e9ff598653bb95775eb4c12c82ba0ca084e83233` |
| Audited commit (LOW_COST_MODEL_AUDIT_20260801) | `dac6930a7de1698c4b2a1fe4cfb6deb7f2679fe2` |
| Delta from audited commit | +2 commits (572f25e9, e9ff5986 — Phase A audit normalization) |
| Upstream | `origin/integration/governed-map-quality-20260729` — local ahead 2 |

## Dirty state (main worktree)

- Modified tracked files (3):
  - `submission/infrastructure/ultimate_pipeline/pipeline_stages/stage_08_final_integrity.py` (1 line)
  - `submission/infrastructure/ultimate_pipeline/pipeline_stages/stage_08_integrity.py` (1 line)
  - `ultimate_pipeline/run_full_domain_gap.py` (7,466-line runner, heavily rewritten vs tracked 84-file subset)
- Untracked (selected, NOT committed to git):
  - `audit_output/` (22 files incl. `raport.md` 756 KB), `audit_output.zip` (519,751 B)
  - `ultimate_pipeline/` — ~509 untracked .py files (only 84 root package files are git-tracked)
  - `campaigns/ingolstadt_cooked_perception_v1/candidate/verify_final_xodr_report.json`
  - `generate_audit.py`, `create_a1_registries.py`, `phase_a_normalize.py` (the last two committed)
  - `carla_governed/` (OSM2World-latest-bin, scenario_runner, MCP server), `external/` (blender-driving-scenario-creator, esmini, scenario_runner-master, synth-it-like-kitti-main)
  - `reports/C01_carla_runtime_audit.{json,md}`, `reports/R01_final_integration_gate.md`
  - `reports/claude_independent_governance_review/`, `reports/codex55_safety/`, `reports/deepseek_governance_inventory/`, `reports/delta_base_verification/`, `reports/source_visual_closure/`
  - `.githooks/`, `.idea/`, `nul`, `vehicle.`, `work/`, `worktrees/`

## Tool availability (verified this session)

| Tool | State |
|---|---|
| Python | 3.12.2 (`python`, not `python3`) |
| pytest | 9.0.1 |
| numpy | 2.2.6 |
| lxml | available |
| CARLA wheel | importable from `.venv` (0.9.16); **no CARLA server** (port 2000 refused in audit) |
| Blender | NOT found on PATH → O2W/BLD runtime checks BLOCKED |
| OSM2World | present under `carla_governed/OSM2World-latest-bin` (unversioned) |
| git-lfs | tracked XODR/OSM; hashes verified against manifest (b9e07465…, ff2a05e7…) |

## Phase A state (committed)

- `572f25e9` — Phase A2 status logic sample
- `e9ff5986` — full Phase A: registry 232 IDs (218 formal + 14 issue), strict status logic (PASS 45→6), per-profile release effects (all 5 profiles BLOCKED), manifest hash verification (32 entries, 1 finding: stale claim for 07_BLOCKING_ISSUES.md), acceptance ACCEPTED_WITH_FINDINGS
- Evidence dir: `reports/post_audit_hardening/20260801T221042Z/`

## Key structural facts (drive SYS-001)

- Root package `ultimate_pipeline/`: 593 .py on disk, **84 tracked** in git (509 untracked)
- Donor package `submission/infrastructure/ultimate_pipeline/`: 582 .py on disk, **688 tracked** (fully versioned)
- Root import of `ultimate_pipeline.main_pipeline` FAILS: 8 unresolved internal module references (see 03_CANONICAL_TREE work)
- `submission/infrastructure/ultimate_pipeline/bootstrap_repo_root.py` exists; root copy exists but lacks docs

## Blockers before build (summary)

1. SYS-001 unresolved: two production package trees, root not importable, root mostly uncommitted
2. Blender unavailable (BLOCKED for O2W-BLD execution, but validator tooling is implementable)
3. No CARLA server (BLOCKED for runtime/perception execution; offline-only claims allowed)
4. Audit manifest stale for one artifact (recorded, authoritative files untouched)
