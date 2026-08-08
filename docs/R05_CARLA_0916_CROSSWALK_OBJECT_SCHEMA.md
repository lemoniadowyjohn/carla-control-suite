# R05 — CARLA 0.9.16 crosswalk `<object>` schema lemma (primary source)

*Status: COMPLETE — captured from the CARLA **0.9.16** source tree (tag commit `294096eb1c38eabf246e4f3a9cdab704e33a7f4c`), raw files fetched 2026-08-08.*

## 1. Scope

Defines exactly what CARLA 0.9.16 parses for a crosswalk `<object>` and how the
parsed data is transformed into world-space polygons. Any XODR written by this
pipeline MUST satisfy this schema; anything outside it is silently dropped.

## 2. Primary evidence

| File (tag 0.9.16) | Role |
| --- | --- |
| `Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Game/OpenDrive.cpp` | resolves the `.xodr` file path; content handed to the blueprint loader |
| `LibCarla/source/carla/opendrive/parser/ObjectParser.cpp` | the ONLY crosswalk-object parser |
| `LibCarla/source/carla/road/MapBuilder.cpp` (`AddRoadObjectCrosswalk`) | stores the parsed record |
| `LibCarla/source/carla/road/element/RoadInfoCrosswalk.h` | parsed record shape (`CrosswalkPoint{u,v,z}`) |
| `LibCarla/source/carla/road/Map.cpp` (`GetAllCrosswalkZones`) | local -> world transform |
| `LibCarla/source/carla/geom/Transform.h` + `Rotation.h` | rotation matrix used by `TransformPoint` |

## 3. Parser facts (ObjectParser.cpp)

- An object is a crosswalk iff `type == "crosswalk"` (exact, case-sensitive)
  **or** the lowercased `name` contains the substring `"crosswalk"`.
- Corners are read from **only** `<outline><cornerLocal u v z>`.
  `<cornerGlobal>`, `<cornerRoad>`, `<cornerParam>` are **ignored**.
  (Before this lemma, our writer emitted `cornerGlobal` — CARLA would parse an
  empty point list for every crosswalk.)
- `points.clear()` per outline: only the **last** `<outline>` contributes.
- Attributes read with `as_double()`, missing -> `0.0` (never an error):
  `s`, `t`, `zOffset`, `hdg`, `pitch`, `roll`, `width`, `length`, `name`,
  `type`, `orientation` (string).
- Everything is keyed to `node_road @id`; the crosswalk attaches to that road
  (`MapBuilder.GetRoad`). No validation of corner count, bounds, or closure.

## 4. Storage (MapBuilder::AddRoadObjectCrosswalk)

`RoadInfoCrosswalk(s, name, t, zOffset, hdg, pitch, roll, orientation, width,
length, points)` on the road's `_temp_road_info_container` (road-level info,
s-ordered). `GetHeading()` = hdg attribute; `GetT()` = t attribute.

## 5. Local -> world transform (Map::GetAllCrosswalkZones) — THE CODEC

For each `RoadInfoCrosswalk` on each road:

1. `base` = `ComputeTransform(waypoint{road, section, lane_id=0, s=crosswalk.s})`
   — position of the reference line at `s`, `base.rotation.yaw` = the reference
   line tangent heading at `s` (in **degrees**, CCW-positive in the XODR
   right-handed plane).
2. Lateral pivot: `pivot = base; pivot.rotation.yaw -= 90°;`
   `pivot.location = pivot.TransformPoint((t, 0, 0))` -> offset `t` along
   direction `(sin θ, -cos θ)` where `θ` = tangent heading (radians).
3. Restore: `pivot = base; pivot.location = (computed above);
   pivot.rotation.yaw -= hdg_deg` where `hdg_deg = 180/pi * GetHeading()`.
4. Each corner `(u, v, z)`: `v2 = (u, -v, z)`  **("Unreal Y axis hack")**,
   `world = pivot.TransformPoint(v2)`.

`Transform::TransformPoint` = rotate-then-translate with
`R(yaw) = [cos, -sin; sin, cos]` about +Z (Rotation.h `RotateVector`, roll =
pitch = 0). Degrees converted via `ToRadians`.

Closed form (roll = pitch = 0):

```
g     = theta - hdg                      # radians
pivot = (bx + t*sin(theta), by - t*cos(theta))
world.x = pivot.x + u*cos(g) + v*sin(g)
world.y = pivot.y + u*sin(g) - v*cos(g)
world.z = pivot.z + z
```

Inverse (encode: world -> u,v), valid because the matrix is its own inverse:

```
d = world_xy - pivot_xy
u = dx*cos(g) + dy*sin(g)
v = dx*sin(g) - dy*cos(g)
```

## 6. Writer contract (this pipeline)

For every authored crosswalk object:

- `type="crosswalk"`, `name` contains "crosswalk" (subtype `crosswalk_zebra`,
  `crosswalk_marked`, `crosswalk_signals` all satisfy).
- `<outline>` contains `cornerLocal u v z` corners **only** (5 corners,
  closed quad, `z=0`), computed with the R05 inverse codec from the OSM UTM
  quad, `t` = S07 `t_center`, `hdg` = OSM crossing bearing, `s` = S07 `s`.
- `u/v` are relative to the CARLA pivot defined by the road centreline pose at
  `s` (computed from the XODR planView via `opendrive_geometry.primitives`).
- Round-trip property: `carla_world(carla_local(outline, pose, t, hdg)) ==
  outline` exactly (verified by `tests/test_crosswalk_schema.py`).

## 7. Runtime representation

- Python API: `carla.Map.get_crosswalks()` / geometry pipeline exposes
  `GetAllCrosswalkZones()` results; `phase_l_validation.py` (live CARLA gate)
  is the end-to-end verifier: runtime polygons must match the OSM UTM quads
  within the lane-offset tolerance.
- Signals (`Speed_*`), stencils (`Stencil_*`) and every other object type are
  ignored for crosswalk purposes; buildings (`cornerGlobal`) are inert in
  0.9.16 (no parser path).

## 8. Implications for the tier-2 checks (fuzz / integration)

- An object with `type="crosswalk"` but no `cornerLocal` yields an empty
  point list — do NOT treat as a valid crosswalk in downstream consumers.
- `hdg`, `t`, `s` mis-match between XML and the road geometry rotates/shifts
  the polygon; the codec must use the same values end-to-end.
