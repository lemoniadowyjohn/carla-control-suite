# Prompt: rr-docs-profiles-gemini31 — Documentation & Immutable Execution Profiles

## Role
You are Gemini 3.1 Flash Lite. Your responsibility is documentation and immutable execution profiles for RoadRunner integration.

## Scope
Restricted to:
- `docs/roadrunner/`
- `roadrunner_profiles/`
- `reports/roadrunner/`

## Task
1. Document the RoadRunner integration architecture, including capability detection, gate matrix, export workflow, and round-trip comparison.
2. Create immutable YAML execution profiles for each export target: CARLA 0.9.16 FBX+XODR, CARLA 0.9.13 Datasmith (experimental), CARLA Filmbox legacy, large-map tiled, reference-only, XODR round-trip.
3. Write a CARLA 0.9.16 compatibility guide explaining why Datasmith is experimental and FBX+XODR is the production path.
4. Write an installation matrix documenting tested RoadRunner/MATLAB/CARLA version combinations.
5. Write a large-map workflow guide covering tiled export, streaming QA, and tile union verification.
6. Write a manual QA checklist for visual inspection of RoadRunner exports.
7. Write a round-trip policy document explaining authority rules and quarantine workflow.

## Deliverables
- `docs/roadrunner/ARCHITECTURE.md`
- `docs/roadrunner/AUTHORING_WORKFLOW.md`
- `docs/roadrunner/CARLA_0916_COMPATIBILITY.md`
- `docs/roadrunner/INSTALLATION_MATRIX.md`
- `docs/roadrunner/LARGE_MAP_WORKFLOW.md`
- `docs/roadrunner/MANUAL_QA_CHECKLIST.md`
- `docs/roadrunner/ROUNDTRIP_POLICY.md`
- `docs/roadrunner/VISUAL_BUILD_WORKFLOW.md`
- `roadrunner_profiles/` YAML files (6 profiles)
- `reports/roadrunner/` sample templates

## Constraints
- Read-only analysis.
- Commit, test, push, verify SHA.
