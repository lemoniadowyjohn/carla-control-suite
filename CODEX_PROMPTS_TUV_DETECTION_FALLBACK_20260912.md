# Codex — PROMPTS T, U, V: automatic detection + fallback repair for 3 issue classes

Follow-up to the G6 adversarial review. Three distinct defect classes were surfaced during that
review, each needs real detection wired into the pipeline plus a validated automatic fallback/fix
-- not just diagnostic reporting. All three already have SOME real code (found via this session's
"is it actually wired in" audit pattern), unwired, with zero prior real-scale execution evidence
(unlike Phase H/G6/F5, which had historical evidence) -- so all three require fresh validation
before any wiring, not just "turn it on."

---

## PROMPT T — wire the existing junction-connector pose-snap fix (position + heading)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/connector-snap-wiring-v1-<date>.

CONFIRMED: check_geometric_continuity.py already DETECTS junction-connector position/heading
discontinuities (gate_junction_connectors=True path, from this session's earlier Fix 1 work) --
9,176 such issues on the pinned map (dxy/dhdg mismatches between an incoming road's endpoint and
its connector's declared start pose). A real FIX already exists for this exact defect class:
ultimate_pipeline/tools/junction_connector_snap.py::snap_junction_connectors() re-poses a
connector's start geometry (x, y, AND hdg) to the incoming road's true endpoint when the gap
exceeds max_gap_m (default 2.0m), then rechains the connector's subsequent geometry segments to
preserve internal shape. It has an honest, documented limitation: contactPoint="end" connections
are skipped entirely (needs backward geometry propagation the tool doesn't implement) rather than
risk corrupting them. It is completely unwired -- zero references in pipeline_stages/ or
main_pipeline.py -- and has zero prior execution evidence at real-map scale.

TASK:
1. Run snap_junction_connectors against a COPY of the current pinned map-of-record and report
   real numbers: connectors_examined, connectors_snapped, skipped_end_contact_point (this count
   matters -- it tells you what fraction of the 9,176 known issues this tool can even address),
   and any other skip reasons. Confirm no map-of-record or frozen evidence was touched.
2. Verify correctness on the snapped candidate: re-run check_geometric_continuity with
   gate_junction_connectors=True on the result and confirm the snapped connectors' dxy/dhdg are
   now near-zero, confirm nothing else regressed (road count, other links, lane counts unchanged),
   confirm structural signature match.
3. Spot-check at least 5 real snapped connectors manually (position AND heading, similar rigor to
   this session's G6 adversarial review) to confirm the repair produces a physically sensible
   result, not just a numerically-small dxy/dhdg.
4. If clean: wire snap_junction_connectors into the live pipeline (stage_05_geometry.py or
   stage_08_hygiene.py, whichever matches this codebase's existing convention for connector-repair
   steps -- check where junction_connector_rebuild.py is called and follow that pattern). Report
   the new dxy/dhdg-issue count on a fresh full regen candidate (not just the existing pinned
   file) if you can produce one; otherwise report against the pinned file copy and note the
   limitation.
5. For the contactPoint="end" cases this tool cannot fix: do not attempt to extend the tool in
   this pass unless it's clearly safe and well-tested -- report the count and characteristics of
   what remains unaddressed, as a known residual gap for a future pass.

End with:
FRESH_VALIDATION: <connectors_examined, connectors_snapped, skipped_end_contact_point, other skips>
POST_SNAP_VERIFICATION: PASS | FAIL
MANUAL_SPOTCHECK: PASS | CONCERNS_FOUND (describe) -- 5+ cases
WIRED: PASS | FAIL | NOT_DONE (why not)
RESIDUAL_UNFIXABLE_COUNT: <count of contactPoint=end cases still unaddressed>
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT U — detect and correctly handle micro-stub (very-short-but-nonzero) road/connector segments

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/micro-stub-detection-v1-<date>.

CONFIRMED (from this session's G6 adversarial review): roads 46317 (0.103m) and 46644 (0.200m) --
very short but NOT zero-length -- produce unreliable heading-continuity signals when their raw
reference-line heading is compared across their own length, because a tiny geometric wiggle over
a sub-meter span translates into a large angular change. This is the SAME underlying class as
GAP-023 (structure_scanner.py's curvature-anomaly microsegment-inflation bug, already fixed with a
minimum-segment-length floor), but GAP-023's fix only applies to that ONE checker
(structure_scanner.py's curvature metric) -- this class of road can still produce misleading
signals in OTHER heading/curvature-sensitive checks across the codebase (check_geometric_
continuity.py, G6's own audit, junction_connector_snap.py's gap calculation, etc.) that were not
specifically guarded.

This is explicitly NOT the same as zero_length_connector_repair.py's scope (that tool handles
`length <= 0.0`, genuinely degenerate geometry -- these micro-stubs have positive, if tiny,
length, a different and more subtle problem).

TASK:
1. Determine the real prevalence: how many roads/geometry segments on the pinned map-of-record
   have length under some reasoned threshold (start from 0.5m, adjust based on what you find) but
   greater than 0 -- report the actual count and distribution, don't guess.
2. Determine whether these are a genuine repairable defect (e.g., should be merged into an
   adjacent segment, since a 0.1-0.2m "road" is not independently drivable/meaningful) or a
   legitimate, expected artifact of the OSM->SUMO->Osm2Odr conversion chain (tiny junction-approach
   fragments that exist for correct topological reasons and shouldn't be eliminated, just
   correctly EXCLUDED from length-sensitive analyses). Investigate a representative sample before
   deciding -- do not assume either answer.
3. If they are a genuine, safely-mergeable artifact: propose (implement only if clearly safe and
   well-tested) a merge/elimination repair. If they are legitimate structural fragments: instead
   build a small, shared, reusable helper (e.g. `is_micro_stub_segment(geometry, min_length_m)`)
   that any heading/curvature-sensitive checker can call to correctly exclude these from analysis,
   and apply it consistently across check_geometric_continuity.py, phase_g6_junction_lanelinks.py,
   junction_connector_snap.py's gap calculation, and any other consumer you find doing raw
   heading/curvature comparison without already guarding for this.
4. Add regression fixtures proving both the detection and the correct exclusion/repair behavior.

End with:
MICRO_STUB_PREVALENCE: <count and length distribution on the pinned map>
CLASSIFICATION: SAFELY_MERGEABLE_ARTIFACT | LEGITIMATE_STRUCTURAL_FRAGMENT (with reasoning)
FIX_IMPLEMENTED: MERGE_REPAIR | SHARED_EXCLUSION_HELPER | NOT_DONE (why not)
CONSUMERS_UPDATED: <list of files that now correctly handle this>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT V — wire G6 lane-coverage repair into the live pipeline (advisory-first)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/g6-coverage-wiring-v1-<date>.
Read the full history first: CODEX_PROMPT_P_G6_ISOLATED_LANES_20260909.md (the original
investigation-only task) and its result (feature/g6-lane-coverage-repair-v1-20260911,
CODEX_G6_LANE_COVERAGE_INVESTIGATION.md/.json). This topic has now been through: (1) an original
3-round investigation in an earlier session that closed it as "do not build" under a disambiguation
framing, (2) a fresh investigation this session proving a DIFFERENT technique (lane convergence,
not disambiguation) resolves 26 of 27 permanently-isolated lane components, (3) an independent
Claude adversarial review of that result (from-scratch reproduction confirming the topology claim
exactly; explained all 3 apparent geometric outliers as either known micro-stub artifacts or
pre-existing, already-documented junction-connector defects unrelated to G6 itself; found the
disclosed "near-zero distance" framing from the 5-sample check was not representative -- median
real lateral-merge distance across all 126 additions is 3.5m, max 7.1m). The operator has now
authorized moving to wiring this in, on the basis of that completed adversarial review.

TASK:
1. Wire ultimate_pipeline.tools.phase_g6_junction_lanelinks.repair_coverage_gaps into the live
   pipeline. Follow this codebase's established pattern for hygiene/repair steps
   (stage_08_hygiene.py's 8H-N numbering convention) -- add it as a new numbered step, not a
   bolt-on. It must run on the live root, be transactional (only commit if repair_issues is empty
   and the post-repair G6 audit is clean, matching the investigation script's own validated
   pattern), and produce a persisted report (added_lanelinks count, per-repair details, the
   lateral-merge-distance for each addition using the same computation approach as this session's
   adversarial review -- do NOT omit this metric, it's the one disclosure gap the review found).
2. Advisory-first: do not make this a hard-fail gate. Report the isolated-component delta
   (component_reachability_summary before/after) as a metric in map_acceptance.py's output,
   surfaced clearly, but do not block promotion on it -- this defect class has been tolerated
   throughout this map's history and characterizing its resolution shouldn't itself become a new
   blocker.
3. Explicitly surface the lateral-merge-distance distribution in the persisted report (min/median/
   max, and flag any individual repair whose merge distance exceeds some reasoned threshold --
   propose the threshold yourself with reasoning, e.g. 2x typical lane width) so a human reviewing
   a future regen's report can see at a glance whether this pass's repairs look like normal
   adjacent-lane merges or something requiring closer inspection.
4. Run a fresh full regen if you can (not just a copy of the pinned file) and report the real
   before/after isolated-component count on that fresh output. If a fresh regen isn't practical in
   this pass, run against a copy of the pinned map and say so explicitly.
5. Full offline suite and scripts/measure_candidate_acceptance.py before/after, report the diff.
   Do NOT promote any new candidate to auto_map_of_record in this pass -- that remains a separate,
   explicit operator decision after this branch is reviewed.

End with:
WIRED: PASS | FAIL
STAGE_LOCATION: <exact file/step number>
TRANSACTIONAL_SAFETY: PASS | FAIL -- <how verified>
ISOLATED_COMPONENT_DELTA: <before> -> <after>, on <fresh regen | pinned-map copy>
LATERAL_MERGE_DISTRIBUTION: <min/median/max, count exceeding your proposed threshold>
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
```
