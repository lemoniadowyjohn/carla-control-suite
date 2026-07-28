# Prompt: rr-contracts-gpt55 — RoadRunner Contracts & Gate Model

## Role
You are GPT-5.5 Fast. Your responsibility is RoadRunner contracts, manifests, and the fail-closed gate model.

## Scope
Restricted to:
- `ultimate_pipeline/roadrunner/`
- `schemas/roadrunner/`
- `tests/roadrunner/`

## Task
1. Define immutable data contracts for RoadRunner job requests, run manifests, artifact records, and source-data provenance.
2. Implement a gate matrix that evaluates required/optional gates per release profile and rejects releases with BLOCKED or FAIL status on required gates.
3. Ensure NOT_APPLICABLE is accepted only for gates explicitly listed as optional by the selected profile.
4. All contracts must be serializable to JSON with deterministic key ordering.
5. No import-time dependency on RoadRunner, MATLAB, or any vendor library.

## Deliverables
- `ultimate_pipeline/roadrunner/models.py` — all data models
- `ultimate_pipeline/roadrunner/gate_matrix.py` — gate matrix evaluation
- `ultimate_pipeline/roadrunner/source_contract.py` — XODR source provenance
- `schemas/roadrunner/manifest.schema.json`
- `schemas/roadrunner/gate_matrix.schema.json`
- `schemas/roadrunner/job.schema.json`
- Tests in `tests/roadrunner/` covering gate evaluation, serialization, and contract validation

## Constraints
- Branch from the published DeepSeek SHA only.
- Commit, test, push, verify SHA equality. No force-push.
- Do not touch files outside the scope above.
