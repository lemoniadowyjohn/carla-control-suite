# GAP-079 (reversed ~0.1 m stubs): decision tree and X9b bisection

GAP-079 is kept **separate from GAP-070**. The snap neither creates nor removes these stubs (the
170-180° bucket is 111 before and after the snap, and the > 150° lane-level kinks are 139/147 in
every arm of `ARCH003_LANE_BORDER_REVIEW.md`). Nothing below may delete a stub that carries routing.

```
For each stub S (58 at stage 01, 81 at stage 02; X9 inventory @06a31ed1, local):
1. Does S carry routing?  (connection laneLink AND an existing exit road AND stub lane links resolve)
   ├─ NO  -> class UNROUTED_DEGENERATE. Report it. Removal is allowed only behind a default-OFF flag,
   │         with a failing-first test. Go to step 5.
   └─ YES (all 58/58 and 81/81 so far) -> continue. MUST NOT be removed for its length.
2. Reference-line orientation vs travel:
   compute the lane travel direction (lane id sign + road link direction) and compare it with routing.
   ├─ The reference line opposes the routing, BUT the lanes are on the matching side (e.g. all
   │   positive ids) and the links run exit->incoming
   │       -> LEGAL_REVERSED_REFERENCE_LINE (valid OpenDRIVE; not a defect).
   │          The checker must classify it, not raise a kink. The 30 deg threshold stays.
   ├─ The lane travel direction opposes the routing -> TRUE_REVERSAL (defect; priority P1).
   └─ Undetermined (mixed lanes, missing links) -> OTHER (report with details).
3. contactPoint consistency:
   ├─ Road-level contactPoint disagrees with the geometric endpoint (the touching end is the other
   │   one) -> CONTACTPOINT_BUG (fix at the source stage that wrote the link).
   └─ consistent -> continue.
4. Position: lane-centre gaps at both ends (ARCH-003 method).
   ├─ >= 0.2 m -> POSITIONAL_DEFECT (with value).
   └─ < 0.2 m  -> OK.
5. Origin (stage 01 vs 02): position-match S between 01 and 02 (2 m radius, same junction).
   ├─ present at 01 -> origin Osm2Odr.
   └─ new at 02     -> origin netconvert. Go to the bisection.
```

## X9b netconvert bisection (stage 02 only; do not assume `--no-turnarounds` is sufficient)

The baseline is the exact command recorded in the run's `sumo_netconvert.log`, line 1:
`--offset.disable-normalization true --geometry.remove true --ignore-errors`.

1. **Region extraction:** 3 junctions holding netconvert-new stubs; the junction, its connecting,
   incoming and exit roads, and the signals and controllers they reference. Geometry is unmodified.
2. **Reproduce first:** the baseline must recreate a stub on at least one region before any toggle
   counts. If it doesn't, grow the region once. If it still doesn't, record INCOMPLETE.
3. **One toggle at a time:**
   - drop `--geometry.remove`;
   - `--opendrive.internal-shapes`;
   - `--junctions.internal-link-detail 1|10`;
   - `--opendrive-output.straight-threshold`;
   - `--junctions.scurve-stretch 1.0`;
   - `--geometry.min-dist 0.2`;
   - `--no-turnarounds`;
   - `--no-internal-links` (diagnostic only: it removes routing).
4. **Hypotheses to test explicitly:**
   - internal-junction lane splits (`:<J>_<n>` with `via`) producing a short second piece;
   - turnaround construction;
   - shape-computation failures (the log's "Could not compute smooth shape…" warnings).
5. **Every toggle also reports routing preservation:**
   - laneLink count;
   - reciprocity violations;
   - lane-link targets;
   - lane-centre continuity.
   An option that removes stubs by removing routing is rejected.
6. **Negative controls:**
   - 200 random non-stub connectors classified by the same code: the expected `LEGAL_REVERSED` rate
     must match their lane-id signs;
   - one synthetic legal reversed road that must classify as LEGAL.

Acceptance requires all of:
- class counts for 58 + 81;
- the origin per stub;
- a remedy decision (an option behind a default-OFF flag, a source-stage re-orientation, or "leave
  it plus checker classification");
- tests 1-5 from `docs/reviews/ARCH_X8_X9_20261104/GAP079_X9B_INVESTIGATION_PLAN.md`.
