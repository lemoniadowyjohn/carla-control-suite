# Design: New Drivable-Surface / Hole-Analysis Stage (Stage 8G)

## Purpose

After Stage 8 (LaneLinks + Markings + Integrity) produces `final_out`, run a deterministic offline scan for drivable-surface discontinuities — "potholes" in the XODR topology that would cause CARLA to drop vehicles or produce unrealistic physics.

## Design

### Stage Placement

Insert as **Stage 8G** between Stage 8 (final integrity) and Stage 9 (tiling), after `repair_and_assert_lane_section_successors`:

```
STAGE 8 (final_out) → STAGE 8G (hole_analyzed) → STAGE 9 (tiling)
```

### Algorithm

```
For each <road> in XODR:
  For each <laneSection> in road:
    For each <lane> with type="driving":
      1. Find the lane's successor lane:
         - Follow <link><successor> to the target road/laneSection/lane
      2. Compute the geometric gap:
         - Last s-coordinate of predecessor lane geometry
         - First s-coordinate of successor lane geometry
         - Threshold: gap > 0.5m → "hole"
      3. Compute the heading discontinuity:
         - Heading at predecessor end vs successor start
         - Threshold: delta_heading > 5° → "seam"
      4. Compute the elevation discontinuity:
         - Elevation at predecessor end vs successor start
         - Threshold: delta_z > 0.3m → "drop"
  
  For each <junction> in XODR:
    For each <connection> in junction:
      Verify connecting road's entry/exit lanes exist in both directions
      "dead_connection" if either side missing
```

### Output

```json
{
  "total_holes": 47,
  "total_seams": 3,
  "total_drops": 12,
  "total_dead_connections": 0,
  "holes": [
    {"road_id": 1024, "s": 342.1, "gap_m": 1.2, "type": "missing_successor"},
    {"road_id": 2048, "s": 567.8, "gap_m": 0.7, "type": "lane_type_mismatch"}
  ],
  "seams": [
    {"road_a": 512, "road_b": 768, "heading_deg": 7.2}
  ],
  "drops": [
    {"road_a": 1280, "road_b": 1536, "z_diff_m": 0.45}
  ],
  "ok": false
}
```

### Gate Integration

Hook into `_stage_gate("08G", "drivable_surface", lambda: scan_holes(final_out))`.

In `structural_release` profile with `strict_quality_gates=True`, any non-zero hole count should be fail-closed (except known false positives from intentional dead-end lanes).

### Toggle

```python
# In settings.py
UP_ENABLE_DRIVABLE_SURFACE_HOLE_SCAN: bool = True
UP_DRIVABLE_SURFACE_HOLE_THRESHOLD_M: float = 0.5
UP_DRIVABLE_SURFACE_SEAM_THRESHOLD_DEG: float = 5.0
UP_DRIVABLE_SURFACE_DROP_THRESHOLD_M: float = 0.3
```

### Implementation Location

New file: `ultimate_pipeline/quality/drivable_surface_scanner.py`

```
DrivableSurfaceScanner.scan(xodr_path, hole_threshold_m=0.5, seam_threshold_deg=5.0, drop_threshold_m=0.3) → dict
```

### Integration in main_pipeline.py

```python
# After stage 8 final_out, before stage 9
if getattr(s, "ENABLE_DRIVABLE_SURFACE_HOLE_SCAN", True):
    from ultimate_pipeline.quality.drivable_surface_scanner import DrivableSurfaceScanner
    self._stage_gate(
        "08G",
        "drivable_surface",
        lambda: DrivableSurfaceScanner.scan(final_out, ...)
    )
```

### Validation

Run against the loaded map (8,535 spawn points, 155,491 waypoints) to establish baseline. Any drivable-surface hole > 0.5m should be flagged and gated.
