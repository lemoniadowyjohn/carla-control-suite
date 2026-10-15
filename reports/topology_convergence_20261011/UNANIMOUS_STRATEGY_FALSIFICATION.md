# UNANIMOUS_LANE_ID_STRATEGY Falsification

**Date**: 2026-10-11
**Authority**: M2.5/M3.5 Topology Convergence

---

## Classification

**UNANIMOUS_LANE_ID_STRATEGY = INVALID**

---

## Evidence

### 1. Current Population Data

From canonical population (GAP048_POPULATION_CANONICAL.jsonl):
- **Category B (MULTI_ROAD_UNANIMOUS_TARGET_LANE_ID)**: **0 cases**
- **Category C (TRUE_MULTI_TARGET_LANE_ID)**: **261 cases**

All 261 ambiguous cases have **different candidate lane IDs** across connecting roads (e.g., `[-2, -1]`). Zero cases have all candidates with the same lane ID.

### 2. OpenDRIVE/CARLA Semantic Analysis

**Lane IDs are road-local, not global.**

In OpenDRIVE:
- Each `<road>` has its own `<lanes>` with `<laneSection>`s containing `<lane>` elements with local `id` attributes
- A `<laneLink>` inside a `<connection>` maps `from` (incoming lane ID) to `to` (connecting lane ID)
- The `to` lane ID refers to a lane on the `connectingRoad` — a **different road** with its own local lane ID space

**Example from data:**
```
Road 42163, Lane -2 → Junction 61
  Connection to Road 42164: laneLink from="-2" to="-2"
  Connection to Road 42165: laneLink from="-2" to="-1"
```
These are **two distinct physical lanes** on two different roads (42164 and 42165). They happen to have local IDs -2 and -1 respectively. The incoming lane FORKS.

**Even if both connections had `to="-2"`:**
- Road 42164 lane -2 ≠ Road 42165 lane -2
- They are different lanes on different roads
- The incoming lane still forks to two distinct lanes
- Treating this as "unanimous" would incorrectly merge two distinct lanes

### 3. CARLA Runtime Behavior

CARLA's lane topology (Waypoint API) treats each road's lanes independently:
- `waypoint.lane_id` is local to the road
- `waypoint.get_next()` follows laneLinks through junctions
- A fork (multiple valid `get_next()` results) is a genuine topological split
- CARLA does NOT merge lanes with the same local ID on different roads

### 4. Policy Violation

The project's standing policy (GAP-026, GAP-048, HH1):
> "Choosing one would be guessing (policy violation)."

The UNANIMOUS_LANE_ID_STRATEGY would choose one connecting road arbitrarily when multiple exist with the same target lane ID — this IS guessing.

---

## Conclusion

The UNANIMOUS_LANE_ID_STRATEGY is **INVALID** because:

1. **Zero empirical cases** exist in the current map where it would apply
2. **Semantically incorrect**: Lane IDs are road-local; same ID on different roads ≠ same lane
3. **Would create false topology**: Merging distinct connecting-road lanes violates OpenDRIVE laneLink semantics
4. **Policy violation**: Arbitrarily selecting one connecting road when multiple valid targets exist

**Recommendation**: Do NOT implement this strategy. The current approach (leave ambiguous cases unresolved) is correct.