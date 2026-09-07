# Claude Independent Adversarial Review — Roundabout Reconstruction V2

Reviewer role: architecture and acceptance authority (per the MQ-A/MQ-B program). This review does
not trust Codex's self-reported verdict block or evidence JSON files at face value — every claim
below was independently re-derived: by reading the actual implementation, by running the actual
tests myself, and by directly checking git state, not by re-stating what the evidence files say.

Branch reviewed: `feature/roundabout-reconstruction-v2-20260907` @ `a786849b4a2cdfa7966ee5dd8fe639cad0540d97`.

## Baseline note (resolved, not a blocker)

Codex's implementation report and evidence JSON cite `base_sha: f195ba0b5d6df3f085573c5e996ff9d0f11a975f`.
This SHA did **not** exist when the MQ-A audit first checked it, but was confirmed to exist by the
time this review ran: `origin/stabilize/research-release-20260905` now points exactly at
`f195ba0b5d6df3f085573c5e996ff9d0f11a975f`, a real GitHub merge commit (PR #3, merging
`review/claude-independent-audit-20260906` into `stabilize/research-release-20260905`,
authored/committed 2026-09-06T18:21:18+02:00 — after the MQ-A audit's initial check, before this
implementation branch was created). `git merge-base --is-ancestor f195ba0b HEAD` confirms `f195ba0b`
is a real ancestor of this branch's HEAD. **Codex's base is genuinely correct** — the earlier
`BASELINE_AUTHORITY_CHANGED` finding was accurate for its moment and has since resolved itself via
the actual PR merge, not via the `BASELINE_REBASELINE_AUTHORIZATION.md` workaround (which remains
useful as a record of the interim human decision, but wasn't ultimately needed to unblock this).

## Safety claims — all independently verified TRUE

| Claim | Verification method | Result |
|---|---|---|
| Worktree clean | `git status --porcelain=v2` | Confirmed clean |
| `roundabout_v2` not wired into `main_pipeline.py`/`pipeline_stages/` | `grep -rn roundabout_v2` across both | Zero matches — genuinely not called from the live pipeline |
| No accidental import anywhere outside its own package/tests | repo-wide grep | Zero matches |
| `map_registry.py` unchanged | `git diff --stat f195ba0b HEAD -- ultimate_pipeline/carla_tools/map_registry.py` | Empty diff |
| No frozen evidence touched | `git diff --stat f195ba0b HEAD -- campaigns/ reports/post_audit_hardening/` | Empty diff |
| No CARLA started | process/socket checks not re-run (no reason to doubt; code contains zero CARLA imports) | Consistent |

**Every safety-critical claim in Codex's report is accurate.** This candidate genuinely does not touch
the map-of-record, the live pipeline, or frozen evidence.

## Design review against the target contract (`docs/map_quality/JUNCTIONS_AND_ROUNDABOUTS.md`)

Read `core.py`, `ring.py`, `validator.py`, `lane_links.py`, `elevation.py`, `reporting.py`,
`reconstructor.py` in full (not excerpted). Against the design target this audit program set:

- **Does NOT force a perfect circle**: `choose_geometry_model` fits a circle and only selects
  `CIRCLE_FIT` if the RMSE is within a configurable threshold (default 0.75); otherwise
  `SOURCE_PRESERVED_NON_CIRCULAR`. This is a genuine, correct fix for GAP-008's core complaint.
- **Preserves multi-lane counts**: `infer_lane_model`/`_lanes()` reads real driving-lane IDs from the
  source roads instead of hardcoding one lane. `build_segment_specs` explicitly **rejects** (fails
  closed, does not guess) when adjacent anchors have different lane counts
  (`"lane-count transition requires explicit mapping"`) rather than silently collapsing to 1 lane the
  way V1 did. Directly unit-tested with a 2-lane-per-side fixture
  (`test_segmented_ring_preserves_endpoints_links_and_multiple_lanes`), independently re-run by me
  and confirmed passing.
- **Real attachment poses, not idealized**: `extract_endpoint_anchors` uses the connection's actual
  `contactPoint` and the road's real sampled endpoint (position + heading), not a polar-angle
  heuristic like V1.
- **Tangent continuity at entry/exit**: the segmented-ring construction (`_hermite_xy`,
  `build_segment_xml`) uses a cubic Hermite fit constrained by both endpoints' real positions AND
  real headings — tangent continuity is a structural consequence of the construction, not an
  afterthought.
- **Transactional, non-destructive**: `reconstruct_transactional` operates on a deep clone and never
  mutates the input; `reconstruct_ring_transactional` only commits (appends new roads) after full
  validation passes, and explicitly does not delete/replace source roads.

This is a substantively better design than V1, and it correctly avoids the specific failure modes
the gap register documented. **However**, it does not yet fully close GAP-008: it has no representation
for splitter islands (acknowledged, out of scope for this candidate), no boundary-clip handling
(not addressed), and the elliptical/lane-count-transition-around-the-ring cases from
`docs/map_quality/JUNCTIONS_AND_ROUNDABOUTS.md`'s required fixture list are still not covered by
new tests — the fail-closed rejection of lane-count transitions is safe, but means the general
`PRODUCTION_MAP_TASK_GRAPH.json` T-007 task is not complete, just meaningfully advanced.

## Findings from this review (not self-reported by Codex)

### 1. A real, verified factual discrepancy in the self-reported test count

Codex's report and `CODEX_ROUNDABOUT_V2_EVIDENCE.json` both claim `"legacy_roundabout": "39 passed"`.
I independently ran the exact two legacy test files on this exact commit:

```
tests/topology/test_roundabout_rebuilder.py ....... (17 passed)
tests/topology/test_roundabout_reconstructor.py .... (27 passed)
Total: 44 passed, 0 failed, 0 skipped, 0 errors
```

Confirmed both files are byte-identical to the base (`git diff f195ba0b HEAD -- <files>` is empty),
so this isn't explained by Codex having modified them. **The true number is 44, not 39** — a
verifiable inaccuracy in Codex's self-reported evidence. This is not a safety concern (44 is *better*
than 39, i.e. this is under-claiming, not hiding a failure), but it means the evidence JSON files
should not be treated as ground truth without spot-checking, exactly as this review was scoped to do.

Separately, `ROUNDABOUT_V2_BASELINE.json`'s `metrics.test_counts` says "5825 collected", while
`CODEX_ROUNDABOUT_V2_EVIDENCE.json` and the chat-relayed report both say "5830 collected." I
independently ran full collection myself: **5830 collected, 1 error, matching the higher figure.**
`ROUNDABOUT_V2_BASELINE.json`'s "5825" appears to be a stale or separately-derived number. The
collection error itself (`tests/unit/test_package_smoke_check.py`, `ModuleNotFoundError: No module
named 'package_smoke_check'`) was independently reproduced and confirmed to be exactly what Codex
described: `scripts/` is excluded by this worktree's active sparse-checkout config
(`git sparse-checkout list` confirms `scripts/` is not in the included-paths set), unrelated to this
candidate's own code. Correctly classified by Codex as an environment artifact, not a regression.

### 2. An internal API contradiction: two lane-link validators disagree on whether `-1`->`-1` is valid

- `core.py::validate_lane_mapping` unconditionally rejects any mapping where
  `source == -1 and target == -1`, calling it a "sentinel" that "is not accepted" — this appears to
  specifically encode rejection of V1's known anti-pattern (a hardcoded universal `-1/-1` fallback
  used regardless of whether it was actually correct).
- `lane_links.py::map_lanes` (the function actually used by the real ring-construction path,
  `ring.py:100`) explicitly treats `-1`->`-1` as a **legitimate** mapping when both sides genuinely
  have a `-1` lane, with a code comment justifying this: "`-1` is a real OpenDRIVE rightmost
  driving-lane ID when it exists in both lane sections; only missing/implicit mappings are rejected
  above."
- Both functions are exported in `__init__.py.__all__` and both are directly unit-tested, each
  passing its own narrow test in isolation
  (`test_elevation_and_lane_sentinel_contract` expects `validate_lane_mapping` to always reject
  `-1`->`-1`; `test_lane_mapping_and_serialization_are_fail_closed` expects `map_lanes` to accept it).

**This is a genuine design inconsistency**, not just a naming collision — the two functions encode
contradictory rules for the same conceptual check. It doesn't affect current test results (nothing
calls `validate_lane_mapping` from the real reconstruction path), but it is a real misuse trap for
whoever integrates this candidate further: if a future caller reaches for `validate_lane_mapping`
(the one in `core.py`, arguably the more "obvious" name) instead of `lane_links.validate_links`, they
would incorrectly reject legitimate V2 output. Recommend resolving before this candidate advances
further: either delete `core.validate_lane_mapping` (if it's dead/superseded) or rename it to make
its narrower V1-specific-anti-pattern purpose explicit (e.g. `reject_universal_sentinel_mapping`).

### 3. Two scoped-down design simplifications, disclosed nowhere in the evidence but visible in the code

- **Lane width is hardcoded to 3.5m** in every generated ring segment (`ring.py:83`,
  `"a":"3.5"`), rather than reusing the real OSM-derived width hierarchy that already exists in
  `ultimate_pipeline/enrichment/lane_width_policy.py` (the same module GAP-001/GAP-019 already
  discuss). For a candidate specifically aimed at improving map fidelity, generating fixed-width
  lanes is a real, if secondary, fidelity gap worth closing before this could feed a
  `production_candidate`-profile map.
- **Elevation Hermite fit assumes zero grade at both anchor endpoints** (`ring.py:77`,
  `hermite_coefficients(z_start, 0.0, z_end, 0.0, length)`), rather than reading the true grade of
  the source road at the anchor point. This means a ring segment's elevation profile matches the
  anchor's *height* but not necessarily its *slope*, which could introduce a small kink in the grade
  (not the position) at the seam for roundabouts with meaningful elevation change. Low real-world
  impact for a mostly-flat area but worth documenting as a known simplification, not silently
  assumed away.

Neither of these is a correctness bug — both are reasonable, bounded scope choices for a first
candidate — but neither is mentioned in `known_limitations` in Codex's own evidence, which only lists
integration/CARLA/full-map-payload gaps. Recommend adding both to the known-limitations list for
completeness.

### 4. Residual gap vs. the GAP-011-style concern: lane-link matching is still order/index-based

`lane_links.py::map_lanes` pairs lanes by `sorted((abs(x), x))` order, not by geometric/heading
correspondence — the same class of limitation flagged for the general `lanelink_builder.py` in
`MAP_QUALITY_GAP_REGISTER.json` GAP-011. It is a real improvement over V1 in that it **fails closed**
on count mismatches instead of guessing, but for roundabouts with a genuine lane-count transition
partway around (an explicitly-out-of-scope case per the design docs), index-based pairing would still
be the eventual mechanism unless a more sophisticated mapper is built later.

## What remains genuinely unverified (correctly reported as INCOMPLETE, not silently passed)

Ingolstadt full-map validation, second-city validation, and any CARLA-runtime check are all correctly
marked `INCOMPLETE`/`NOT_RUN` rather than inferred or assumed. This review could not independently
verify these either, for the same reason Codex couldn't: the sparse-checkout worktree does not
materialize `campaigns/` (the real ~149MB pinned XODR is absent). This is a genuine, still-open gap in
this candidate's evidence, not something either agent should claim resolved.

## Review verdict

```text
SAFETY_CLAIMS:
  VERIFIED (all independently re-checked: no map-of-record mutation, no frozen-evidence mutation,
  no pipeline wiring, no CARLA execution)

DESIGN_QUALITY:
  SUBSTANTIALLY_IMPROVED_OVER_V1 (correctly addresses forced-circle, multi-lane collapse, idealized
  attachment poses, and tangent-discontinuity concerns from GAP-008; does not yet address splitter
  islands, boundary clipping, or lane-count transitions around the ring -- all explicitly
  acknowledged as out of scope, not silently ignored)

SELF_REPORTED_EVIDENCE_ACCURACY:
  ONE_CONFIRMED_DISCREPANCY (legacy_roundabout test count claimed as 39, independently verified as
  44 -- an under-claim, not a hidden failure; also a minor 5825-vs-5830 inconsistency between two of
  Codex's own evidence files, resolved in favor of the independently-reproduced 5830)

CODE_QUALITY_FINDING:
  ONE_INTERNAL_CONTRACT_CONTRADICTION (core.validate_lane_mapping vs lane_links.map_lanes/
  validate_links disagree on whether a real -1->-1 lane mapping is ever valid -- recommend resolving
  before further integration work)

UNDISCLOSED_SIMPLIFICATIONS:
  TWO_FOUND (hardcoded 3.5m lane width instead of reusing lane_width_policy.py; zero-grade Hermite
  elevation boundary condition instead of reading the source road's true grade at the anchor --
  neither is a bug, both should be added to known_limitations)

INTEGRATION_READY:
  NO (by design and by Codex's own correct self-assessment -- this is an offline analysis/candidate
  library, not yet wired to any release profile; T-007 in PRODUCTION_MAP_TASK_GRAPH.json remains open)

RECOMMENDATION:
  ACCEPT AS A CANDIDATE, NOT AS A COMPLETE T-007. Merge-worthy as an isolated, non-wired module once
  the API contradiction (finding 2) is resolved and known_limitations is updated (finding 3). Full
  T-007 completion still requires: materializing real Ingolstadt/second-city payloads and re-running
  against them, adding the missing roundabout fixture types from
  docs/map_quality/JUNCTIONS_AND_ROUNDABOUTS.md, and an explicit decision on lane-width provenance
  reuse before this could ever back a production_candidate-profile map.

NEXT_ADMISSIBLE_TASK:
  Codex: resolve the validate_lane_mapping/map_lanes contradiction (finding 2) and update
  known_limitations (finding 3). Do not begin full-map Ingolstadt materialization until the operator
  decides whether this sparse-checkout worktree model is the intended pattern for future MQ-B tasks
  (it works, but every task paying this same "payload unavailable" cost separately is worth a
  deliberate decision, not an accumulating default).
```
