# Execution Plan — 2026-09-07

Consolidates: `MAP_QUALITY_GAP_REGISTER.json` (42 entries, was 31), `PRODUCTION_MAP_TASK_GRAPH.json`
(26 tasks), the roundabout V2 independent review (`feature/roundabout-reconstruction-v2-20260907`),
and a subsequent externally-sourced architecture analysis (spot-checked 2/2 on concrete claims,
integrated as GAP-035 through GAP-042, with unverified items explicitly marked so).

## Status: is any of this done?

**Only one thing has real, committed implementation: the Roundabout Reconstruction V2 candidate**
(`feature/roundabout-reconstruction-v2-20260907`, independently reviewed, substantively fixes
GAP-008's forced-circle/multi-lane-collapse defects, but is unwired and has 3 residual findings of
its own — GAP-032/033/034). Everything else in the gap register, including the two newly-confirmed
bugs (GAP-035 geometry backfill, GAP-036 sidewalk=no), is still open. This plan does not re-litigate
that — it organizes what's left.

## Ownership split (unchanged from PRODUCTION_MAP_TASK_GRAPH.json)

- **CLAUDE** (this session): discovery, verification, contract/architecture design, independent
  review of Codex's output, cross-cutting decisions. Already done: the original 31-gap audit, the
  roundabout V2 review, GAP-015's resolution, spot-checking the new document's claims, this plan.
- **CODEX**: core algorithm implementation.
- **OPENCODE**: mechanical engineering — wiring already-built-but-unwired modules into gates/pipeline,
  deprecation migration, documentation housekeeping, evidence-file corrections.
- **OPERATOR**: data acquisition (second-city fixture), policy decisions (superelevation scope),
  environment actions (self-hosted CI runner).

## Priority waves (supersedes the informal grouping in PRODUCTION_MAP_REMEDIATION_PLAN.md)

The new document's suggested "geometry kernel first" ordering and this session's original "lane
count first" ordering are **not actually in conflict** — they're largely orthogonal (lane *count*
policy doesn't depend on which geometry-primitive math computes a road's *shape*). Both can start
immediately, in parallel tracks.

### Wave 1 — start immediately, no dependencies (parallelizable)

| Task | Gap(s) | Owner | Why first |
|---|---|---|---|
| Canonical geometry-primitive evaluator | GAP-037, GAP-035 | CODEX | Highest-leverage fix: retroactively fixes GAP-035 and de-risks every module that currently reimplements geometry math (roundabout_v2, crosswalk_writer, structure_classifier, geometry_validator) |
| Lane count from OSM tags | GAP-001 | CODEX | Most consequential single fidelity gap; nothing else in the lane/roundabout/turn-lane space can be done properly without it |
| sidewalk=no fix | GAP-036 | CODEX | Small, isolated, confirmed real, no dependencies |
| Confirm-then-fix: GAP-038/039/040/041/042 | GAP-038 to GAP-042 | CODEX | Each is cheap to confirm (a targeted grep+read) before deciding whether to fix; bundle as one investigation pass |
| Roundabout V2 API contradiction + limitations doc | GAP-032, GAP-033, GAP-034 | CODEX | Small, isolated, already fully scoped by the independent review |
| Second-city fixture acquisition | GAP-007 | OPERATOR | No code dependency; the longest-lead-time item, should start now so it's ready when Wave 2/3 need it |
| Wire `check_junction_connection_coverage.py` into gates | GAP-012 | OPENCODE | Real, tested, already-built diagnostic just sitting unused |
| Deprecation-migration pass (see below) | — | OPENCODE | Independent of all code-fix work |

### Wave 2 — depends on Wave 1

| Task | Gap(s) | Owner | Depends on |
|---|---|---|---|
| ConnectorValidator real checks + connector-offset gate | GAP-002, GAP-004 | CODEX | Geometry evaluator (cleaner to build pose-checks on top of one canonical evaluator) |
| Junction lane-link geometry-awareness | GAP-011 | CODEX | Geometry evaluator |
| Turn-lane geometric generation, cycle lanes | GAP-017, GAP-025 | CODEX | Lane count from OSM |
| Lane-count-change gate, lane provenance metadata | GAP-020, GAP-019 | CODEX | Lane count from OSM |
| Roundabout multi-lane preservation in reconstruction proper | GAP-008 | CODEX | Lane count from OSM (roundabout_v2 already partially does this independently) |
| Bridge/tunnel deck-height model | GAP-009, GAP-010 | CODEX | Geometry evaluator (structure_classifier's sampler is one of the fragmented implementations) |
| Spatial OSM↔XODR correspondence engine | GAP-005 | CODEX | Geometry evaluator (needs real curve-aware matching, same pattern as crosswalk_writer.py) |

### Wave 3 — depends on Wave 2's correspondence engine

| Task | Gap(s) | Owner |
|---|---|---|
| Regulatory signs, traffic-light source-truth priority, speed-limit precedence, turn restrictions | GAP-005 (extension), GAP-040 | CODEX |
| OSM-vs-generated completeness metric | GAP-014 | CODEX |

### Wave 4 — housekeeping and unification, can interleave with any wave

| Task | Gap(s) | Owner |
|---|---|---|
| Dead-code retirement (`quality/semantic_overlap.py` wiring swap, `tools/junction_connector_rebuild.py` retirement) | GAP-006 | CODEX (wiring) + OPENCODE (retirement) |
| Docs deprecation migration | — | OPENCODE |
| `pipeline_health_summary`-style production fallback contract enforcement | GAP-030, GAP-041 | CODEX |
| Phase J visual QA wiring + full-scale run | GAP-013 | CODEX |
| StageContext migration (start with `self.semantic_state`) | GAP-016 | CODEX |
| Duplicate/conflicting-connection junction check | GAP-021 | CODEX |
| Dead elevation-anomaly check, curvature-anomaly microsegment artifact | GAP-022, GAP-023 | CODEX |
| Heading-smoothing guard end-to-end re-verification | GAP-024 | CODEX |
| z-fighting detector | GAP-027 | OPENCODE |
| Stale-comment fixes | GAP-028, GAP-029 | OPENCODE |
| Superelevation/crossfall scope decision | GAP-030 | OPERATOR |

### Not scheduled — genuinely blocked

RQ3/RQ5(a) live capture, runtime certification, anything requiring live CARLA. Full-scale scene/tiling
architecture (the new document's M27) is real future work but is downstream of every wave above —
not scheduled until Waves 1-3 land and the second-city fixture exists to test against.

## Deprecation-migration safety rule (for OpenCode, non-negotiable)

Before any file is moved to a `deprecated/` location, it must be classified as **exactly one** of:

1. **DEPRECATE** — genuinely superseded: a live, current implementation exists elsewhere, the
   candidate file is provably unreferenced (no import anywhere in `ultimate_pipeline/`, `tools/`,
   `scripts/`, or any test), and moving it changes no runtime behavior. Requires: a grep-based
   unreferenced-anywhere proof, pasted into the migration commit message.
2. **UNWIRED_BUT_NEEDED** — real, tested, working code that simply isn't called from the live
   pipeline yet. **Never deprecate this.** Wire it in instead (see Wave 1's
   `check_junction_connection_coverage.py` as the template case), or leave it exactly where it is
   with a comment explaining why it's not yet wired.
3. **UNCERTAIN** — cannot confidently classify. Do not move. Flag for CLAUDE or the operator.

Known DEPRECATE candidates (already confirmed this session, safe to act on):
- `ultimate_pipeline/quality/semantic_overlap.py` — **only after** GAP-006's wiring swap lands (once
  `check_semantic_overlap.py`'s gate calls this real implementation, the naive heuristic in
  `check_semantic_overlap.py`'s old code path becomes the actual deprecation candidate, not this file
  — do not deprecate the *real* implementation).
- `ultimate_pipeline/tools/junction_connector_rebuild.py` — confirmed not called from
  `stage_05_geometry.py` or anywhere else in the live pipeline; the `topology/` version is canonical.
  Verify no test imports the `tools/` version specifically before moving.
- Root-level `docs/02_CLAUDE_C0_REVIEW_PROMPT.md`, `docs/N04_CLAUDE_C0_PACKET.md`,
  `docs/N19_CLAUDE_C1_PACKET.md`, `docs/R05_CARLA_0916_CROSSWALK_OBJECT_SCHEMA.md` — historical
  handoff packets, already identified in `DOCS_INFORMATION_ARCHITECTURE.md` as
  `docs/deprecated/` candidates.

Known UNWIRED_BUT_NEEDED (do not deprecate, wire in instead):
- `ultimate_pipeline/quality/check_junction_connection_coverage.py` (Wave 1 task above).
- `ultimate_pipeline/quality/semantic_overlap.py` (the REAL polygon-intersection implementation —
  wire it in, don't archive it; see the DEPRECATE entry above for the correct target).
- `ultimate_pipeline/tools/phase_j_osm2world_blender.py` and its J1-J8 modules — real, tested, just
  never called from `main_pipeline.py` (GAP-013).

Explicitly excluded from any sweep: everything under `submission/` (frozen thesis snapshot, see
`REPOSITORY_GOVERNANCE.md`), everything under `campaigns/`, `reports/post_audit_hardening/` (historical
evidence, append-only per governance policy).

## What Claude will do directly, now, without delegating

- Already done this pass: GAP-015 resolution, GAP-032/033/034 (roundabout review), GAP-035/036
  confirmation (spot-checks), this plan, the two prompt documents below.
- Will do on request, not proactively: re-verify GAP-038 through GAP-042 myself if Codex's
  "confirm-then-fix" pass reports back inconclusive results, or if the operator wants independent
  double-checking before those become committed fixes.

## Deliverables in this commit

- `MAP_QUALITY_GAP_REGISTER.json` — extended to 42 entries (was 31).
- `CODEX_EXECUTION_PROMPTS.md` — ready-to-send prompts, organized by wave.
- `OPENCODE_EXECUTION_PROMPTS.md` — ready-to-send prompts, deprecation safety rules embedded.
- This file.
