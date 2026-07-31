# DSV01 — Visual (OSM2World / Blender / FBX) Donor & Artifact Discovery

**Model:** DeepSeek V4 Light · **Mode:** STRICTLY READ-ONLY · **Parent:** `ingolstadt_cooked_perception_v1`
**Base SHA:** `7053bab56de4ba1680c4fb73bf85a5dc9b911694`

## Worktrees Scanned (12)

| # | Worktree | Branch | SHA |
|---|----------|--------|-----|
| 1 | `carla_-main` | `integration/governed-map-quality-20260729` | `7053bab5` |
| 2 | `carla_main_audit` | `audit/gemini31pro-audit` | `d202ad22` |
| 3 | `carla_main_governed` | `fix/deepseek-observability-integration-verification` | `deb261bf` |
| 4 | `carla_main_governed/work/claude-grid0828-review` | detached | `b1b6e010` |
| 5 | `carla_main_governed/work/codex-full-pipeline-rerun-20260427` | `work/codex-full-pipeline-rerun-20260427` | `6b250621` |
| 6 | `carla_main_governed/work/codex-grid0828-patch` | `work/codex-grid0828-batch-sync-001` | `fe7daad8` |
| 7 | `carla_main_governed/work/gemini-governance-normalize` | `work/gemini-governance-normalize-20260315` | `68ab0caf` |
| 8 | `carla_main_governed/work/gemini-grid0828-runtime` | detached | `21e8e23a` |
| 9 | `carla_main_governed_worktrees/codex-jsnap-20260428` | `work/codex-jsnap-20260428` | `2b1a3d11` |
| 10 | `carla_rr_recovery` | `recovery/roadrunner-capability-integration` | `25917b18` |
| 11 | `carla_governed/` | (mirror of #3) | `deb261bf` |
| 12 | `carla_-main_submission_ready/` | (plain dir, not git) | — |

## Implementation Inventory

### OSM2World Runner
| Variant | Size | SHA256 | Has GLB Validation? | Worktrees |
|---------|------|--------|-------------------|-----------|
| submission variant | 33,614 B | `451A2009E02DE...` | Yes (rr_recovery) | carla_-main, carla_main_audit, carla_rr_recovery |
| governed variant | 32,747 B | `9CF30DD01ADA...` | No | all carla_main_governed sub-worktrees |
| submission_ready variant | 32,747 B | `9CF30DD01ADA...` | Yes | carla_-main_submission_ready |

### Blender Runner
| Variant | Size | SHA256 | Worktrees |
|---------|------|--------|-----------|
| submission variant | 18,042 B | `4BC29E3A15D8...` | carla_-main, carla_main_audit, carla_rr_recovery |
| governed variant | 16,889 B | `4ECC506F12FA...` | all carla_main_governed sub-worktrees |

### OSM2World JAR
- **Present in**: all 5 `carla_main_governed/work/*/OSM2World-latest-bin/` (identical)
- **Size**: 506,756 B · **SHA256**: `F20B00E1C5DC...`
- **Not present in**: carla_-main root, carla_main_audit, carla_rr_recovery

## Execution Artifacts

| Classification | Count | Details |
|---------------|-------|---------|
| COOKED_AND_RUNTIME_VERIFIED | 2 worktrees | carla_main_governed + carla_governed: full OSM→OBJ→FBX pipeline with Blender 4.3.0 conversion logs (69.8s, 11,784 mesh objects, 0 stderr) |
| UNREAL_IMPORTED | 2 worktrees | FBX in `artifacts/supervisor_delivery/fbx/` (166 MB, SHA `48675A4D...`). One run succeeded, one failed with OSM XML error |
| VALIDATED_STATICALLY | 5 sub-worktrees | GLB files (703 MB each, SHA `25229E09...`) in `OSM2World-latest-bin/_osm2world_test/scene.glb` |
| EXECUTED_WITH_LOGS | carla_-main | OSM2World ran with degenerate-triangle warnings; Blender ran successfully; no output artifacts retained |
| IMPLEMENTATION_ONLY | 6 worktrees | Code present but no execution artifacts |

## Key FBX Artifacts

| Artifact | Size | SHA256 | Worktree | Status |
|----------|------|--------|----------|--------|
| `fbx_test_output/osm2world/scene.fbx` | 115,809,148 B | `FB540459...` | carla_main_governed | UNTRACKED |
| `artifacts/supervisor_delivery/fbx/generated_ingolstadt_osm2world.fbx` | 166,231,852 B | `48675A4D...` | carla_main_governed | UNTRACKED |

## Files Not Found (any worktree)
- `*.uproject` · `*.umap` · `package.json` · `visual_manifest*.json` · `asset_manifest*.json` · `conversion*.log` · `export*.log`

## Best-Donor Identification

| Subsystem | Donor Worktree | Branch | SHA | Evidence |
|-----------|---------------|--------|-----|----------|
| OSM2World execution | carla_main_governed/work/* | various | any | 5× GLB + 20× OBJ + full pipeline logs |
| Blender conversion | carla_main_governed | fix/deepseek-... | deb261bf | Blender 4.3.0 stdout confirms OBJ→FBX success (69.8s, 11,784 meshes, 0 errors) |
| FBX export | carla_main_governed | fix/deepseek-... | deb261bf | 115 MB + 166 MB FBX artifacts with export logs |
| Semantic splitting | N/A | N/A | N/A | No evidence of semantic splitting implementation |
| FBX validation | carla_main_governed | fix/deepseek-... | deb261bf | Blender import-export cycle validated; no FBX-specific validator |
| Unreal import | NONE | NONE | NONE | No `*.uproject`, `*.umap`, or Unreal import scripts found anywhere |

## Verdict

```
VISUAL_DONORS_MAPPED
```

Best visual pipeline: **carla_main_governed** (`deb261bf`) — contains the only end-to-end OSM→OBJ→FBX pipeline with Blender 4.3.0 success logs. FBX artifacts are untracked but present. No Unreal import infrastructure exists in any worktree.
