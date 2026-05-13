# Enrichments and Building Visibility in CARLA

## Overview

The pipeline supports enriching OpenDRIVE maps with additional objects such as:
- Buildings (from GeoJSON or OSM footprints)
- Traffic lights
- Street furniture (benches, poles, fences)
- Realism objects (parking lots, vegetation zones)

These enrichments are stored as `<object>` elements within the OpenDRIVE XML structure.

## Important: Buildings Do NOT Automatically Appear in CARLA

**OpenDRIVE `<object>` elements do NOT produce visible 3D meshes when loading an XODR file into CARLA.**

The CARLA OpenDRIVE importer (`carla.Client.generate_opendrive_world()`) only uses:
- Road geometries (planView)
- Lane definitions
- Junction connections
- Traffic signals (as spawn points, not meshes)

Buildings and other `<object>` entries are stored in the XODR for data completeness and potential downstream use, but **CARLA does not render them**.

## Options for Visualizing Buildings

### Option 1: Runtime Actor Spawning (Recommended for Quick Visualization)

Use the provided script to spawn simple proxy actors (cubes/props) at building locations:

```bash
python -m ultimate_pipeline.carla_tools.spawn_enrichments enrichments.json --host localhost --port 2000
```

This spawns placeholder actors that represent building footprints. Useful for:
- Quick visual checks
- Understanding spatial layout
- Testing occlusion effects

Limitations:
- Simple geometry (boxes only)
- No realistic textures
- Performance impact with many objects

### Option 2: Custom UE4/UE5 Project (Production Quality)

For realistic 3D buildings, you need to:

1. Import the XODR into a custom Unreal Engine project
2. Use a mesh generation pipeline that reads `<object>` elements
3. Generate building meshes from footprint data + height attributes
4. Package as a CARLA-compatible map

This approach is used for production-quality maps but requires:
- UE4/UE5 development expertise
- Custom asset pipeline
- Significant development time

### Option 3: Post-Processing with External Tools

Export building data to formats compatible with external tools:
- GeoJSON for GIS visualization
- CityGML for 3D city modeling
- Custom formats for game engine imports

## Where Enrichment Data is Stored

The pipeline produces several enrichment artifacts:

| File | Contents |
|------|----------|
| `buildings.geojson` | Building footprints with heights |
| `enrichments.json` | All enrichment objects (buildings, furniture) |
| Final XODR | `<object>` elements embedded in road sections |

## Related Pipeline Settings

```python
# In ultimate_pipeline/config/settings.py

ENABLE_BUILDING_INJECTION = True   # Add building footprints to XODR
ENABLE_TRAFFIC_LIGHTS = True       # Infer traffic lights at junctions
ENABLE_REALISM = True              # Add street furniture objects
```

## Technical Details

### Building Data Sources (Priority Order)

1. `buildings.geojson` - Pre-processed GeoJSON footprints
2. `osm.xml` - Raw OSM data (fallback)
3. None - Buildings skipped if no source available

### Object Attributes Stored

Each `<object>` in the XODR includes:
- Position (s, t relative to road, or absolute x/y)
- Dimensions (width, height, length)
- Type classification
- Orientation (heading)
- Optional metadata (name, source)

## Summary

| Approach | Complexity | Visual Quality | Use Case |
|----------|------------|----------------|----------|
| spawn_enrichments.py | Low | Basic | Debug/preview |
| Custom UE project | High | Production | Final maps |
| External tools | Medium | Varies | Analysis/export |

For most development and testing purposes, the pipeline's XODR output is fully functional for driving simulation - buildings are supplementary data that can be visualized separately when needed.
