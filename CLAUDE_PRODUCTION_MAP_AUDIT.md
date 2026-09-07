# Claude Production Map Quality Audit

Role: architecture and acceptance authority for `lemoniadowyjohn/carla-control-suite`'s transition
from a validated research release toward a genuinely production-grade CARLA map-generation system.
This document is the master narrative for the MQ-A audit (sections A0-A15). It does not implement
core algorithms (that's Codex's role) and does not do mechanical migration (OpenCode's role) — it
establishes what's actually true about the current system and what needs to happen next.

**Every finding below was independently verified against live code, live CI, or live data this pass
— none of it is repeated from the audit brief without re-derivation.** Five parallel research agents
performed deep, read-only code audits across the pipeline; their findings, cross-checked and
synthesized, are what this document and its companion artifacts are built from.

## A0 — Authority and provenance

The audit brief's own stated baseline was wrong: `Expected release SHA: f195ba0b5d6df3f085573c5e996ff9d0f11a975f`
**does not exist anywhere in this repository** (`git cat-file -t` fails; `git log --all` finds no
match). Per the brief's own explicit rule ("If release authority has moved: STOP mutation. Report:
`BASELINE_AUTHORITY_CHANGED` and require re-baselining"), this was surfaced to the operator before
any further work proceeded, rather than silently substituted or ignored.

The operator explicitly re-baselined this audit against `review/claude-independent-audit-20260906` @
`2e020d9b8ed5e21ae0a2e4a93ef1e71116082eef` — a direct descendant of the actually-real
`stabilize/research-release-20260905` (`33d5d815`) plus 4 additional commits (an independent review
packet, 7 polish fixes, and 2 provenance fixes). This exact SHA has a **fully green 6-job CI run**
(package/wheel smoke, offline tests, research provenance, thesis RQ contract, governance integrity,
repository health — run `34044481507`, `pull_request`-triggered, completed 2026-09-06T16:08:15Z,
10m19s), re-confirmed live via `gh run view` immediately before this document was written. Every one
of the brief's 9 "expected state" narrative claims (six gates green, CARLA runtime NOT_RUN, RQ3
NOT_RUN, RQ5 NOT_RUN) independently checks out true against this corrected SHA — only the specific
SHA citation was stale.

Full detail: `reports/production_readiness/20260906T170000Z/A0_AUTHORITY.json`.

## A1 + A13 — Pipeline dependency graph and software architecture

Full detail: `reports/production_readiness/20260906T170000Z/PIPELINE_DEPENDENCY_GRAPH.json`,
`docs/architecture/TARGET_PIPELINE_STAGE_GRAPH.md`.

The single most important architectural finding of this audit is **negative**: reordering pipeline
stages would *not* fix Stage-6's containment problem. Every "unsafe" geometry mutator gated behind
`EXPERIMENTAL_UNSAFE` is internally incomplete or buggy at the function level — a missing companion
`x`/`y` recompute after `hdg`-only mutation, a `paramPoly3` arc-length math defect (partially patched
2026-09-04, not yet re-verified end-to-end) — independent of which stage calls them or when. The path
to safely relaxing containment is fixing these internal defects, not moving stage boundaries.

Two concrete, evidence-backed reordering improvements ARE real: moving buildings/signals/crosswalks to
run after lane generation and structural freeze (they currently run in stage 4, before either exists,
with no code dependency found requiring that order), and promoting the already-existing but
implicit geometry-freeze mechanism to an explicit, first-class pipeline stage.

The global-injection architecture pattern (`_inject_main_pipeline_globals()` in all 13 stage modules,
untyped `self.semantic_state` mutated by 4 different stages) is confirmed real and a genuine
migration target — but a large, risky one. `self.semantic_state` is the correct first migration
target; stages 5, 6, and 8 (the containment mechanism and the most entangled stage, respectively)
should be migrated last, after the pattern is proven safe elsewhere.

## A2 + A3 — Map-of-record forensic audit and horizontal geometry

Full detail: `reports/production_readiness/20260906T170000Z/`, `MAP_QUALITY_GAP_REGISTER.json`
GAP-002, GAP-003, GAP-015, GAP-018, GAP-022, GAP-023.

The pinned map-of-record (`ingolstadt_perception_map_of_record_20260905_202847.xodr`, sha256
`2ca342d8...`) was verified byte-for-byte against the registry before any analysis proceeded. The
27 isolated lane components were re-derived from a full XML chain-walk (not assumed from prior
memory) and confirmed as a systematic **LANELINK_DEFECT**: every isolated lane is a road's outermost
driving lane, and its junction connection's laneLink set always covers one fewer lane than the
incoming road has. This independently re-confirms a prior investigation's "do not build" conclusion
(fixing this for real means fabricating geometry that doesn't exist in the source data) — this audit
does not propose reopening that decision.

The 134 CARLA-compatibility warnings were confirmed to be exactly what they were claimed to be: a
benign converter quirk (near-zero-length junction-connector stub roads whose `length` attribute was
floored to 0.1m while the true planView geometry sum stayed near-zero) — the looser,
CARLA-import-risk-calibrated gate reports zero issues on the same 134 roads.

**The single most significant new finding from this section**: 20.3% of junction-connector
road-boundary links (9,176 of 45,178) have a geometric position offset ≥ 0.05m, with a median offset
of **exactly one lane-width (3.5m)** — and this is completely invisible to `valid_for_experiments`
because the relevant continuity check structurally routes junction-connector links into a separate,
non-gating bucket by design. This strongly suggests connector reference-lines are anchored to the
wrong lane-boundary/index in roughly one in five junction connections — see GAP-002.

A separate, previously-cited claim ("~9-10 road-level graph-islands components") could **not** be
reproduced against the current pin (measured: 1 component, 0 islands) — flagged as an unreconciled
discrepancy, not silently resolved either way. A genuine, isolated 180-degree tangent reversal was
found and independently verified (road 45622, a non-monotonic `paramPoly3` parametrization) — a real
defect worth a dedicated regression fixture regardless of its low aggregate frequency.

## A4 + A5 — Junctions, connectors, roundabouts

Full detail: `docs/map_quality/JUNCTIONS_AND_CONNECTORS.md`, `docs/map_quality/JUNCTIONS_AND_ROUNDABOUTS.md`.

`ConnectorValidator`'s narrowness was confirmed exactly as the brief suspected — its own source
comments admit lane-section and attachment-pose validation are "SKIP for now." This is mitigated in
practice (connector rebuild is off by default; a broader `JunctionIntegrityGate` covers dangling
refs) but remains a real gap when the rebuild feature is used at all.

Roundabout reconstruction forces every roundabout into a perfect single-lane circle, quantifiably
risky against real data (25% of lane-tagged OSM roundabouts in the pinned source are multi-lane) —
but this severity is bounded by `ENABLE_ROUNDABOUT_RECONSTRUCTION` defaulting `False` in every named
release profile, meaning the live map's roundabout geometry currently passes through from the
upstream converter largely unmodified by this codebase.

## A6 + A7 — Lanes, elevation, structures

Full detail: `MAP_QUALITY_GAP_REGISTER.json` GAP-001, GAP-009, GAP-010, GAP-011, GAP-017, GAP-019, GAP-025.

**The single most consequential finding of the entire audit**: lane *count* is never derived from
OSM data at all. Every road, regardless of its real OSM `lanes=` tag, receives exactly one driving
lane per side. Width has a real 4-tier OSM→inferred→fallback hierarchy; count does not. This directly
contradicts the "highest-fidelity map" goal more than any other single finding in this audit — a
genuinely 4-lane arterial and a 1-lane service road are structurally identical in the output.

The bridge/tunnel "deck_linear" elevation policy (confirmed live, matches commit `e3f91dbc`) does not
use any independent deck-height/clearance data source — it linearly interpolates between the same
ground-terrain DEM sampled at the structure's two endpoints. This works reasonably when the endpoints
happen to be correctly sampled, but nothing validates that an endpoint sample represents "top of
abutment" rather than "ground beneath the abutment," and no minimum deck-to-ground separation is
ever checked.

## A8 + A9 + A10 + A12 — OSM correspondence, semantics, visual QA, generalization

Full detail: `MAP_QUALITY_GAP_REGISTER.json` GAP-005, GAP-006, GAP-007, GAP-013, GAP-014.

Position-specific OSM metadata (turn-lane hints, regulatory signs) is confirmed to propagate through
pure street-name matching in the live pipeline path, with no confidence scoring or ambiguity
handling — a real, reachable risk given one street name commonly spans many distinct XODR segments.
`crosswalk_writer.py` is a working counter-example proving the team already knows how to do
geometric correspondence correctly; it just wasn't applied here.

A genuine duplicate-class bug was found: two different `SemanticOverlapChecker` classes exist under
different filenames — the live-wired one is a non-geometric co-attachment heuristic, and the real
Shapely polygon-intersection implementation is dead code, imported nowhere.

The offline visual/collision QA system (Phase J: OSM2World/Blender/FBX/collision/detached-slab
checks) is real and has genuine execution evidence — not merely scaffolded — but has never been wired
into `main_pipeline.py` and has only ever been validated at a 19-vertex smoke-test scale, never
against the actual ~149MB map-of-record.

**No second-city fixture exists anywhere in this repository.** Munich references found in the code
are illustrative docstring examples and unwired HPC config stubs, never backed by real acquired data.
Every structural algorithm in this pipeline has been validated on Ingolstadt alone. Two narrow,
properly-gated Ingolstadt hardcodes were found (an elevation fallback and a UTM-zone default, both
requiring non-default opt-ins or near-unreachable inputs to matter) — no unconditional
city-name-branching was found anywhere in core algorithm code.

## A11 — Production acceptance semantics

`PRODUCTION_MAP_QUALITY_CONTRACT.yaml` unifies the existing, extensive quality-gate system (not
duplicates it) into three profiles: `research_release` (current operating mode, bounded caveats
acceptable), `production_candidate` (fails closed, no SKIPPED-as-PASS), `runtime_certified` (requires
a live CARLA certificate — currently `BLOCKED_EXTERNAL`, confirmed via the prior Stage-A
runtime-admission audit this session: zero self-hosted CI runners registered, no CARLA process or
listening socket). A `WAIVED` status class with a mandatory identifier/owner/evidence/rationale/
expiration schema replaces anonymous warning suppression.

## A12 — see A8-A10 above (combined in the same research pass)

## A14 — Documentation information architecture

`DOCS_INFORMATION_ARCHITECTURE.md` and `docs/index.md`. A genuinely important discovery here: the
`docs/` tree has **already evolved substantially past the brief's originally-proposed skeleton**,
built by prior work on this branch — real `docs/research/`, `docs/runtime/`, `docs/hardening/`
content already exists, organized differently than proposed. Rather than creating a competing
parallel structure, this pass documents the reconciled target and the real current state, and
corrects one genuinely stale claim in `README.md` (a CI-status line that predated this session's own
live verification of the current HEAD's green run).

## A15 — Implementation task graph

`PRODUCTION_MAP_TASK_GRAPH.json` (26 tasks) and `PRODUCTION_MAP_REMEDIATION_PLAN.md`. Every task maps
to one or more gap-register entries, has explicit dependencies (verified acyclic), an owner
(CLAUDE/CODEX/OPENCODE/OPERATOR), affected files, tests, an expected metric, a stop condition, a
rollback plan, and evidence. Zero tasks require live CARLA. The most foundational task (T-001, fixing
GAP-001's lane-count defect) has no dependencies and is the recommended starting point.

## Full gap register

`MAP_QUALITY_GAP_REGISTER.json` — 31 entries: 7 P0, 11 P1, 10 P2, 3 P3. Every entry cites concrete
evidence (file:line where applicable) and is assigned an owner. No entry is marked `UNKNOWN` where a
more specific classification was achievable through direct investigation.

## What this pass explicitly did not do

- Did not implement any core geometry/topology/lane algorithm (Codex's role, per the task graph).
- Did not move any historical documentation file (OpenCode's role, per `DOCS_INFORMATION_ARCHITECTURE.md`).
- Did not touch frozen thesis evidence under `submission/`.
- Did not promote a new map-of-record.
- Did not start, stop, or connect to CARLA at any point in this pass.
- Did not modify GitHub branch protection, default-branch settings, or any repository settings.
- Did not attempt to reopen the "27 isolated lanes" question with a geometric fix — the prior
  "fabricating geometry" conclusion was independently re-verified, not re-litigated.

---

## Final Verdict

```text
BASE_AUTHORITY:
  INCOMPLETE (prompt's stated SHA does not exist; RESOLVED via explicit operator re-baseline to
  review/claude-independent-audit-20260906 @ 2e020d9b, which independently satisfies every one of
  the prompt's own expected-state claims)

MAP_QUALITY_ARCHITECTURE:
  INCOMPLETE (extensive, real quality-gate system exists and is largely sound; genuinely
  production-grade requires closing the P0 gaps below first, most critically GAP-001 lane-count
  fidelity and GAP-002 the newly-quantified connector-offset defect)

STAGE_ORDER:
  ACCEPTABLE (reordering stages does not fix the containment problem -- the root causes are
  internal defects in individual unsafe mutators, not sequencing; two narrower, real reordering
  improvements are identified and do not require a full stage-order overhaul)

HORIZONTAL_GEOMETRY:
  NEEDS_REMEDIATION (C0/C1 internal continuity is excellent -- 0 seams across 165,130 boundaries --
  but junction-connector boundary continuity has a 20.3% out-of-tolerance rate invisible to the
  current gate, plus one confirmed 180-degree tangent-reversal defect)

JUNCTIONS_CONNECTORS:
  NEEDS_REMEDIATION (ConnectorValidator's pose/lane-section checks are confirmed disabled;
  JunctionIntegrityGate covers dangling refs but not direction/pose correctness)

ROUNDABOUTS:
  NEEDS_REMEDIATION (multi-lane collapse and perfect-circle forcing confirmed, quantified against
  real data at 25% of lane-tagged OSM roundabouts; severity currently bounded by
  reconstruction being off by default in every release profile)

LANES:
  NEEDS_REMEDIATION (lane WIDTH has a real OSM-derived hierarchy; lane COUNT is never OSM-derived
  at all -- this is the single highest-priority structural-fidelity gap found in this audit)

ELEVATION_STRUCTURES:
  NEEDS_REMEDIATION (thorough, well-thresholded elevation gates exist; bridge/tunnel deck
  elevation has no independent height/clearance data source and no deck-to-ground-separation check;
  superelevation/crossfall confirmed absent, documented as a deliberate scope question for the
  operator rather than a silent gap)

OSM_XODR_CORRESPONDENCE:
  NEEDS_REMEDIATION (crosswalks have genuine geometric correspondence; turn-lanes and regulatory
  signs propagate via unscored, ambiguity-blind street-name matching -- a real, reachable risk)

SEMANTIC_FIDELITY:
  NEEDS_REMEDIATION (a real, working polygon-intersection overlap checker exists but is dead code;
  the live-wired checker is a much weaker heuristic; no OSM-source-vs-generated completeness metric
  exists for any semantic object type)

OFFLINE_PRODUCTION_GATE:
  NEEDS_REMEDIATION (the gate system itself is extensive and largely well-designed; unifying it
  into fail-closed profiles per PRODUCTION_MAP_QUALITY_CONTRACT.yaml, and closing the P0/P1 gaps
  it depends on, is required before a production_candidate claim can be trusted)

LIVE_CARLA:
  NOT_RUN

PRODUCTION_READY:
  NO

IMPLEMENTATION_PLAN_READY:
  YES

FIRST_BLOCKER:
  GAP-001 (lane count never derived from OSM) -- the most foundational structural-fidelity defect,
  with the largest number of downstream tasks depending on it (T-007, T-015, T-017, T-018 in
  PRODUCTION_MAP_TASK_GRAPH.json all block on it).

NEXT_ADMISSIBLE_TASK:
  T-001 -- "Derive driving-lane COUNT from OSM lanes:*/lanes= tags instead of always emitting 1 per
  side" (see PRODUCTION_MAP_TASK_GRAPH.json for the full task definition: affected files, tests,
  expected metric, stop condition, rollback). Owner: CODEX. No dependencies. Does not require live
  CARLA.
```

This Claude session does not begin T-001 or any other implementation task. Per the audit brief:
Codex implements core algorithms; this document and its companions are the architecture and
acceptance authority's output, ready for that work to begin.
