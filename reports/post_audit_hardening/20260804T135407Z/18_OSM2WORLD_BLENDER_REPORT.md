# 18 OSM2World + Blender/FBX enrichment report (Phase J rollup)

- Phase J run: `20260804T130959Z`
- Verdict: `J1_PASS; J4_OK; J5_MISALIGNED; J7_PASS; J8_PASS; J6_PASS`

## J2 Naming
- <map_id>_<campaign_id>_<source_hash_prefix>_<tile_id>.<ext> = ingolstadt_cooked_perception_v1_b9e07465_window_osm.<ext>

## J1 Structural validation
- OBJ: True
- MTL: True
- GLB: True (json_utf8=True)

## J4 Semantic partition
- classes: ['elevator', 'ground']

## J5 Coordinate control (critical finding)
- verdict: `MISALIGNED`
- OBJ origin is 165942.9 m from the nearest XODR road control point: the source OSM and the XODR map do not describe the same region (origin-shift)

## J6 FBX round-trip
- ROUNDTRIP_PASS

## J7 Collision + LOD
- collision: PASS
- lod: POLICY_DECLARED

## J8 Detached slabs
- PASS

## J3 Blender manifest highlights
- blender: Blender 4.3.0
- FBX: FBX binary int=7400
- determinism: DETERMINISTIC
