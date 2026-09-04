# WS-H: isolated-lane-junction-connection root cause (documented, not fixed)

Round-3 map-quality plan item. This is a documentation-only pass -- no code change. Scope: pin
down, with fresh direct verification, why `component_reachability_summary()`
(`ultimate_pipeline/quality/map_acceptance.py:156`) reports **27 isolated lane components** on the
current map-of-record candidate
(`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260904_deepaudit.xodr`,
sha256 `e281367e...`), soft-warned only (`component_reachability` is opt-in hard-fail via
`--require-component-reachability`, off by default) and why it isn't being auto-repaired now.

## The authoritative metric

`component_reachability_summary()` builds a union-find graph over every `driving`-type lane
(`{road_id}:{laneSection_index}:{lane_id}` nodes), wiring edges from three sources: (1) within-road
lane-section successor/predecessor transitions, (2) road-level `<link>` entries with
`elementType="road"` (direct road-to-road boundaries, no junction involved), and (3) junction
`<connection>`/`<laneLink>` entries (`incomingRoad` lane -> `connectingRoad` lane). A lane node with
no edges at all ends up as its own size-1 component -- that's what `isolated_lane_component_count`
counts. On the real candidate: `component_count=35`, `largest_component_fraction=0.996734`,
`isolated_lane_component_count=27` -- one dominant component holding 99.67% of all driving lanes,
plus 27 completely disconnected single-lane fragments (confirmed directly, re-measured this pass).

## Root cause, verified with a concrete example (road 42335 / junction 11)

Road 42335 (length 26.6 m) has:

```
<road id="42335" length="26.60616812" ...>
  <link><predecessor elementType="junction" elementId="11"/></link>   <!-- no <successor> at all -->
  ...
  <lanes><laneSection><right><lane id="-1" type="driving">
    <link/>   <!-- empty: no successor, no predecessor -->
```

Junction 11's own `<connection>` list:

```
connection 0  incomingRoad=42794  connectingRoad=52755  contactPoint=start
connection 1  incomingRoad=42794  connectingRoad=52756  contactPoint=start
connection 2  incomingRoad=47022  connectingRoad=52757  contactPoint=start
connection 3  incomingRoad=47022  connectingRoad=52758  contactPoint=start
connection 4  incomingRoad=47022  connectingRoad=52759  contactPoint=start
connection 5  incomingRoad=46641  connectingRoad=52760  contactPoint=start
connection 6  incomingRoad=46641  connectingRoad=52761  contactPoint=start
```

Road 42335 never appears as `incomingRoad` anywhere in junction 11 -- despite its own `<link>`
explicitly claiming to approach that junction. Since the reachability graph's only route through a
`elementType="junction"` link is via that junction's `<connection>` list, and road 42335 has **no
successor link either** (confirmed above -- it's a true dead end on its far side), its single
driving lane gets zero graph edges from any of the three connectivity sources. It is, verifiably,
one of the 27 isolated components, not just a bookkeeping quirk that happens to still be reachable
some other way.

## Scale caveat found during this pass: the raw pattern is far more common than 27

A systematic sweep of the whole map (every road whose `<link><predecessor|successor
elementType="junction">` names a junction, checked against whether that junction's `<connection>`
list actually cites the road as `incomingRoad`) found **9,350 of 32,267 roads (~29%)** exhibit this
same road-level mismatch on at least one end -- two full orders of magnitude more than the 27 truly
isolated lanes.

This is *not* a contradiction: most of those 9,350 roads have a second, correctly-linked end (a
normal road-to-road link, or a junction where they genuinely are listed as `incomingRoad`) that
still pulls them into the main 99.67% component by transitivity. Road 42335 is unusual specifically
because *both* its ends fail -- the junction-side end has the connection-list gap, and the far end
has no link at all. The 27-lane count is the real, ground-truth measure of roads this actually
strands; the 9,350 figure is a much broader, mostly-benign version of the same underlying junction-
connection-generation gap, currently invisible to any wired gate because it doesn't change
`component_reachability`'s output when a road is rescued by its other end.

**This scale caveat is a new observation from this pass, not previously characterized.** It doesn't
change today's map's acceptance status (only the 27 truly-isolated lanes matter for drivability),
but it suggests the underlying junction-connection-list generation gap is systemic rather than a
handful of one-off omissions, and is worth carrying into whatever future investigation traces the
actual stage responsible (see below) -- a fix there would likely need to explain the 9,350-scale
pattern, not just the 27 currently-visible symptoms.

## Why not auto-repaired now

Constructing the missing `<connection>`/`<laneLink>` entries correctly requires inferring which
specific `connectingRoad` and which lane(s) traffic from the omitted incoming road should route
through -- real geometric/directional reasoning (matching headings, lane offsets, and turn
geometry at the junction), not a mechanical, bounded nudge like this session's other repairs
(`repair_lane_width_discontinuities`, `repair_true_zseams`, etc., which each reuse an existing
checker as their own detection oracle and adjust an existing value by the exact residual delta). A
wrong inference here risks fabricating an incorrect route through a real junction, which is a worse
outcome than the current soft-warned, 0.33%-of-lanes gap.

## Recommended future work (not started)

Trace which pipeline stage actually generates `<junction><connection>` entries and why some
legitimately-approaching roads are omitted from that generation step -- the ~29% road-level
mismatch rate suggests a systemic gap in that stage's logic (e.g. an early-exit or a filter that
drops certain approach directions), not per-junction bad luck. Once root-caused, a real fix could
close both the 27-lane visible gap and the broader 9,350-road latent pattern in one pass, with
proper geometric validation rather than a mechanical repair.

## Status

Documentation only, per the approved round-3 plan (`velvet-wobbling-lighthouse.md`, Workstream H).
No code change. `component_reachability` remains a soft warning, `valid_for_experiments=True` is
unaffected, and no regeneration/re-promotion was triggered by this pass.
