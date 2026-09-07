# Junctions and Connectors — Production Quality Contract

Status: gap analysis + proposed contract, informed by direct code audit as of baseline `2e020d9b`.

## Files involved

- `ultimate_pipeline/topology/junction_connector_rebuild.py` — **live** implementation, contains `ConnectorValidator`.
- `ultimate_pipeline/tools/junction_connector_rebuild.py` — an older/parallel implementation, not wired into the
  pipeline (`stage_05_geometry.py` calls the `topology/` version only). Should be marked deprecated to avoid
  confusion; not removed by this pass.
- `ultimate_pipeline/quality/check_junction_integrity.py` — `JunctionIntegrityGate`, wired as an unconditional
  hard-fail gate in `scripts/measure_candidate_acceptance.py::run_gates()` and `quality/map_acceptance.py`.
- `ultimate_pipeline/quality/check_junction_connection_coverage.py` — a broader, geometry+heading-aware gap
  detector, **not wired into any gate or pipeline call** — confirmed standalone via repo-wide import search.
- `ultimate_pipeline/quality/check_lane_link_targets_exist.py`, `ultimate_pipeline/lanes/lanelink_builder.py`.
- `ultimate_pipeline/tools/junction_connector_snap.py` — a narrower, position-only "snap" repair tool.

## `ConnectorValidator` — confirmed narrow, by its own source comments

```python
class ConnectorValidator:
    def validate(self) -> bool:
        if self.road.find("planView") is None: return False
        if float(self.road.get("length", 0)) < 0: return False
        # E1.5: validate lane sections (SKIP for now)
        # E1.8: validate attachment poses (SKIP for now)
        return True
```

Lane-section validation and attachment-pose validation are **explicitly commented out** in the live code, not
merely absent. This is the exact gap the audit brief predicted, confirmed rather than assumed.

## What IS covered today, and by which mechanism (not always `ConnectorValidator`)

| Requirement | Covered? | Mechanism |
|---|---|---|
| planView exists | Yes | `ConnectorValidator` |
| length ≥ 0 | Yes | `ConnectorValidator` |
| Lane-section existence/validity | **No** | explicitly disabled |
| Attachment pose (start/end position+heading vs. connected roads) | **No** inside `ConnectorValidator` | — |
| C0 position continuity at seam | Partial, position-only | post-hoc gap check in the rebuild function itself (`max_after_gap_m` default 0.5m), reverts the edit on failure |
| Tangent/heading continuity at seam | **No** | not checked anywhere |
| laneLink from/to existence | Yes | `JunctionIntegrityGate`, a separate module |
| laneLink driving-direction correctness | **No** | only ID existence is checked, not compatible direction/type |
| contactPoint correctness | Indirect only | used as an input heuristic to pick attach pose, never independently verified against geometry |
| Predecessor/successor consistency | **No** | no dedicated check found anywhere |
| Dangling connectors (missing road/junction refs) | Yes | `JunctionIntegrityGate` |
| Duplicate/conflicting connections | **No** | no detection found |
| Coverage gaps (road cites a junction, junction doesn't cite it back) | Yes, but unwired | `check_junction_connection_coverage.py` — a real, geometry+heading-aware classifier (CONFIDENT/AMBIGUOUS/NO_CANDIDATE), explicitly read-only per its own docstring, **not called from `run_gates()` or any pipeline stage** |

## The straight-chord fallback

- Location: `_replace_planview_with_direct_line()`. Tried only after a real curved-arc fit (`_fit_arc_geometry`,
  which has its own verified round-trip endpoint check) fails, and only if `allow_straight_chord_fallback=True`.
- **Default: `False`**, at both the low-level function and the file-level entrypoint.
- The entire connector-rebuild feature is itself off by default in the governed pipeline
  (`UP_ENABLE_JUNCTION_CONNECTOR_REBUILD=0`). Even when enabled, the chord fallback needs a second, separate
  opt-in (`ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK`) AND `RELEASE_PROFILE=EXPERIMENTAL_UNSAFE`.
- Test coverage confirms the default-off behavior directly: `test_junction_connector_rebuild.py::test_line_connector_rebuild_blocks_straight_chord_by_default`.
- **No check anywhere validates that the chord preserves tangent/heading continuity** with the connected roads —
  only the same generic position-gap check applies. A straight line generally will not match an incoming road's
  heading unless the anchor points happen to be collinear with it.
- **Known drift**: `submission/infrastructure/ultimate_pipeline/pipeline_stages/stage_05_geometry.py` (the frozen
  thesis-submission mirror) defaults this feature to enabled — consistent with this repo's already-documented
  policy that `submission/infrastructure/` is a deliberately frozen snapshot, not a live-pipeline drift bug.

## Production connector contract (target, not yet implemented)

A connector is production-valid only if ALL of the following hold. Status column reflects what's checked TODAY;
items marked "NEW" don't exist anywhere yet.

| # | Requirement | Today |
|---|---|---|
| 1 | Valid road length (≥0) | Checked (`ConnectorValidator`) |
| 2 | Start/end position matches incoming/outgoing road within tolerance | Checked, position-only, post-hoc |
| 3 | Start/end heading matches incoming/outgoing road within tolerance | **NEW** |
| 4 | Junction attachment pose is geometrically verified (not just contactPoint-heuristic) | **NEW** |
| 5 | C0 continuity at both ends | Checked (subsumed by #2) |
| 6 | Tangent (C1) continuity at both ends | **NEW** |
| 7 | laneSection exists and is valid | **NEW** (explicitly disabled today) |
| 8 | Lane widths valid (no zero/negative) | Covered by a *different* gate (`check_lane_width_continuity`), not connector-specific |
| 9 | Lane-offset consistency | Same as #8 |
| 10 | laneLink from/to exist | Checked (`JunctionIntegrityGate`) |
| 11 | laneLink driving direction correct | **NEW** |
| 12 | contactPoint matches actual geometry | **NEW** |
| 13 | Predecessor/successor consistency | **NEW** |
| 14 | No dangling connector | Checked (`JunctionIntegrityGate`) |
| 15 | No duplicate/conflicting connection | **NEW** |

Implementing #3, #4, #6, #7, #11, #12, #13, #15 as real checks inside `ConnectorValidator` (uncommenting and
implementing the two already-stubbed lines is the natural starting point for #7 and part of #4) is the concrete
Codex-facing task; see `PRODUCTION_MAP_TASK_GRAPH.json`.

## A related finding this document exists to surface (not predicted by the original brief)

A separate audit pass (map-of-record forensics) found that **20.3% of junction-connector road-boundary links
(9,176 of 45,178) have a geometric position offset ≥ 0.05m, with a median offset of exactly one lane width
(3.5m)**, and that this is **structurally invisible to `valid_for_experiments`** because
`check_geometric_continuity.py` deliberately routes junction-connector links into a separate, non-gating bucket.
This is very likely evidence that connector reference-lines are anchored to the wrong lane-boundary/lane-index
rather than the road centerline in a large fraction of cases. See `MAP_QUALITY_GAP_REGISTER.json` GAP-002 for
the full writeup — this is one of the highest-priority findings of the entire audit.
