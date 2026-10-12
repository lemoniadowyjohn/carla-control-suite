# HH1 Verification Report: lane_successor_topology.py Fix

**Date**: 2026-10-08  
**Map-of-Record**: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr`  
**SHA256**: `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8` (matches pinned registry)

---

## Executive Summary

The `lane_successor_topology.py` module has been integrated into Stage 7 but **does not resolve the GAP-048 missing-successor issue** on the current pinned map-of-record. Key findings:

| Metric | Value |
|--------|-------|
| Original missing successors (GAP-048 claim) | 10,556 |
| **Actual missing on pinned map (driving lanes)** | **331** |
| Inferred by lane_successor_topology | **0** |
| Junction-mapped by lane_successor_topology | **0** |
| Remaining without topology (lanes_without_topology) | **331** |
| **Resolution rate** | **0%** |

**Conclusion**: The 10,556 figure from GAP-048 does not match the current pinned map-of-record (which has only 331 missing driving lane successors). The module infers 0 successors because the 331 missing are on roads connecting to junctions (elementType="junction"), which the current implementation does not handle. Additionally, **Strategy 2 (junction laneLink mapping) contains a bug** that prevents it from working even for connecting roads.

---

## 1. Unit Tests Written

Created `tests/unit/test_lane_successor_topology.py` with 9 tests covering:

| Test | Status | Notes |
|------|--------|-------|
| `test_road_level_successor_match` | ✅ PASS | Strategy 1 works: road-level successor with matching lane ID |
| `test_road_level_successor_no_match` | ✅ PASS | Correctly skips when lane IDs don't match |
| `test_junction_lane_link_mapping_currently_broken` | ✅ PASS | **Documents bug**: Strategy 2 never triggers due to inverted map lookup |
| `test_junction_no_road_successor_on_connecting` | ✅ PASS | Correctly infers 0 when connecting road has no road successor |
| `test_topology_unresolvable_dead_end` | ✅ PASS | Confirms lanes stay without successor when no topology exists |
| `test_already_has_successor_skipped` | ✅ PASS | Existing successors preserved |
| `test_non_driving_lanes_skipped` | ✅ PASS | Shoulder/parking/center lanes skipped |
| `test_center_lane_id_zero_skipped` | ✅ PASS | Lane ID 0 correctly skipped |
| `test_multiple_lane_sections_all_processed` | ✅ PASS | All lane sections processed (not just boundary) |

**Pytest run**: 9/9 tests pass. Related Stage 7/8 tests also pass (12 total).

---

## 2. Pinned Map-of-Record Analysis

### Map Statistics (sha256 370abbbb...)
- **Total lane elements**: 85,909
- **Driving lane elements**: 34,301
- **Unique (road, lane) driving lanes**: ~34,301 (one per lane section)
- **Driving lanes WITHOUT successor**: **331 unique lanes**

### The 331 Missing Successors

All 331 missing successors are on **incoming roads to junctions**:

```
Road 42335, Lane -1
Road 42435, Lane -1
Road 42471, Lane -1
... (328 more roads, each with Lane -1)
Road 49471, Lane -1, -2, -3
Road 49767, Lane -1, -2, -3
Road 51767, Lane -1, -2
```

Each of these roads has:
- `road.link.successor.elementType = "junction"` (not "road")
- `road.junction = "-1"` (not in a junction themselves)
- Road-level successor points to a junction (e.g., junction 2, 6, etc.)

---

## 3. Why lane_successor_topology Infers 0

### Strategy 1: Road-level successor (elementType="road")
- **Condition**: `road_succ[0] == "road"`
- **Result**: **FAILS** for all 331 lanes because their road successors have `elementType="junction"`
- The module explicitly checks for `elementType == "road"` and ignores junction successors

### Strategy 2: Junction laneLink mapping
- **Condition**: `is_junction_road and road_id in junction_lane_map`
- **Result**: **FAILS** because:
  1. These roads are NOT in junctions (`junction="-1"`), so `is_junction_road = False`
  2. Even if they were, the `junction_lane_map` keys are **connectingRoad** IDs, not incomingRoad IDs
  3. **BUG**: The map stores `incoming_lane_id -> connecting_lane_id`, but lookup uses `connecting_lane_id` as key

### Bug in Strategy 2 (junction mapping)
```python
# In _build_junction_lane_map():
lane_map[from_id] = to_id  # Maps incoming -> connecting

# In infer_lane_successors_from_topology():
if lane_id in lane_map:    # Looks up connecting lane_id as key
    mapped_id = lane_map[lane_id]  # Never matches!
```
The map keys are incoming lane IDs, but the lookup uses connecting lane IDs. This means **Strategy 2 never triggers** even for valid connecting roads.

---

## 4. Are the 331 Cases Genuinely Topology-Unresolvable?

**Yes, with the current implementation design.**

### Why they cannot be resolved:
1. **Road successor points to junction, not road**: The module only handles `elementType="road"` successors. Junction successors require laneLink mapping inside the junction.
2. **Module only processes connecting roads**: Strategy 2 processes roads that ARE connectingRoad in a junction (junction != -1 AND road_id in junction_lane_map). These 331 roads are incomingRoad, not connectingRoad.
3. **No laneLink processing for incoming roads**: The junction laneLinks map `incomingRoad.lane -> connectingRoad.lane`, but the module never looks at incomingRoad lanes.

### What would be needed to resolve them:
- Extend Strategy 2 to also process **incoming roads** by:
  1. Building a reverse map: `incomingRoad -> {incoming_lane: connecting_lane}`
  2. For each incoming road lane that has a laneLink, follow the connecting road's road-level successor
  3. This would require the connecting road to have a road-level successor to a ROAD (not junction)

### Are they legitimate dead-ends?
**No, they are not dead-ends in the real world.** These roads connect to junctions. The lane-level topology exists in the junction laneLinks, but the module doesn't traverse `incomingRoad -> junction -> connectingRoad -> road successor`.

---

## 5. Discrepancy with GAP-048's 10,556 Figure

The GAP-048 register states: *"10,556 lanes missing <successor> on the pinned map-of-record, found via GAP-046's verification trial."*

**Possible explanations:**
1. **Different map**: The GAP-046 trial used a different pipeline output (intermediate stage), not the final pinned map-of-record
2. **Different counting**: 10,556 may count all lane elements (not unique lanes), or include non-driving lanes
3. **Map updated**: The pinned map-of-record may have been regenerated after GAP-048 was filed (file date: 2026-09-23, GAP-048 filed: 2026-10-08)

**Verification**: The current pinned map (sha256 370abbbb...) has only 331 missing driving lane successors.

---

## 6. Recommendations

### Immediate (to make module work as designed):
1. **Fix Strategy 2 bug**: Invert the junction_lane_map lookup or build inverse map
   ```python
   # Option A: Build inverse map in _build_junction_lane_map
   lane_map[to_id] = from_id  # connecting -> incoming
   
   # Option B: Fix lookup in main loop
   if lane_id in lane_map.values():  # Check if connecting lane is a target
       # Find the incoming lane that maps to this connecting lane
   ```

2. **Add Strategy 3**: Handle incoming roads to junctions
   - Build map: `incomingRoad -> {incoming_lane: connecting_lane}`
   - Follow connecting road's road-level successor

### For GAP-048 closure:
1. **Re-measure on GAP-046 trial output**: Run lane_successor_topology on the actual trial output that produced 10,556
2. **If 10,556 was real**: The current map-of-record may already have partial fixes applied
3. **Document scope**: Clarify that lane_successor_topology only handles road-to-road (not road-to-junction) successors

---

## 7. Artifacts Generated

| Artifact | Location |
|----------|----------|
| Unit tests | `tests/unit/test_lane_successor_topology.py` |
| Standalone module report | `/tmp/lane_successor_report.json` |
| Debug scripts | `debug_*.py` (in repo root) |

---

## 8. Verdict

**GAP-048 is NOT closed by this fix.**

- The module correctly implements Strategy 1 (road-to-road) but this doesn't apply to the 331 missing successors
- Strategy 2 (junction mapping) is **broken** and infers 0
- The 331 missing successors require a different topological traversal (incoming road -> junction -> connecting road -> road) that is not implemented
- The 10,556 figure from GAP-048 does not match the current pinned map-of-record

**Next steps**: Either (a) extend the module to handle junction incoming roads, or (b) accept that road-to-junction successors are out of scope for this generator-stage fix and must be handled elsewhere (e.g., in Stage 8 LaneLinkBuilder).