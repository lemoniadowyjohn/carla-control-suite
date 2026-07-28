# Prompt: rr-roundtrip-laguna — OpenDRIVE Round-Trip Semantic Comparison

## Role
You are Laguna S 2.1 Free. Your responsibility is OpenDRIVE round-trip semantic comparison.

## Scope
Restricted to:
- `ultimate_pipeline/roadrunner/`
- `tests/roadrunner/`

## Task
1. Implement semantic diff between parent structural XODR and RoadRunner-imported-re-exported XODR.
2. Compare: road geometry (plan view, elevation, lateral), lane counts/widths/types/directions, junctions and connections, signal/signal references.
3. Report added, removed, and modified elements with quantitative deltas.
4. Flag authority escalation: RoadRunner must not promote its XODR authority above the structural source.
5. All comparison logic must work offline; no live RoadRunner required.

## Deliverables
- `ultimate_pipeline/roadrunner/semantic_manifest.py` — semantic diff models and validation
- `schemas/roadrunner/manifest.schema.json` updates
- Tests covering: identical roads → match; modified geometry → delta; added/removed lanes → added/removed; authority escalation → blocked

## Constraints
- No import-time RoadRunner dependency.
- No modification of structural pipeline stages.
- Commit, test, push, verify SHA.
