# DSV01 — Visual (OSM2World / Blender / FBX) Donor & Artifact Discovery

**Assigned model:** DeepSeek V4 Light · **Difficulty:** 2/10 · **Mode:** STRICTLY READ-ONLY
**Coordinator:** Claude Opus 4.8 · **Parent campaign:** `ingolstadt_cooked_perception_v1`
**Prereq:** R00 (base clean, previous writer closed) — SATISFIED @ base `02bdc100`.

## Hard rules
- Do NOT edit/merge/cherry-pick/copy/rename/reset/clean/delete anything.
- Do NOT run OSM2World, Blender, Unreal, or CARLA.
- Use **content hashes**, not filenames, for authority (rule 4.4).
- Report only what you can back with a path + command output + hash.

## Search scope (exact worktrees from R00)
Search every worktree below (all share origin `carla-control-suite.git`):
```
carla_-main                                                  (base, 02bdc100)
carla_main_audit                                             (d202ad22)
carla_main_governed                                         (deb261bf, DIRTY - read-only)
carla_main_governed/work/claude-grid0828-review             (b1b6e010)
carla_main_governed/work/codex-full-pipeline-rerun-20260427 (6b250621)
carla_main_governed/work/codex-grid0828-patch               (fe7daad8)
carla_main_governed/work/gemini-governance-normalize        (68ab0caf)
carla_main_governed/work/gemini-grid0828-runtime            (21e8e23a)
carla_main_governed_worktrees/codex-jsnap-20260428          (2b1a3d11)
carla_rr_recovery                                           (25917b18)
```
Also scan reference siblings (read-only): `carla_governed/`, `carla_main/`, `carla_-main_submission_ready/`.

## Find (by name + content)
`osm2world_runner.py`, `blender_runner.py`, `OSM2World.jar`, `*.obj`, `*.mtl`, `*.glb`, `*.gltf`, `*.fbx`,
`visual_manifest*.json`, `asset_manifest*.json`, `osm2world*.log`, `blender*.log`, `conversion*.log`,
`export*.log`, `package.json`, Unreal `*.uproject`/`*.umap`, cook logs.

## Per OSM2World/Blender implementation, record
worktree · branch · SHA · source file · active caller · configured executable · tool version · command ·
input path · **input OSM sha256** · **configuration hash** · output path · **output hash** · exit-code evidence · test evidence.

## Per visual artifact (OBJ/GLB/FBX/…), record
path · worktree · git status (tracked/untracked/ignored) · file size · **sha256** · producer · **input OSM sha256** ·
input configuration hash · object count · triangle/vertex count · material count · texture inventory · bounds ·
coordinate metadata · axis metadata · unit metadata · semantic groups · collision data · LOD data · reimport evidence.

> A nonempty FBX is NOT automatically "working." Classify honestly.

## Classification (per artifact/implementation)
`ARTIFACT_ONLY` · `IMPLEMENTATION_ONLY` · `EXECUTED_UNVERIFIED` · `EXECUTED_WITH_LOGS` ·
`VALIDATED_STATICALLY` · `UNREAL_IMPORTED` · `COOKED_AND_RUNTIME_VERIFIED`.

## Best-donor identification (SEPARATE per subsystem — do NOT pick one global winner)
OSM2World execution · Blender execution · semantic splitting · FBX export · FBX validation · Unreal import.
For each: name the donor worktree + branch + SHA + the exact file(s), and your evidence class.

## Required outputs
- `reports/visual_structural_reconciliation/DSV01_visual_donor_matrix.md`
- `reports/visual_structural_reconciliation/DSV01_visual_donor_matrix.json`

## Verdict line
End with one of: `VISUAL_DONORS_MAPPED` · `VISUAL_ARTIFACTS_FOUND_UNVERIFIED` · `NO_TRUSTWORTHY_VISUAL_SOURCE`.
Do NOT recommend a global merge. Return control to the Claude coordinator.
