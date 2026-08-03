# Ingolstadt Map-Quality Improvement Campaign V2

## Objective

Produce a new OSM→OpenDRIVE candidate that is semantically different from candidate `c8419f8c`, preserves valid network content, and measurably improves structural quality and manual-reference comparability.

This is an implementation campaign. Do not rerun verification against the unchanged candidate.

## Baseline

The completed verification campaign established:

- offline replay: PASS
- stage contracts: PASS
- determinism: PASS
- content preservation: PASS
- structural domain gap: REPRODUCED
- full-map improvement: MIXED_RESULTS_REVIEW_REQUIRED
- perception: BLOCKED

The replay candidate is canonically equivalent to the earlier pinned candidate, and therefore reproduced the historical domain-gap metrics.

## Mandatory First Checks

Record:

- current branch
- current commit
- baseline candidate path
- baseline byte hash
- baseline canonical semantic hash
- authoritative OSM hash
- manual reference hashes
- DEM hash
- metric-definition-lock hash
- threshold-registry hash

Create a dedicated branch and worktree:

- `improvement/ingolstadt-map-quality-v2-YYYYMMDD`

Do not modify prior evidence or accepted candidates.

## Work Package 1 — Coordinate Truth

Determine the actual coordinate frame of:

- authoritative OSM
- raw XODR
- pinned XODR
- manual Grid0821
- manual Grid0828
- tile grid
- domain-gap correspondences

Resolve the discrepancy between the candidate's observed `tmerc(lat_0=0, lon_0=0)` behaviour and its `EPSG:32632` header.

Separate:

- metadata correction
- actual coordinate transformation
- local-origin translation
- alignment transformation

Do not change only the header and claim reprojection.

Produce distributed control-point and bounding-box evidence.

## Work Package 2 — Connectivity

Implement and validate:

- road predecessor/successor links
- road/junction reciprocity
- contactPoint correctness
- junction connection consistency
- component reachability
- route continuity

Never infer links from ID proximity alone.

Required targets:

- dangling links = 0
- invalid reciprocal links = 0
- invalid contactPoints = 0
- unexplained disconnected components = 0

## Work Package 3 — Elevation

Apply the authoritative DEM after horizontal geometry freeze.

Implement:

- structure classification
- piecewise elevation profiles
- coverage validation
- C0 continuity
- bounded grade
- bridge/tunnel handling
- seam validation

Release mode must prohibit a global flat fallback.

## Work Package 4 — Grounded Semantics

Add provenance-backed enrichment for:

- road classes
- buildings
- barriers
- poles
- vegetation
- crosswalks
- signs
- signals
- controllers
- speed limits
- turn restrictions

Use deterministic IDs and idempotent writers.

Every element must identify its source and mapping confidence.

## Work Package 5 — Tile and Extent Reconciliation

Reconcile both map families to:

- one CRS
- one unit system
- one declared analysis extent
- one tile grid
- one clipping policy

Recompute tile overlap only after coordinate reconciliation.

Explain every excluded tile or region.

## Candidate Acceptance

The new candidate is eligible for evaluation only when:

- canonical semantic hash differs from `c8419f8c`
- authoritative inputs unchanged
- horizontal freeze passes
- lane invariants pass
- no unacceptable road/lane loss
- connectivity does not regress
- elevation is no longer globally flat
- semantic elements have provenance
- all mandatory tests pass

## Locked Evaluation

Use the existing P04 metric-definition lock and threshold registry unchanged.

Compare:

- baseline candidate
- new candidate
- run_11 historical artifact
- manual Grid0821
- manual Grid0828

Report:

- coverage
- geometry
- topology
- connectivity
- lanes
- elevation
- semantics
- tiles
- content preservation
- domain-gap statistics

Do not declare improvement from a matched subset alone.

Do not hide maximum errors behind means.
Do not reduce errors by removing difficult roads or regions.

## Required Final Verdict

Return exactly one:

- `NEW_CANDIDATE_FULL_MAP_IMPROVEMENT_VERIFIED`
- `NEW_CANDIDATE_STRUCTURALLY_IMPROVED_DOMAIN_GAP_MIXED`
- `NEW_CANDIDATE_NO_MEASURABLE_IMPROVEMENT`
- `NEW_CANDIDATE_REGRESSION`
- `IMPROVEMENT_CAMPAIGN_BLOCKED`

Perceptual readiness remains blocked until a cooked map and comparable sensor datasets exist.

## Immediate Priority

The immediate engineering priority is coordinate truth and topology connectivity. They affect nearly every later domain-gap metric and should be resolved before investing heavily in semantic or perceptual comparisons.