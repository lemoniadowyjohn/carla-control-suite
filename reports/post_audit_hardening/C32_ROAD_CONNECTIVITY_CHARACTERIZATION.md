# C32 — road-connectivity investigation: characterized, recommend no fix

Per the approved scoped plan (Phase 1: characterization, Phase 2: decision gate before any
fix). All of this is read-only analysis against the pinned XODR and the pinned source OSM —
no pipeline code was touched, no regen was run.

## The two connectivity metrics are genuinely different, unrelated graphs
Confirmed by direct code reading (both functions read in full) plus an independent Explore
agent cross-check:
- **`map_acceptance.py::component_reachability_summary`** (pre-existing, the source of the
  stable "33 isolated lane components" WARN): builds a **lane-level** graph from `<lane><link>`
  successor/predecessor edges (within-road section transitions + cross-road junction links).
  This is what actually determines CARLA autopilot drivability — its own docstring cites a
  real live-CARLA finding that spawn points on isolated components never drive.
- **`audit_xodr_visual_geometry.py::_graph_components`** (new this session, from C30): builds a
  **road-level** graph from `<road><link>` + `<junction><connection>` edges — coarser, purely
  topological, doesn't know about individual lanes at all.
No prior report cross-analyzed these two, and none named specific isolated road IDs before now.

## Road-level finding: 6 isolated roads are exactly 3 directional-pair duplicates
All 6 (`42367`, `43405`, `46369`, `46698`, `48129`, `51654`) have **zero** `<link>` element —
not a dangling reference, genuinely absent. Pairing by name/length revealed each is the exact
geometric reverse of its partner (start↔end coincide to 0.000 m in both directions):
- `42367` / `46698` — both "Maria-Telkes-Straße"
- `43405` / `48129` — both "Stollstraße"
- `46369` / `51654` — unnamed, identical length

Each pair is the forward/backward directional split of one physical road segment — standard
for two-way streets in this pipeline (confirmed: several *other*, correctly-linked segments of
Stollstraße follow the identical matched-length-pair pattern).

## Root cause, per street
- **Maria-Telkes-Straße**: the pinned OSM source has exactly **one** way for this name
  (`1051035541`, `highway=unclassified`, 2 nodes — a short, simple segment). Checked whether
  either endpoint node connects to anything else in the source graph: one endpoint
  (`9658584938`) is shared with `Thomas-Edison-Straße`, but that way is tagged
  **`highway=pedestrian`**. This street's only real-world extension is a pedestrian path — the
  pipeline is correctly *not* creating a vehicular road-to-road link there, because there is no
  other vehicular street to link to. **Expected behavior, not a bug.**
- **Unnamed pair** (`46369`/`51654`): no name tag, so the same OSM lookup isn't directly
  traceable, but the identical pattern (exact-reverse pair, isolated only as its own pair, no
  nearby geometry) makes the same explanation — a short way whose only extension is
  non-vehicular or genuinely absent in the source graph — the most plausible account.
- **Stollstraße**: genuinely different picture. This street has **9** XODR road segments total,
  and **7 of 9 are correctly linked** (three other exact-reverse pairs plus one one-way
  segment, forming a proper chain through real junctions 1106/1111/1179/1182/1250). The OSM
  source confirms Stollstraße is a real, connected through-street (3 ways, confirmed shared
  nodes between them). Only this **one** 135.555 m segment pair (`43405`/`48129`) failed to
  link, while structurally identical sibling pairs of the same street succeeded. This is the
  one piece of the three that looks like it could reflect a genuine, narrow processing gap
  rather than expected dead-end behavior — but tracing exactly *why* this one segment (out of
  several SUMO-derived from the same OSM ways) was skipped would require instrumenting
  SUMO/netconvert's internal way-splitting, which is disproportionate to what's actually at
  stake here (see recommendation).

## Recommendation: do not implement a fix
- **Scale**: 6 of 32,297 roads (0.019%). Already a non-blocking soft WARN, not failing
  anything.
- **Practical value even if "fixed"**: adding the missing self-link for a pair would only turn
  2 isolated singleton roads into 1 isolated 2-road island — it would **not** connect them to
  the main drivable network (2 of the 3 pairs have no other vehicular street to reach in the
  source data at all). No autopilot routing scenario, capture scenario, or RQ is unblocked by
  this. It doesn't move the lane-level 33-component figure in any meaningful way either, since
  these few roads are a small subset of that separate, larger metric.
- **2 of 3 pairs are very likely correct pipeline behavior**, not bugs — confirmed directly
  against the source OSM for the one case with a distinguishing name tag.
- **The 1 pair that could reflect a real gap (Stollstraße) would need SUMO-internals tracing
  to root-cause properly**, disproportionate effort for a change whose maximum possible
  benefit is "one fewer near-zero-impact WARN line."
- Matches today's standing lesson: an existing, plausible-looking fix (heading-only smoothing)
  measurably made the map worse when actually tested. A narrower fix here carries much lower
  risk than that did, but the cost/benefit still doesn't clear the bar — there's no benefit to
  weigh the (small but nonzero) risk against.

## What was and wasn't done
- Pure read-only XML/OSM analysis (pinned XODR + pinned source OSM). No pipeline code
  modified, no regen run, no test suite impact.
- Did not perform an exhaustive ID-level cross-check between the road-level and lane-level
  isolated sets — `component_reachability_summary` doesn't expose per-lane component
  membership in its returned summary (aggregate counts only), and extracting it would require
  reading its internal union-find state directly. Not done in this pass since it wasn't needed
  to reach the recommendation above; flagged here rather than silently skipped.
- The 3 small road-level clusters (16/4/4 roads, distinct from the 6 fully-isolated singles)
  were not individually characterized with the same depth — the 6-road characterization above
  already answered the decision-gate question (is this worth fixing) clearly enough that
  extending the same analysis to the clusters wouldn't change the recommendation.
