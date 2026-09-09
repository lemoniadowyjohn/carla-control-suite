# Codex — regulatory signs / traffic lights discovery pass (2026-09-09)

Fresh discovery pass, verified against the real Ingolstadt OSM source
(campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm). 2 concrete
findings, both empirically confirmed (not inferred from reading code alone).

## PROMPT M — regulatory_sign_writer.py is fully wired and fully dead simultaneously

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/regulatory-sign-catalog-v1-<date>.

CONFIRMED (2026-09-09, empirically tested, not just read): ultimate_pipeline/enrichment/
regulatory_sign_writer.py's own module docstring claims "Requires an osm_roads_by_id dict where
each entry carries a traffic_sign attribute... This is not yet populated in the main pipeline's
OSM loading path." THIS IS STALE/WRONG. Direct test:

    from ultimate_pipeline.enrichment.osm_meta_index import build_osm_meta_index
    result = build_osm_meta_index("campaigns/.../ingolstadt_authoritative.osm")
    # 50 of 1536 indexed streets DO have a populated "traffic_sign" field, e.g.
    # "Parkstraße" -> "DE:244.1", "Bahnhofstraße" -> "DE:245,1026-30"

So the wiring is NOT the problem. The real problem: SIGN_TABLE (the OSM-code -> XODR-object
lookup, ~17 entries: stop/giveway/speedLimit10-120/parking/priority) matches ZERO of these 50
real streets' actual traffic_sign values. Tested directly: `0/50` match. The real dataset's
traffic_sign values are dominated by path/cycleway classification codes (DE:240 shared foot/
cycle path: 172 occurrences map-wide, DE:245 bus lane: 105, DE:239 pedestrian path: 41, DE:241
segregated path: 30, DE:244.1 cycle street: 35, DE:238 cycle path: 3) -- essentially none of the
vehicular regulatory codes SIGN_TABLE covers (de:206 stop, de:301/306 priority, de:274-* speed
limit) appear anywhere in this source data's traffic_sign tag at all.

The net effect: apply_regulatory_signs() is correctly called from the live pipeline
(stage_04_enrichment.py), correctly receives real OSM data, and STILL produces exactly 0
<object> elements on the current map-of-record, every single run, silently.

TASK:
1. Fix the stale docstring in regulatory_sign_writer.py -- state the real situation (wiring
   works, coverage is the gap) so a future reader doesn't waste time re-investigating the wiring
   question this prompt just settled.
2. Investigate whether the DE:240/241/244.1/238/245/239 codes actually present in this dataset
   are semantically appropriate for SIGN_TABLE at all: these are mostly path-CLASSIFICATION
   signs (this way IS a shared/segregated cycle path, this way IS bus-only), which overlaps with
   information this codebase already derives from highway=cycleway/cycleway=lane tags elsewhere
   (see the turn/cycle-lane work already landed or in flight) -- adding them to SIGN_TABLE as
   physical roadside <object> sign placements may or may not be the right model. Make a
   deliberate call and document your reasoning either way; don't just mechanically add every
   code you see.
3. Separately: check whether genuinely vehicular regulatory codes (de:206 stop, de:301/de:306
   priority, de:274-* speed limit) exist ANYWHERE in the raw OSM file outside the `traffic_sign`
   tag key specifically (e.g. under a differently-named tag, or as node-level tags rather than
   way-level) -- if Ingolstadt's OSM mapping simply doesn't carry this data at all for stop/yield/
   speed-limit signs, that's a genuine data-availability gap to document, not a code bug to chase.
4. If you find real, currently-unmapped vehicular sign codes worth adding to SIGN_TABLE, add them
   with the same "only emit where confirmed, never infer" discipline this module's docstring
   already establishes. Report the before/after count of regulatory sign objects the pinned map
   would produce.

End with:
DOCSTRING_FIXED: PASS | FAIL
SIGN_TABLE_EXPANDED: PASS | FAIL | NOT_APPLICABLE -- <reasoning>
PINNED_MAP_SIGN_COUNT: <before> -> <after>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT N — traffic-light inference ignores 44 real ground-truth OSM signal locations

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: the OSM<->XODR spatial
correspondence engine (feature/osm-correspondence-engine-v1-20260907, verified landed and
correct). Isolated branch: feature/traffic-light-osm-groundtruth-v1-<date>.

CONFIRMED (2026-09-09): ultimate_pipeline/enrichment/traffic_light_infer.py::TrafficLightInferer
places traffic-light objects PURELY from junction topology (_estimate_junction_center averages
incoming-road endpoint positions; no OSM reference anywhere in the module -- confirmed via full
read, zero "osm" references). The real source OSM
(campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm) has 44 real
highway=traffic_signals node locations -- actual ground truth for which junctions genuinely have
traffic lights in reality -- currently completely unused for this decision.

This means the pipeline cannot currently distinguish "this junction really has traffic lights"
from "this junction doesn't" -- whatever heuristic currently decides which junctions get an
inferred traffic light (read the module to determine the actual current trigger condition, don't
assume) applies uniformly/geometrically, with no real-world validation available even though the
data exists.

TASK:
1. Determine the current trigger condition for WHEN infer_as_objects/infer_and_insert decides a
   junction gets a traffic light (read the actual logic -- is it every junction above some
   incoming-road-count threshold? all junctions unconditionally? something else?).
2. Using the now-available spatial correspondence engine, cross-reference each junction's
   position against the real highway=traffic_signals node locations (5m-order proximity, same
   pattern as the correspondence engine's own thresholds). For junctions with a confirmed nearby
   OSM traffic-signal node: keep/generate the inferred light (or increase confidence). For
   junctions with NO nearby OSM traffic-signal node: this is now a real signal that the
   topological inference may be wrong -- do not necessarily suppress the light unconditionally
   (topological inference may be catching real cases OSM's tagging missed), but DO record the
   disagreement as a metric, matching this session's established pattern of measuring before
   gating.
3. Report the real numbers: how many junctions currently get an inferred light, how many of
   those have a corroborating OSM traffic_signals node nearby, how many OSM traffic_signals nodes
   have NO corresponding inferred light at their location (a miss in the other direction).

This is investigation-and-instrumentation first, not necessarily a behavior change -- do not
silently start adding or removing traffic lights based on this cross-reference without reporting
the disagreement numbers first, since 44 ground-truth points is a small sample to calibrate a
behavior change against.

End with:
GROUNDTRUTH_CROSSREFERENCE: PASS | FAIL | INCOMPLETE
CURRENT_INFERRED_LIGHT_COUNT: <count>
OSM_CORROBORATED_COUNT: <count>
OSM_UNCORROBORATED_INFERRED_COUNT: <count>
OSM_SIGNALS_WITH_NO_INFERRED_LIGHT: <count>
FULL_OFFLINE_TESTS: PASS | FAIL
```
