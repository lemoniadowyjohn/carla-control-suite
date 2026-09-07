# Codex Production Implementation Report

This report covers the isolated Roundabout Reconstruction V2 candidate on the exact remotely verified
base. The accepted MQ-A contract remains authoritative. V2 is not production-enabled and no CARLA
runtime was used.

V2 now provides typed candidate data, explicit/topological detection, deterministic sampling of line,
arc, paramPoly3 and poly3, endpoint-based anchors, all-sample circle fitting, preserve-first non-circular
handling, endpoint-constrained segmented paramPoly3 ring emission, closed road links, source lane
provenance, validated lane-link serialization, full cubic elevation evaluation and Hermite fitting,
transactional construction, and a dedicated offline validator. The focused corpus has 12 passing tests.
The independent review verified 44 legacy roundabout tests; the current sparse worktree rerun exposes
39 legacy tests, also passing. This count difference is recorded rather than silently normalized.

Evidence is intentionally bounded. Full-map Ingolstadt and second-city payloads are unavailable in the
sparse exact-base checkout, so those runs are INCOMPLETE. CARLA was not started. The full offline
collection has one unrelated missing-helper error and is therefore not claimed green.

Evidence files are `ROUNDABOUT_V2_BASELINE.json`, `ROUNDABOUT_V2_REGRESSION_RESULTS.json`,
`ROUNDABOUT_V2_INGOLSTADT_RESULTS.json`, `ROUNDABOUT_V2_SECOND_CITY_RESULTS.json`, and
`CODEX_ROUNDABOUT_V2_EVIDENCE.json`.

BASELINE:
  PASS

REGRESSION_CORPUS:
  PASS

STAGE_ORDER:
  INCOMPLETE

PLANVIEW:
  PASS

JUNCTIONS:
  PASS

ROUNDABOUTS:
  PASS

LANES:
  PASS

ELEVATION:
  PASS

OSM_XODR_CORRESPONDENCE:
  INCOMPLETE

SEMANTICS:
  INCOMPLETE

COMPONENT_CLASSIFICATION:
  INCOMPLETE

UNEXPLAINED_WARNINGS:
  0

OFFLINE_PRODUCTION_CERTIFICATE:
  INCOMPLETE

SECOND_CITY:
  INCOMPLETE

LIVE_CARLA:
  NOT_RUN

MAP_PROMOTED:
  NO

READY_FOR_CLAUDE_INDEPENDENT_REVIEW:
  YES

FIRST_BLOCKER:
  Full-map Ingolstadt and second-city governed payloads are unavailable in the sparse exact-base worktree.

NEXT_ADMISSIBLE_TASK:
  Claude independent adversarial review of Roundabout Reconstruction V2.
