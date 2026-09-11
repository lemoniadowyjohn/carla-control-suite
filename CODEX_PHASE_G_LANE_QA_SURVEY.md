# Phase-G Lane QA Current-Map Survey

This is a read-only survey of the current pinned map, not a request to enable
or repair any Phase-G module. The source map retained SHA-256
`2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`
before and after every audit.

## Result

G1 inventory, G2 polynomial validation, and G4 lane continuity find no
blocking current-map defects. G5 and G7 are repair-capable but not admissible
for activation:

- G5 proposes zero `restricted -> driving` reclassifications. Its 1,204
  walk-side findings compare lane numbers across opposite sides of the road.
  Five inspected cases have the sidewalk outermost on its own side, so this is
  a validator defect rather than a current-map lane misclassification.
- G7 reports 19,324 zero-width visible markings, all `solid` marks on
  `sidewalk` lanes. Its generic repair would assign a 0.13 m width to all of
  them without evidence that such a visual change is correct. Only two
  driving-lane solid marks (roads 46620 and 74522) omit `laneChange`.

G3 needs the next investigation. It passes while 751 non-stub sampled sections
are unavailable because a road's declared length is slightly longer than its
planView end. The measured positive drift is bounded (p95 0.06995 m, max
0.09999999 m), so this is not evidence that 751 roads have visually material
geometry defects. It is evidence that G3's pass verdict does not prove full
sampling coverage.

## OSM Boundary

No G5 reclassification candidate exists to spot-check. The five false-positive
examples have no OSM way ID in their XODR `userData`; matching their street names
to the authoritative OSM produces multiple possible ways. A source-accurate
semantic claim therefore remains unproven rather than being inferred from a
name-only match.

## Recommended Order

1. Fix G7 lane-type-aware audit/repair boundaries and add fixtures before any
   activation.
2. Define the allowed planView-length tolerance and make G3 report coverage
   failure honestly.
3. Correct G5's side-local outermost invariant before reconsidering lane-type
   repair.
4. Retain G4, G2, and G1 as offline validators; no current-map remediation is
   justified by their results.

Raw evidence paths and hashes are recorded in the accompanying JSON.

Focused verification passed: 48 lane-quality tests, plus the native G3 and
G7 synthetic fixture suites. No source implementation changed, so a full-suite
run is intentionally deferred to an artifact-complete integration worktree;
this sparse audit checkout omits ignored large artifacts.
