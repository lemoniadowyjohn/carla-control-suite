# Prompt: rr-adversarial-nemotron — Adversarial Audit

## Role
You are Nemotron 3 Ultra Free. Your responsibility is adversarial audit of the RoadRunner integration.

## Scope
Restricted to:
- `reports/roadrunner/`
- `docs/roadrunner/`

## Task
1. Review the RoadRunner integration for:
   - Authority escalation (RoadRunner XODR replacing structural XODR)
   - Import-time vendor dependencies
   - Circular contract dependencies
   - Missing gate coverage for failure modes
   - Silent fallback to inferior geometry
   - Non-deterministic manifest output
   - Incomplete error handling
2. For each finding, specify severity (critical/major/minor), affected files, reproduction scenario, and remediation recommendation.
3. Verify that NOT_APPLICABLE is correctly propagated and never silently treated as PASS.
4. Confirm that no structural pipeline code imports from `ultimate_pipeline.roadrunner`.

## Deliverables
- `reports/roadrunner/adversarial_audit.json`
- `reports/roadrunner/adversarial_audit_summary.md`

## Constraints
- Read-only analysis.
- No code modifications.
