# PROMPT P4 — CLAUDE OPUS 4.8 — Fresh Independent Architecture Gate

> Drafted by Claude Opus 4.8 (the P0 session) on 2026-07-30, grounded in the **verified live state** of
> worktree `carla_-main` @ `integration/governed-map-quality-20260729`.
> Concretizes P4 from `osm_carla_bundle_current_state_adjustments_v4.md`.

## Process rule (mandatory)
- Run in a **NEW Claude Opus 4.8 process**. **Do NOT use the session that performed P0** (this drafting session).
- **Strictly read-only.** No source repair. No commits. No writer lock. No map mutation. No Unreal/CARLA execution.

## Model / difficulty
- Model: **Claude Opus 4.8** · Difficulty: **8/10**.

## Prerequisites (verify before starting; else return the matching BLOCKED verdict)
```
P0 = INTEGRATION_BRANCH_PUSHED_GREEN        (met: CC01–CC05 @ 42f7b77c)
P2 = FRESH_SESSION_HOOKS_PASS               (from reports/fresh_claude_hook_test/FCH01_*)
P3 = BASE_READY_FOR_ARCHITECTURE_GATE       (from reports/base_closure/BC06_*)
```
If P2 or P3 is missing/failed → do not proceed; return `REQUIRES_BASE_CORRECTION` or `FAIL_HOOK_GOVERNANCE`.

## Pinned base
```
REPOSITORY : C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
BRANCH     : integration/governed-map-quality-20260729   (current pushed tip == P3 final SHA; >= 992e50b6)
```
Confirm `git rev-parse HEAD == git rev-parse origin/<branch>` before trusting any input report.

## Verified architecture anchors (confirm, then classify — do not assume)
- **Geometry authority present:** `opendrive_geometry/` (canonical OpenDRIVE primitive math + cross-compare).
- **Pipeline subsystems present:** `ultimate_pipeline/{osm,carla_tools,perception,tiling}`.
- **No Unreal/cooked tree in this worktree:** `Unreal/`, `carla/`, `Import/`, `Content/` are ABSENT here →
  current path is almost certainly **runtime-XODR**, not a cooked loadable map. Confirm.
- **CARLA install exists:** `E:\CARLA\CARLA_0.9.16` (→ CARLA 0.9.16 / UE4.26 toolchain). Verify exact tag/commit.
- **Reference maps live in SIBLING worktrees, not integrated here:** RoadRunner-class Grid0821/Grid0828
  (~62–63 MB, signal-rich, elevated). **Known provenance drift:** a file named `manual_ingolstadt_grid0828.xodr`
  in `carla_main/manual_maps` actually contains **Grid0821** content (993r/5000sig) vs the true Grid0828
  (972r/4981sig). This must inform the reference-map ROLE decision (registry disambiguation is P5's job, not P4's).
- **INPUT_XODR/authoritative-map ambiguity:** every configured XODR input/output path in `settings.py` was
  previously missing/empty/wrong-worktree (see `reports/read_only_map_readiness_audit/.../15_audit_gap_005_verification.md`).
  Determine what P3 base-closure changed, and whether an authoritative XODR is now pinned.

## Read-only inputs
```
complete v2 prompt bundle (F:\pulpit\osm_carla_prompt_bundle\osm_carla_prompt_bundle\*)
reports/current_claude_completion/        (P0)
reports/delta_base_verification/          (P1: DV01–DV04)
reports/fresh_claude_hook_test/           (P2: FCH01)
reports/base_closure/                     (P3: BC01–BC06)
AGENT_TASK_LEDGER.md, reports/CODEX_FIX_PROMPTS.md, agent_sync.yaml
ultimate_pipeline/** (active pipeline source), opendrive_geometry/**
reports/read_only_map_readiness_audit/**  (prior 00–16 audit + AUDIT-GAP-005)
```
**Do not assume file presence means completion.** Verify claims against current source/SHA.

## Objectives
1. Verify the current authority chain (branch/SHA/upstream/lock/agent_sync/ledger consistency).
2. Confirm the exact pending-prompt statuses (P0–P3 actual, not asserted).
3. Classify the **current** architecture.
4. Select the **target** architecture.
5. Parameterize the Unreal cooking prompt (do NOT execute it).
6. Produce a **binding implementation contract for Codex 5.5** (the P5 scope).

## Current architecture classification (return exactly one)
```
A_RUNTIME_XODR_ONLY
B_RUNTIME_XODR_WITH_PROXY_ENRICHMENT
C_SUPPLEMENTARY_OSM2WORLD_BLENDER_NOT_INTEGRATED
D_PARTIAL_UNREAL_CUSTOM_MAP
E_COOKED_LOADABLE_CUSTOM_MAP
F_ROADRUNNER_AUTHORITATIVE_MAP
G_MULTIPLE_CONFLICTING_PATHS
```

## Mandatory architecture decisions (pin every one; "UNKNOWN → must-resolve" is allowed but must be flagged)
```
CARLA repository / branch-or-tag / commit      (anchor: 0.9.16 at E:\CARLA\CARLA_0.9.16)
Unreal version / commit                        (anchor: UE4.26)
PythonAPI version
build system ; native or Docker ; host support
visible-road authority ; OSM2World role ; Blender role
authoritative XODR ; authoritative FBX/visual input
coordinate transform ; vertical transform
manual/reference map role (Grid0821 vs Grid0828 — role only; registry is P5)
monolithic or tiled ; tile-size experiment ; semantic partition strategy
traffic-light/sign strategy ; collision strategy ; navigation strategy
runtime session owner (note: ultimate_pipeline/carla_tools/session.py + map_identity_guard exist)
sensor calibration contract (agent_sync.yaml: use_K_undistortion=T, ignore_K=T, ignore_D=T,
                             ctv_inverted=F, vtl_inverted=T)
dataset identity contract
```
**Do NOT mix** UE4.26 legacy import / UE5.5 CMake / legacy large-map tiles / UE5 World Partition without direct
branch support. If the repo mixes them → classify `G_MULTIPLE_CONFLICTING_PATHS` and require a decision.

## Unreal prompt parameterization
Create `reports/architecture_gate/UNREAL_COOKING_PARAMETERS.md` specifying, section-by-section, which parts of
`05_UNREAL_ENGINE_ASSET_COOKING_PROMPT.md` **apply / are disabled / need repo-specific replacement**, with the
approved exact CARLA & UE values substituted for every generic branch choice. **Do not execute the cooking prompt.**

## Thesis boundary (state explicitly)
```
historical thesis evidence            (what already stands and must not be retro-upgraded)
new cooked-map campaign               (what a future cook would add)
reference-map role                    (Grid0821/0828 as evaluation reference vs production input)
claims that cannot be retroactively upgraded
```

## Required outputs
```
reports/architecture_gate/AG01_authority_chain.md/.json
reports/architecture_gate/AG02_current_architecture.md/.json
reports/architecture_gate/AG03_target_architecture.md/.json
reports/architecture_gate/AG04_coordinate_contract.md/.json
reports/architecture_gate/AG05_unreal_parameters.md/.json      (+ UNREAL_COOKING_PARAMETERS.md)
reports/architecture_gate/AG06_implementation_contract.md/.json  (binding contract for Codex 5.5 / P5)
reports/architecture_gate/AG07_verdict.md/.json
```
(These are read-only *analysis* artifacts; a fresh read-only session may write under `reports/` without a writer
lock, since it mutates no source/map. If your governance requires a lock even for reports, acquire a read-only
lease and note it.)

## Verdicts (choose one)
```
ARCHITECTURE_APPROVED_FOR_CODEX_55
REQUIRES_BASE_CORRECTION
REQUIRES_ARCHITECTURE_DECISION
BLOCKED_MISSING_INPUTS
BLOCKED_TOOLCHAIN
FAIL_HOOK_GOVERNANCE
```

## Final status block
```
CLAUDE ARCHITECTURE VERDICT:

REPOSITORY:
WORKTREE:
BRANCH:
SHA:
CURRENT ARCHITECTURE:
TARGET ARCHITECTURE:

CARLA BRANCH:
CARLA COMMIT:
UNREAL VERSION:
UNREAL COMMIT:
BUILD WORKFLOW:

AUTHORITATIVE XODR:
AUTHORITATIVE VISUAL INPUT:
VISIBLE ROAD SOURCE:
OSM2WORLD ROLE:
BLENDER ROLE:
TILING:
COORDINATE CONTRACT:
VERTICAL CONTRACT:

SEMANTIC STRATEGY:
COLLISION STRATEGY:
NAVIGATION STRATEGY:
TRAFFIC CONTROL STRATEGY:
SESSION OWNER:
SENSOR CONTRACT:

UNREAL PROMPT READY:
CODEX 5.5 AUTHORIZED:
BLOCKERS:
```
Stop after the architecture verdict block. Do not begin P5, Unreal, or CARLA.
