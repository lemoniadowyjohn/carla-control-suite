# J5R A2 Visual Asset Transform Chain Documentation

## Transform Chain Summary

### OSM2World origin
OSM2World produces local tmerc coordinates; OBJ header declares WGS84 origin

- **Origin WGS84**: {
  "lat": 48.74933435,
  "lon": 11.43242175
}
- **Transform Matrix**: WGS84 → Osm2ODR-native tmerc(lat_0=0, lon_0=0, k=1, x_0=0, y_0=0)
- **Units**: meters
- **Scale**: 1.0
- **Source of Truth**: F1 PHASE_1A_DIAGNOSIS.md: Osm2ODR wheel probe confirms native tmerc frame

- **Verdict**: Osm2ODR geometry is native tmerc (not reprojected to header CRS)

### Blender
Blender scene import/export for FBX conversion

- **Origin WGS84**: {}
- **Transform Matrix**: OSM2World tmerc → Blender local (unity, axes standardized)
- **Units**: meters
- **Scale**: 1.0
- **Source of Truth**: Blender manifest (ingolstadt_cooked_perception_v1_b9e07465_window_osm.blender_manifest.json)

- **Verdict**: Blender axes standardized without hidden transforms; no axis reflection

### FBX
FBX binary export from Blender for CARLA import

- **Origin WGS84**: {}
- **Transform Matrix**: Blender local tmerc → FBX binary (unity, no scale/rotation)
- **Units**: {'global_scale': 1.0, 'metres': 1.0, 'note': '1 Blender unit = 1 meter'}
- **Scale**: 1.0
- **Source of Truth**: Blender manifest + FBX provenance (ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx.provenance.json)

- **Verdict**: FBX export uses global_scale=1.0, axes consistent with OBJ

### CARLA/Unreal
CARLA/UE4 import of FBX visual assets

- **Origin WGS84**: {}
- **Transform Matrix**: FBX right-handed → Unreal left-handed (axis swap + scale)
- **Units**: 
- **Scale**: 0.01
- **Source of Truth**: Unreal Engine 4.26 coordinate system specification; CARLA FBX importer conventions

- **Verdict**: CARLA uses UE4.26 left-handed X-forward Y-right Z-up, metres to centimetres scale

### Map Local Origin
Final map coordinate system for CARLA/Unreal world

- **Origin WGS84**: {}
- **Transform Matrix**: Native tmerc(local OSM2World frame) → Map local origin (based on XODR header)
- **Units**: 
- **Scale**: 1.0
- **Source of Truth**: OpenDRIVE <header> north/south/east/west attributes (EPSG:32632 header, but geometry in native tmerc)

- **Verdict**: Map origin derived from XODR header; geometry in native tmerc (verified F1)

## Transform Chain Integrity Verification

- **Chain Integrity**: PASS
- **Issues Detected**: 0
## Summary

