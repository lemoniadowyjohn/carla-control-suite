# Codex — PROMPT R: survey the rest of the Phase G lane-QA chain (G0-G5, G7-G8)

## Context, including a real complication to be aware of

This session already found two genuinely valuable, real, tested, but completely unwired
subsystems this way (Phase H signal enrichment -- see PROMPT O; Phase G6 junction-lanelink
coverage repair -- see PROMPT P). The rest of the Phase G family
(ultimate_pipeline/tools/phase_g0_handoff.py through phase_g8_acceptance.py, excluding G6 which
has its own dedicated prompt) looks similarly substantial by docstring: G1 lane inventory, G2
width/border/laneOffset polynomial validation, G3 full cross-section reconstruction, G4 lane
continuity (predecessor/successor link validation), G5 lane-type semantic reclassification
(e.g. walk-side lanes must be outermost), G7 roadMark semantics (presence + validity), G8 a full
re-run acceptance gate over G1-G7. None of G0-G5/G7/G8 have any reference anywhere in
ultimate_pipeline/pipeline_stages/ or main_pipeline.py (confirmed via grep) -- same unwired
pattern as H and G6.

**The complication**: there is a DIFFERENT, older, already-investigated context involving some of
these same gate names -- a "Phase-N certification" (gates named G1-G19+, a larger numbering scheme)
run on 2026-08-13 against branch `fix/post-audit-phase-e-junctions-roundabouts-20260803` and a
candidate `ingolstadt_perception_final_repaired.xodr` (sha256 6bac3570...) that is NOT the current
map-of-record lineage. That certification run had G2/G5/G6/G7 among its 7 failing gates, but the
failures were diagnosed as stale-anchor (wrong candidate hash referenced in evidence), not code
defects, and the whole effort was blocked on a live CARLA run that never happened. Do not confuse
this with the present task -- that was a different candidate on a different branch, evaluated as a
CERTIFICATION exercise. This prompt is about whether G1-G5/G7/G8's own REPAIR/VALIDATION logic
(independent of that old certification run) has real, current value against the ACTUAL current
map-of-record, the same question already answered YES for G6 and H.

## PROMPT R

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/phase-g-lane-qa-survey-v1-<date>.
Read-only survey first -- do not modify the map-of-record or wire anything in until the survey is
complete and reviewed.

TASK: for each of ultimate_pipeline/tools/phase_g1_lane_inventory.py, phase_g2_polynomial_validation.py,
phase_g3_cross_section.py, phase_g4_lane_continuity.py, phase_g5_lane_classification.py,
phase_g7_roadmark_semantics.py (skip G0/G8 -- G0 is just a handoff/freeze record, G8 is a
meta-gate that reruns the others, neither has independent findings of its own):

1. Read the module in full. Is it purely a VALIDATOR (reports issues, no mutation) or does it also
   REPAIR (like G6 does)? Note which.
2. Run its check against the CURRENT pinned map-of-record
   (campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr)
   fresh -- do not rely on old evidence from a different candidate/branch (see the Phase-N
   certification complication above -- old G-gate evidence you might find in
   reports/post_audit_hardening/ may reference a DIFFERENT, non-current candidate; verify the
   candidate path/hash in any evidence file you look at before trusting its numbers).
3. Report real findings: does it find genuine defects on the CURRENT map that nothing currently
   live catches? For G5 specifically (lane-type reclassification): how many lanes does it find
   misclassified, and are the reclassifications semantically correct (spot-check at least 5
   manually against the actual OSM source)? For G7 (roadMark semantics): how many lanes currently
   lack a roadMark or have an invalid one, and does this matter for the perception/camera-based
   research use case this repo serves (missing lane markings would be a real, visually-relevant
   gap for CARLA-based sensor capture, not just an XODR-schema nicety)?
4. Do NOT implement any wiring or repair in this pass. This is a survey to determine which (if
   any) of these 6 modules deserves the same individual, careful investigation-first treatment PROMPT
   O/P/Q already got for H/G6/F5. Rank them by apparent real-world impact on the current map, with
   your evidence, so a human can decide what to prioritize next.

End with, for each of the 6 modules:
<MODULE>: VALIDATOR | REPAIR-CAPABLE -- <real finding count on current map> -- <one-line significance>
RECOMMENDED_PRIORITY_ORDER: <your ranked list with one-line reasoning each>
FULL_OFFLINE_TESTS: PASS | FAIL
```
