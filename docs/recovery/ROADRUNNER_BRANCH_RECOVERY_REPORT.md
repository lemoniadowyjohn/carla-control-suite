# RoadRunner Branch Recovery Report

## AUTHORITATIVE_REPOSITORY
https://github.com/lemoniadowyjohn/carla-control-suite.git

## IMPLEMENTATION_BRANCH
deepseek-observability-integration-verification

## BASE_SHA
db0d983a34209e0a47628d3c2b48efc3f9327ec4

## LOCAL_REMOTE_MATCH
true (local=db0d983a, remote=db0d983a)

## BRANCHES_EXPECTED
8

## BRANCHES_MISSING_LOCAL_AND_REMOTE
5/8

## BRANCHES_EMPTY (local, zero unique commits)
3/8

## BRANCHES_WITH_UNIQUE_COMMITS
0/8

## UNPUBLISHED_BRANCHES
3 (local only, never pushed)

## Detailed Branch Inventory

| Branch | Local | Remote | Unique Commits | Status |
|--------|-------|--------|---------------|--------|
| rr-gap-analysis-gemini35 | NO | NO | 0 | MISSING_LOCAL_AND_REMOTE |
| rr-contracts-gpt55 | YES | NO | 0 (behind base SHA) | LOCAL_ONLY_EMPTY |
| rr-docs-profiles-gemini31 | NO | NO | 0 | MISSING_LOCAL_AND_REMOTE |
| rr-automation-ling | NO | NO | 0 | MISSING_LOCAL_AND_REMOTE |
| rr-roundtrip-laguna | NO | NO | 0 | MISSING_LOCAL_AND_REMOTE |
| rr-tests-north | YES | NO | 0 (behind base SHA) | LOCAL_ONLY_EMPTY |
| rr-adversarial-nemotron | YES | NO | 0 (behind base SHA) | LOCAL_ONLY_EMPTY |
| rr-visual-mimo | NO | NO | 0 | MISSING_LOCAL_AND_REMOTE |

All 3 local rr-* branches point to a12fe9ba (BEHIND authoritative base db0d983a).  
The base has advanced 5 commits beyond where rr-* branches were created.  
No branch has any divergent or unique work.

## WORKTREES_WITH_CHANGES
0
No RoadRunner-related changes found in any worktree.

## STASHES_WITH_RELEVANT_WORK
0
- stash@{0} (fix/elevation-and-final-quality-gate-closure): no RoadRunner files
- stash@{2} (fix/verification-and-roadrunner-quality-closure): branch name contains "roadrunner" but its content does not contain RoadRunner implementation files

## REFLOG_COMMITS_RECOVERABLE
0
All reflog entries referencing "rr-" are branch-creation events only.  
No RoadRunner implementation commits found in reflog.

## PROHIBITED_FILE_TOUCHES
0 (no changes exist)

## FILES_ALREADY_PRESENT (untracked, on current worktree)
The following RoadRunner files exist untracked in the working tree.
They were NOT committed to any branch and may be from earlier work:

### Core implementation files (with content)
- ultimate_pipeline/roadrunner/__init__.py (5033 bytes)
- ultimate_pipeline/roadrunner/alignment.py
- ultimate_pipeline/roadrunner/capability_probe.py
- ultimate_pipeline/roadrunner/exceptions.py
- ultimate_pipeline/roadrunner/export_inventory.py
- ultimate_pipeline/roadrunner/gate_matrix.py
- ultimate_pipeline/roadrunner/grpc_runner.py
- ultimate_pipeline/roadrunner/installation.py
- ultimate_pipeline/roadrunner/manifest.py
- ultimate_pipeline/roadrunner/matlab_runner.py
- ultimate_pipeline/roadrunner/mesh_manifest.py
- ultimate_pipeline/roadrunner/models.py
- ultimate_pipeline/roadrunner/package_manifest.py
- ultimate_pipeline/roadrunner/process_runner.py
- ultimate_pipeline/roadrunner/semantic_manifest.py
- ultimate_pipeline/roadrunner/source_contract.py
- ultimate_pipeline/roadrunner/validation.py

### Tools
- tools/roadrunner/build_carla_import_manifest.py
- tools/roadrunner/generate_grpc_bindings.py
- tools/roadrunner/inventory_export.py
- tools/roadrunner/probe_roadrunner.py
- tools/roadrunner/validate_mesh_xodr_alignment.py
- tools/roadrunner/validate_roundtrip.py

### MATLAB scripts
- matlab/roadrunner/rr_close_all.m
- matlab/roadrunner/rr_export_fbx_xodr.m
- matlab/roadrunner/rr_export_tiled.m
- matlab/roadrunner/rr_export_xodr.m
- matlab/roadrunner/rr_import_xodr.m
- matlab/roadrunner/rr_probe.m

### Schemas
- schemas/roadrunner/capability.schema.json
- schemas/roadrunner/export_inventory.schema.json
- schemas/roadrunner/gate_matrix.schema.json
- schemas/roadrunner/job.schema.json
- schemas/roadrunner/manifest.schema.json

### Profiles
- roadrunner_profiles/carla_0913_datasmith_experimental.yaml
- roadrunner_profiles/carla_0916_fbx_xodr.yaml
- roadrunner_profiles/carla_filmbox_legacy.yaml
- roadrunner_profiles/large_map_tiled.yaml
- roadrunner_profiles/reference_only.yaml
- roadrunner_profiles/xodr_roundtrip.yaml

### Tests (empty stubs)
- tests/roadrunner/__init__.py (0 bytes)
- tests/roadrunner/conftest/__init__.py (0 bytes)
- tests/roadrunner/fixtures/fixtures.json (1572 bytes)

### Documentation
- docs/roadrunner/ARCHITECTURE.md
- docs/roadrunner/AUTHORING_WORKFLOW.md
- docs/roadrunner/CARLA_0916_COMPATIBILITY.md
- docs/roadrunner/INSTALLATION_MATRIX.md
- docs/roadrunner/LARGE_MAP_WORKFLOW.md
- docs/roadrunner/MANUAL_QA_CHECKLIST.md
- docs/roadrunner/ROUNDTRIP_POLICY.md
- docs/roadrunner/VISUAL_BUILD_WORKFLOW.md

### Reports
- reports/roadrunner/nemotron_risk_register.json (17528 bytes)

## RECOVERY_RECOMMENDATION
1. All 8 expected rr-* branches are either missing or empty.
2. The files present on disk are untracked and NOT committed to any branch.
3. These files appear to be a complete RoadRunner integration module but have no test coverage, no git history, and no verified compilation.
4. Recommended action: Create a single recovery branch from the authoritative base SHA (db0d983a) and commit the existing RoadRunner files as a single bounded batch. Follow with tests and verification.
5. The existing 3 rr-* local branches (rr-contracts-gpt55, rr-tests-north, rr-adversarial-nemotron) should be deleted as they contain no unique work.

## SAFE_TO_CREATE_RECOVERY_BRANCH
YES — only if the untracked RoadRunner files are verified first (compileall, lint) before committing.
