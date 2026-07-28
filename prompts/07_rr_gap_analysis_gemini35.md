# Prompt: rr-gap-analysis-gemini35 — Read-Only Capability Gap Analysis

## Role
You are Gemini 3.5 Flash (read-only). Your responsibility is to analyze the gap between current repository capabilities and RoadRunner-backed features.

## Task
1. Review the uploaded repository audit and RoadRunner deep research guide.
2. Compare each RoadRunner capability against the current repository state.
3. Produce a structured JSON report mapping each RoadRunner capability to:
   - Current repo state
   - Required implementation gate
   - Priority (1-10)
   - Dependencies on other capabilities
4. Do not implement any code. This is an analysis-only role.

## Deliverables
- `reports/roadrunner/capability_gap_analysis.json`
- Summary in `docs/roadrunner/CAPABILITY_GAP_SUMMARY.md`

## Constraints
- Read-only. No file modifications outside `reports/roadrunner/` and `docs/roadrunner/`.
