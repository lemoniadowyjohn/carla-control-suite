# Codex — PROMPT P: re-examine the 27-isolated-lanes question via Phase G6 (sensitive, read history first)

## MANDATORY CONTEXT — read before doing anything

This exact defect class (27 isolated lane components on the map-of-record) was investigated in
depth THREE separate times in an earlier session (2026-09-04/05) and definitively closed as
"do not build," with this explicit instruction for any future revisit: **"do NOT restart from the
disambiguation framing -- go straight to investigating whether missing lane-level connector
geometry can be synthesized safely."**

The closure's decisive finding: simulating all 16 CONFIDENT-classified candidate fixes produced
`DELTA_ISOLATED = 0`. Root cause, precisely: "in every single one of the 16 cases, the matched
candidate road has FEWER driving lanes than the gap road, and the specific lane causing isolation
is always the outermost/highest-numbered one -- which has NO matching lane id on the (correctly,
uniquely) matched candidate... it's a missing junction movement: no connector anywhere in the
junction carries that specific lane." Fixing it was judged to require "inventing a new lane on an
existing connector road, or an entirely new connector road, that doesn't exist anywhere in the
OSM-derived geometry" -- ruled out as fabricating infrastructure.

## Why this prompt exists anyway: a candidate technique the prior closure didn't know about

`ultimate_pipeline/tools/phase_g6_junction_lanelinks.py` ("G6") implements exactly the
"missing_driving_from_coverage" defect class -- its own docstring: "every driving lane that flows
into the incoming road's contacted endpoint must appear as a `from` in at least one connection of
that junction" -- which is structurally the SAME finding as the September closure's "no connector
anywhere in the junction carries that specific lane." G6's repair technique is NOT disambiguation
among existing candidates, and NOT fabrication of new connector roads: "Coverage gaps are REPAIRED
iteratively: an uncovered driving lane U converges onto the driving target lanes of its routed
neighbour (inner neighbour preferred, outer neighbour fallback)" -- i.e. lane U's traffic is
routed onto an ALREADY-EXISTING, ALREADY-VALID neighbouring connector, not a newly-invented one.

Real evidence this works, at least on an older map: reports/post_audit_hardening/
C0_G6_COVERAGE_FIX.md (2026-08-16) ran this repair against
ingolstadt_perception_clean_regen_crashsafe_20260815.xodr (a real, full-scale probe, NOT this
prompt's fabrication) and reduced `missing_driving_from_coverage` from 5 to 0, adding 126 real
laneLinks, with every G6 check passing afterward. This module also has real test coverage
(tests/unit/test_phase_g6_junction_lanelinks.py).

G6 is NOT wired into the live pipeline or the campaign-script cluster (confirmed: zero references
anywhere outside its own file and its test). It appears to have simply never been connected to
anything, the same "built but never wired" pattern found repeatedly this session elsewhere
(Phase H, Phase J) -- NOT evidence it was deliberately rejected for a known flaw. But this has
NOT been independently confirmed, which is exactly this prompt's first job.

## PROMPT P

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/g6-lane-coverage-repair-v1-<date>.
Read this entire prompt including the MANDATORY CONTEXT above before starting -- this is a
sensitive, previously-closed topic being reopened on new evidence, not a routine task.

This is INVESTIGATION FIRST. Do not modify the map-of-record or wire anything into the live
pipeline until every step below is satisfied. If any step fails or is ambiguous, STOP and report
-- do not push through to "make it work."

TASK:
1. Read ultimate_pipeline/tools/phase_g6_junction_lanelinks.py in full and
   reports/post_audit_hardening/C0_G6_COVERAGE_FIX.md in full. Confirm your own understanding of
   the repair technique matches this prompt's description before proceeding.
2. Run G6's coverage CHECK (not yet the repair) against the CURRENT pinned map-of-record
   (campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr)
   -- the August evidence used an older, different map. Report the current
   missing_driving_from_coverage / missing_driving_to_coverage counts fresh.
3. CRITICAL VALIDATION STEP: independently confirm (do not assume from the finding above) that G6's
   coverage gaps genuinely correspond to the SAME 27 roads currently reported as isolated by
   component_reachability_summary() -- these are two different metrics (G6: per-junction laneLink
   coverage; component_reachability: whole-graph reachability) and their overlap has NOT been
   verified. Build a from-scratch mapping: for each of the 27 currently-isolated roads, is its
   isolation caused by a missing_driving_from_coverage gap at a specific junction? If some or all
   of the 27 are NOT explained by G6-class gaps, say so explicitly -- do not force a connection
   that isn't there.
4. If the overlap is real: run G6's actual REPAIR (repair_coverage_gaps or equivalent) against a
   COPY of the current pinned map (never the live pinned file directly), then re-run
   component_reachability_summary() on the repaired copy. Report the real before/after isolated
   count -- this is the actual acceptance criterion, not G6's own internal "coverage" metric.
5. Semantic sanity check: for at least 5 of the actual repairs G6's technique would make on the
   real map, manually inspect what "lane U converges onto its routed neighbour's target" produces
   geometrically/physically -- does this represent a plausible real-world lane merge (a driver in
   an ending lane naturally merges into the adjacent lane before a junction), or does any specific
   case produce an implausible/unsafe-looking routing (e.g. crossing a lane it shouldn't, a sharp
   unrealistic merge angle)? This determines whether "safely synthesized" is actually true, not
   just "produces a laneLink."
6. Do NOT commit any change to the map-of-record or wire G6 into the live pipeline in this pass,
   regardless of how step 4/5 come out. This prompt's job is to produce a trustworthy answer to
   "does this actually work and is it safe," with real numbers, for a human (Claude + the
   operator) to review before any decision to build on it. If everything checks out, end by
   proposing (not implementing) the smallest safe next step.

End with:
CURRENT_MAP_COVERAGE_GAPS: <missing_driving_from_coverage count, missing_driving_to_coverage count>
GAP_TO_ISOLATED_ROAD_OVERLAP: <how many of the 27 isolated roads are explained by a G6-class gap>
REPAIR_ISOLATED_COUNT_DELTA: <before> -> <after>, on a COPY only
SEMANTIC_SANITY_CHECK: PASS | CONCERNS_FOUND (describe) -- <5+ manually inspected cases>
RECOMMENDATION: <your proposed smallest safe next step, or "do not pursue" with reasoning>
FULL_OFFLINE_TESTS: PASS | FAIL
```
