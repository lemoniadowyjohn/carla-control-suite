# Roundabouts — Production Quality Contract

Status: gap analysis + proposed contract, informed by direct code audit as of baseline `2e020d9b`, cross-checked
against the real pinned OSM source (`campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm`).

## Files involved

- `ultimate_pipeline/topology/roundabout_rebuilder.py` (`RoundaboutRebuilder`) — detection + **tagging only**.
  Own docstring: "We don't aggressively rewrite geometry." Confirmed: only sets an `isRoundabout`/
  `type="roundabout"` XML attribute; never touches geometry.
- `ultimate_pipeline/topology/roundabout_reconstructor.py` (`RoundaboutReconstructor`, `_RoundaboutDetector`) —
  the actual geometry-rewriting implementation.
- Wiring: `ultimate_pipeline/pipeline_stages/stage_04_enrichment.py:127-155`.

## Current default: reconstruction is OFF everywhere

`ENABLE_ROUNDABOUT_RECONSTRUCTION` defaults `False` in **every** named release profile, including
`CARLA_RELEASE` and `VISUAL_RELEASE` (`ultimate_pipeline/config/settings.py`, 6 confirmed occurrences). Only
`RoundaboutRebuilder`'s lightweight tagging path runs unconditionally. **This materially bounds the practical
severity of every gap below**: the live/production map's roundabout geometry passes through largely as produced
by the upstream OSM→XODR converter, not as reshaped by `RoundaboutReconstructor`.

## What `RoundaboutReconstructor` does when enabled, and its confirmed failure modes

| Question | Finding |
|---|---|
| Perfect circle, or preserves OSM shape? | **Forces a perfect circle, unconditionally.** Computes one average radius from detected core roads' distances to an estimated center, builds a single `<arc>` for the full circumference. Original per-segment shape is discarded entirely — only used to estimate center/radius. |
| Preserves multi-lane roundabouts? | **No.** Always creates exactly one `right` driving lane, unconditionally. No code path reads per-segment lane counts from the source roads. |
| Preserves OSM lane counts at each segment? | No — see above. |
| Entry/exit attachment — real meeting points or idealized? | Idealized. Recomputes `contactPoint` via a coarse half-plane angle test (`atan2` of the incoming road's last point relative to center), not a true nearest-point/pose match to the new circle. `laneLink` is stubbed with hardcoded `from="-1" to="-1"` if absent, regardless of actual lane topology. |
| Tangent discontinuities at entry/exit? | Confirmed likely, never checked. The circle's attach point is fixed by construction, independent of any incoming road's actual heading. Only elevation (z) discontinuities are smoothed near the seam (best-effort, wrapped in try/except); horizontal/heading continuity is never addressed. |
| Splitter islands? | Not handled at all. No island/median code anywhere; the single-lane-per-direction model has no room to represent one even conceptually. |
| Pedestrian crossings / partial (boundary-clipped) roundabouts? | Not handled. No crossing-aware code. No boundary-clip detection — a roundabout missing some approach roads or an incomplete ring due to tile/map-boundary clipping would still be forced into a full closed circle. |

## Quantified real-data risk (if reconstruction were ever enabled by default)

The pinned OSM source has **135 `junction=roundabout`-tagged ways, 81 with an explicit `lanes` tag, of which 20
(25%) are multi-lane** (2 or 3 lanes) — including named roundabouts "Gymnasiumkreisel," "Möbel-Gruber-Kreisel,"
"Audi-Ring," and "Lana-Grossa-Kreisel." All 20 would be collapsed to single-lane if reconstruction ran.

## Test fixture coverage (44 tests total across both modules)

| Fixture type | Present? |
|---|---|
| Simple one-lane roundabout | Yes |
| Multi-lane roundabout | **No** |
| Elliptical/non-circular roundabout | **No** |
| Malformed OSM roundabout input | Partial — only structural malformation (missing junction element), not genuinely malformed/self-intersecting geometry |
| Partial/boundary-clipped roundabout | **No** |
| Roundabout with pedestrian crossings | **No** |
| Roundabout with a lane-count change partway around | **No** — the single-lane model has no representation for this concept at all |

## A stale-comment finding worth fixing regardless of the reconstruction decision

`check_junction_connection_coverage.py`'s own comment implies roundabout junctions are "wholesale-rewritten
elsewhere" and excludes them from its own gap analysis on that basis. This is **inaccurate** relative to the
confirmed default-off state — a minor, low-effort documentation fix (or a runtime check of the actual flag
value instead of an assumption) worth including in any pass that touches this file.

## Design target for a production roundabout representation

Per the audit brief's explicit instruction, the target is **not** "force every roundabout to a perfect circle."
A production-grade reconstruction, when eventually built, should preserve:

- OSM roundabout centerline geometry where usable (fit a smooth curve constrained by the real point cloud,
  not replace it with a single average-radius arc).
- Actual entry/exit attachment points, computed from genuine nearest-point-on-curve geometry against the
  connecting roads' real endpoints and headings — not a half-plane angle heuristic.
- Per-segment lane count and width, preserved from OSM where available (reusing the same OSM-lane-count-parsing
  logic that already exists for `lane_width_policy.py`, which currently is used only for a width-per-lane
  divisor and never to determine lane cardinality — see `MAP_QUALITY_GAP_REGISTER.json` GAP-001, the same root
  defect affecting all lane generation, not just roundabouts).
- One-way direction and lane continuity through entry/exit.
- Entry/exit lane mappings validated the same way any other junction's laneLinks should be (see
  `JUNCTIONS_AND_CONNECTORS.md`'s production connector contract).
- Tangent continuity at every entry/exit seam.
- Road elevation, junction semantics.

Where reconstruction genuinely is required (e.g., self-intersecting or topologically broken source geometry),
prefer geometry fitting constrained by actual attachment poses over forcing a canonical shape.

## Required new fixtures before this can be called production-ready

Simple one-lane roundabout (existing); multi-lane roundabout; elliptical/non-perfect-circle case; malformed OSM
roundabout; partial roundabout at a map boundary; roundabout with pedestrian crossings; roundabout with a
lane-count change partway around. See `PRODUCTION_MAP_TASK_GRAPH.json` for the corresponding implementation
task.
