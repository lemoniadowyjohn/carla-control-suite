# X9b — GAP-079 reversed 0.1 m connector stubs: investigation plan (2026-11-04)

## What is established, and by whom

| Fact | Source | Independently reproduced? |
|---|---|---|
| 58 stubs at stage 01 and 81 at stage 02, in the 170-180° exit bucket (0.09–0.11 m, single line geometry, in a junction) | X9 (`06a31ed1`, local branch, **not on GitHub**) | yes: `evidence/x9check.py` on the local stage files (58/58, 81/81) |
| All of them carry declared routing (a connection laneLink, an existing exit road, stub lane links resolving to exit-road lanes) | X9 + this review | yes, same script |
| The +23 is a population difference; road ids are renumbered by netconvert | X9 | consistent; position matching is pending |
| U-turn connectors come from Osm2Odr, not netconvert (3,949 at stage 01, 3,944 at stage 02) | this review (`evidence/uturn_count.py`) | executed once |

Inputs are local, untracked run outputs (stage 01 = map-of-record sha256 `370abbbb…`; stage 02 is
138 MB). Until they are archived (backlog C0), GitHub-only reviewers must treat these counts as
reported, not reproduced.

## Questions to answer

1. **Origin of the 23:** which netconvert behaviour creates them? Is the cause an internal-junction
   split, shape-computation failures ("Could not compute smooth shape…" in the log), or turnaround
   building?
2. **Reversal semantics:** is "reversed" a real driving reversal, or a legal reference-line
   orientation? In OpenDRIVE, a road may run opposite to traffic: its lanes are then on the left
   (positive ids), and its links run predecessor = exit, successor = incoming. That is legal and
   drivable.
3. **Relation to U-turns:** how many stubs sit inside U-turn connector chains (incoming and exit are
   twins)? If most do, GAP-079 and GAP-070 share one root (Osm2Odr turnaround representation) and
   should be fixed together.

## Method (the X9b part 2 prompt already given to Codex covers steps A-D; E-F are new)

A. **Position matching 01 ↔ 02.** Match each stub by its start point and junction (2 m radius).
   Classify stage-2 stubs as carried or netconvert-new, and stage-1 stubs as survived or gone.

B. **Heading / lane-direction classification.** Use the kernel only (pose_at_s / endpoint) and no
   private evaluator. Per stub:
   - the contactPoint-aware poses of the incoming and exit ends;
   - the gaps and the heading differences;
   - the lane side (sign of the driving lane ids);
   - the direction of the lane links.
   Assign one class:
   - `REPRESENTATION_ONLY`: reversed reference line, consistent lane side and links, gaps < 0.2 m;
   - `TRUE_REVERSAL`;
   - `POSITIONAL_DEFECT` (a gap ≥ 0.2 m);
   - `OTHER`.
   Negative control: run the same classifier on 200 random non-stub connectors. It must report
   `REPRESENTATION_ONLY` only for connectors whose lane ids actually are positive. Positive control: a
   synthetic stub with flipped lanes and correct links must come out as `REPRESENTATION_ONLY`.

C. **Netconvert option bisection** on 3 extracted regions (a junction plus its incoming and exit roads,
   and the signals/controllers they reference).
   - Baseline: the exact stage-2 command, from `sumo_netconvert.log` line 1:
     `--offset.disable-normalization true --geometry.remove true --ignore-errors`.
   - The baseline must reproduce a stub before any toggle result counts.
   - Toggles, one at a time: drop `--geometry.remove`, `--opendrive.internal-shapes`,
     `--junctions.internal-link-detail 1/10`, `--opendrive-output.straight-threshold`,
     `--junctions.scurve-stretch 1.0`, `--no-turnarounds`, `--geometry.min-dist 0.2`, and
     `--no-internal-links` (diagnostic only: it removes routing, so it cannot be the remedy).
   - Also test the internal-junction split hypothesis in the `.net.xml` (`:<J>_<n>` lanes with a short
     second part).

D. **Optional full-map confirmation** of a routing-preserving option, only if ≥ 1 GB is free.
   Measure reciprocity, lane-link targets and junction integrity, and report every metric that gets
   worse.

E. **(new) Road-ID remapping and predecessor/successor preservation.** For every matched pair
   (01 → 02), check that the stub's incoming and exit roads map to the same OSM-derived pair. Road
   ids are renumbered, so match by geometry: the start/end position of each neighbour within 0.5 m.
   Report how many stubs change their neighbour pair. A change means netconvert rewired the topology,
   not just the geometry.

F. **(new) U-turn cross-reference.** For each stub, record whether it sits on a U-turn chain (exit is
   the reverse twin of incoming; see `uturn_count.py`). Report the overlap.

## Regression tests to add with any remedy (failing first)

1. `test_routed_stub_is_never_removed_for_length`: a 0.1 m connector with a laneLink and an exit road
   survives every topology/cleanup stage.
2. `test_unrouted_degenerate_stub_is_reported`: the same stub without a laneLink is reported as
   degenerate. It is removed only behind a default-OFF flag, and only if that flag is part of the
   remedy.
3. `test_reversed_reference_line_with_left_lanes_is_not_flagged_as_reversal`: legal orientation.
4. `test_true_reversal_is_flagged`: lane direction opposite to the routing.
5. `test_junction_exit_heading_check_classifies_representation_only`: the 170-180° bucket separates
   `REPRESENTATION_ONLY` from real kinks. **The 30° threshold must not be raised (GAP-026 rule).** The
   classification must use lane direction, not a looser angle.

## Acceptance

GAP-079 can close only with:
- a class count for all 58 and 81 stubs;
- a remedy decision (an option change behind a default-OFF flag, a source-stage re-orientation, or
  "leave it, plus checker classification");
- the tests above;
- for any geometry change: re-measurement in X8 and a CARLA traversal check (operator).
