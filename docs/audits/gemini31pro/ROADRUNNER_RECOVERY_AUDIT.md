# RoadRunner Recovery Audit — gemini31pro

**AUDITED BRANCH:** `origin/recovery/roadrunner-capability-integration` — DOES NOT EXIST

---

## AUDIT SUMMARY

The requested branch `origin/recovery/roadrunner-capability-integration` was verified to not exist remotely or locally. The nearest related branches are `origin/integration/deepseek-roadrunner-hardening` and `origin/deepseek-observability-integration-verification`. The audit below documents the state of the working tree relative to the DeepSeek base and the newly created RoadRunner automation files.

---

## AUDITED BRANCH

`origin/recovery/roadrunner-capability-integration`

**Status:** DOES NOT EXIST

---

## BASE SHA

`db0d983a34209e0a47628d3c2b48efc3f9327ec4` — `origin/deepseek-observability-integration-verification`

---

## HEAD SHA

`a12fe9ba7508bad2bce5f22cea923cf33fc57173` — HEAD (current working tree)

---

## UNIQUE COMMITS

0 unique commits between the DeepSeek base and HEAD on a shared ancestry path (the two refs are not in a direct ancestor-descendant relationship).

---

## FILES CHANGED (deepseek base → HEAD)

16 files changed, 6 insertions(+), 1791 deletions(-):

| File | Change |
|------|--------|
| `ROADRUNNER_MISSING_CAPABILITIES.json` | deleted |
| `prompts/01_rr_contracts_gpt55.md` | deleted |
| `prompts/02_rr_roundtrip_laguna.md` | deleted |
| `prompts/03_rr_visual_mimo.md` | deleted |
| `prompts/04_rr_automation_ling.md` | deleted |
| `prompts/05_rr_docs_profiles_gemini31.md` | deleted |
| `prompts/06_rr_tests_north.md` | deleted |
| `prompts/07_rr_gap_analysis_gemini35.md` | deleted |
| `prompts/08_rr_adversarial_nemotron.md` | deleted |
| `ultimate_pipeline/cli.py` | modified (630 lines removed) |
| `ultimate_pipeline/contracts/gate_runner.py` | deleted |
| `ultimate_pipeline/entrypoints.py` | modified (45 lines removed) |
| `ultimate_pipeline/main_pipeline.py` | modified (113 lines removed, 6 inserted) |
| `ultimate_pipeline/pipeline_stages/stage_05_geometry.py` | deleted |
| `ultimate_pipeline/quality/drivable_surface_scanner.py` | deleted |
| `ultimate_pipeline/quality/full_map_metrics.py` | deleted |

---

## PERMITTED ADDITIVE PATHS (newly created, uncommitted)

The following new files exist in the working tree (not yet committed):

- `ultimate_pipeline/roadrunner/installation.py`
- `ultimate_pipeline/roadrunner/capability_probe.py`
- `ultimate_pipeline/roadrunner/process_runner.py`
- `ultimate_pipeline/roadrunner/grpc_runner.py`
- `ultimate_pipeline/roadrunner/matlab_runner.py`
- `tools/roadrunner/probe_roadrunner.py`
- `tools/roadrunner/generate_grpc_bindings.py`
- `matlab/roadrunner/rr_probe.m`
- `matlab/roadrunner/rr_import_xodr.m`
- `matlab/roadrunner/rr_export_xodr.m`
- `matlab/roadrunner/rr_export_fbx_xodr.m`
- `matlab/roadrunner/rr_export_tiled.m`
- `matlab/roadrunner/rr_close_all.m`

---

## PROHIBITED FILE CHANGES

### Vendor files, binaries, generated bindings, secrets

- `ultimate_pipeline/roadrunner/grpc_runner.py` — no vendor bindings committed; build output targets `.rr_grpc_build/` (git-ignored)
- No binaries, protobuf-generated `_pb2.py` or `_pb_grpc.py`, or secret values found
- `.gitignore` updated to include `.rr_grpc_build/` and RoadRunner `__pycache__` entries

### Import-time RoadRunner/MATLAB dependency

All 5 new Python modules use lazy imports and filesystem probes only. Verified: `import ultimate_pipeline.roadrunner` succeeds without RoadRunner or MATLAB installed.

### Models and profiles fail closed

`capability_probe.py` reports `overall_status = "blocked"` when required capabilities are missing. `gate_matrix.py` (existing) rejects releases that violate gate profiles.

### Authority cannot silently escalate

`models.py` enforces `GOVERNED_INPUT` authority class for source data. Candidate artifacts must use `DERIVED_CANDIDATE` authority. `RoadRunnerContractError` is raised on violations.

### Round-trip comparison

The `models.py` `RunManifest` and `ArtifactRecord` SHA-256 chaining ensures round-trip fidelity is detectable. RoadRunner output cannot replace governed XODR automatically — the contract validates parent SHA and rejects authority escalation.

### Visual inventory

The `visualization/` subpackage (existing) detects axis, scale, origin, tile, and semantic defects through `MeshXodrAlignmentSummary` and `SemanticDiffSummary`.

### Validators are read-only

`capability_probe.py` and `process_runner.py` do not mutate RoadRunner or source data. `installation.py` uses `shutil.which()` and filesystem probes only.

### Runtime missing dependencies → BLOCKED/NOT_APPLICABLE

`capability_probe.py` classifies missing required capabilities as `severity = "error"` and missing optional capabilities as `severity = "warning"`. `run_capability_probe()` returns `overall_status = "blocked"` when errors are present.

### CARLA 0.9.13 vs 0.9.16

No CARLA version constraints are presented in any newly created file. Existing codebase constraints are unchanged.

### Traffic-light visuals ≠ runtime control

No traffic-light runtime control is introduced in the new files. Traffic light handling remains in existing enrichment and pipeline stages.

### RoadRunner output cannot replace governed XODR

`models.py` `SourceDataContract` enforces `GOVERNED_INPUT` authority. `RoadRunnerJobRequest` cannot request `GOVERNED_INPUT` authority (enforced in `__post_init__`). Export artifacts must reference a `parent_sha256`.

---

## TEST STATUS

| Check | Result |
|-------|--------|
| `python -m compileall ultimate_pipeline` | PASS |
| `python -m pytest tests/ -k "roadrunner"` | NO TESTS FOUND |
| `python -m pytest -m "not carla"` | TIMEOUT (pre-existing) |
| `git diff origin/deepseek-observability-integration-verification...HEAD --check` | PASS (no whitespace errors) |

**Missing:** No `tests/roadrunner` directory exists. No roadrunner-specific test suite has been created.

---

## CRITICAL FAILURES

1. **Branch `origin/recovery/roadrunner-capability-integration` does not exist** — cannot verify branch-level claims
2. **No roadrunner test suite exists** — `tests/roadrunner/` is missing
3. **New files are uncommitted** — all 13 new files exist only in the working tree, not on the requested branch
4. **DeepSeek base is not an ancestor of HEAD** — the two refs are on separate ancestry paths

---

## HIGH FAILURES

1. **No automated test coverage for new code** — no pytest tests for `roadrunner` package
2. **No integration verification** — cannot verify gRPC or MATLAB runner behavior without those runtimes installed
3. **Uncommitted working tree** — audit cannot confirm the commit history matches the requested branch

---

## RUNTIME BLOCKERS

1. **MATLAB** — not installed in audit environment; `matlab_runner.py` cannot be tested at runtime
2. **RoadRunner** — not installed in audit environment; `capability_probe.py` correctly reports `BLOCKED`
3. **gRPC tooling** — `grpc_tools` not installed; `grpc_runner.py` gracefully returns empty binding set

---

## SAFE TO CONSOLIDATE

- No

The branch `origin/recovery/roadrunner-capability-integration` does not exist. All new files are uncommitted working tree additions. The code passes static checks (`compileall`, `ast.parse`, import verification) but lacks test coverage and integration validation.

---

## REQUIRED FIXES BEFORE CONSOLIDATION

1. Create branch `recovery/roadrunner-capability-integration` from the appropriate base
2. Commit all 13 new files to the branch
3. Create `tests/roadrunner/` with meaningful test suite covering:
   - `test_installation.py` — offline-safe detection tests
   - `test_capability_probe.py` — required/optional/warning classification tests
   - `test_process_runner.py` — timeout, safe termination, env allow-list tests
   - `test_process_runner_safety.py` — secrets redaction, argument array enforcement
   - `test_grpc_runner.py` — proto discovery, build directory isolation, no vendor binding commits
   - `test_matlab_runner.py` — parameter-driven execution, log saving, source preservation
4. Add CI check for prohibited file patterns (vendor bindings, binaries, secrets)
5. Verify branch SHA matches expected base before merge
6. Run full `python -m pytest -m "not carla"` to confirm no regressions