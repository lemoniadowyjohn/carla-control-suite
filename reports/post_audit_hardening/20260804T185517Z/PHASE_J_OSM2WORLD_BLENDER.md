# Phase J: OSM2World + Blender/FBX enrichment evidence

- Run ID: `20260804T185517Z`
- Verdict: `J1_PASS; J4_OK; J5_ALIGNED; J7_PASS; J8_PASS; J6_PASS`
- Evidence directory: `reports/post_audit_hardening/20260804T185517Z/`

## J2 Artifact naming
- Scheme: `<map_id>_<campaign_id>_<source_hash_prefix>_<tile_id>.<ext> = ingolstadt_cooked_perception_v1_b9e07465_window_osm.<ext>`

## J1 OBJ/GLB/MTL structural validation
### J1_obj: PASS
- exists: ok (1226 bytes)
- empty_file: ok (1226 bytes)
- vertex_count: ok (19)
- face_count: ok (17)
- normal_count: ok (1)
- uv_count: ok (0)
- bounds: ok ({'x_min': 124.092, 'y_min': 0.0, 'z_min': 256.535, 'x_max': 156.762, 'y_max': 0.0, 'z_max': 310.166})
- finite_coordinates: ok (19)
- coordinate_magnitude: ok (max |coord| = 310.2 m (limit 10000000 m))
- degenerate_faces: ok (0)
- duplicate_objects: ok ({})
- empty_objects: ok ({})
- material_library: ok ({'ingolstadt_cooked_perception_v1_b9e07465_window_osm.obj.mtl': True})
- input_hash_linkage: ok (b9e074656f74)
- artifact_hash_match: ok (88d153348f00)
### J1_mtl: PASS
- materials: ok (['MAT_0_0'])
- texture_references: ok ({})
### J1_glb: PASS
- exists: ok (4052 bytes)
- magic: ok (glTF)
- version: ok (2)
- total_length: ok (4052 vs 4052)
- json_utf8: ok (utf-8 decode ok)
- json_valid: ok (JSON parse ok)
- accessor_bounds: ok ([])
- accessor_count: ok (3)

## J4 Semantic partition
- objects: 3
- `elevator`: 2 objects, 0 faces, materials=[]
- `ground`: 1 objects, 17 faces, materials=['MAT_0_0']

## J5 Coordinate control points
- Verdict: `ALIGNED`
- OBJ header origin (WGS84): `{'lat': 48.74933435, 'lon': 11.43242175, 'ele': 0.0}`
- OBJ origin in XODR frame: `[839964.008386947, 5465150.607499553]`
- Nearest XODR road control point: 284.7 m
- Detail: OSM window forward-projected via the verified Osm2Odr-native tmerc frame overlaps the XODR road bbox (5304311.8 m^2) and the OBJ origin (839964.0, 5465150.6) falls within the XODR road bbox.

## J7 Collision + LOD
- Collision verdict: `PASS` (0 intrusions, 0 violations)
- Corridors checked: 2000

## J8 Detached-slab validation
- Verdict: `PASS`
- exact duplicate faces: 0
- coplanar overlapping pairs: 0
- degenerate faces: 0
- floating slabs: 0

## J6 FBX round-trip
- ok: True
- verdict: `ROUNDTRIP_PASS`

## Determinism (J2 stable naming)
- verdict: `DETERMINISTIC`
- byte-identical: True
- object names equal: True

## J3 Blender manifest
- status: `ok`
- blender: `Blender 4.3.0` (exe sha256 e5c09e875471…)
- script sha256: 1f63f0be20c2da9c…
- exit code: 0
- fbx: C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260804T185517Z\artifacts\ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx
- FBX header: `Kaydara FBX Binary` (version FBX binary int=7400)
- units: METRIC scale 1.0
- import: wm.obj_import {'filepath': 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\ingolstadt_cooked_perception_v1_b9e07465_window_osm.obj'}
- export axes: forward=-Z, up=Y, global_scale=1.0
- objects: 1, materials: 1, images: 0
- input obj sha256: 88d153348f004537…
- output fbx sha256: 96a18cc8b369b868…

## Window clip (J2 input)
- source: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\source\ingolstadt_authoritative.osm`
- source sha256: `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`
- window: {'lon_min': 11.418828570940956, 'lon_max': 11.446091429059045, 'lat_min': 48.74032693105002, 'lat_max': 48.75835306894997}
- nodes 4670, ways 1225, relations 0
- bytes: 773744
- method: verbatim deep-copy of in-window elements (dynsax-safe)

## OSM2World run
- status: `ok`
- reason: Generated 3 outputs: scene.obj, preview.png, scene.glb
- jar: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\carla_governed\OSM2World-latest-bin\OSM2World.jar`
- java: openjdk version "17.0.17" 2025-10-21
- command: [['java', '-jar', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\carla_governed\\OSM2World-latest-bin\\OSM2World.jar', 'convert', '-i', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\window_osm.osm', '-o', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\ingolstadt_cooked_perception_v1_b9e07465_window_osm.obj', '--config', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\osm2world.properties'], ['java', '-jar', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\carla_governed\\OSM2World-latest-bin\\OSM2World.jar', 'convert', '-i', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\window_osm.osm', '-o', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\ingolstadt_cooked_perception_v1_b9e07465_window_osm.png', '--config', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\osm2world.properties'], ['java', '-jar', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\carla_governed\\OSM2World-latest-bin\\OSM2World.jar', 'convert', '-i', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\window_osm.osm', '-o', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\ingolstadt_cooked_perception_v1_b9e07465_window_osm.glb', '--config', 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\osm2world.properties']]
- outputs: {'scene.obj': 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\ingolstadt_cooked_perception_v1_b9e07465_window_osm.obj', 'preview.png': 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\ingolstadt_cooked_perception_v1_b9e07465_window_osm.png', 'scene.glb': 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\post_audit_hardening\\20260804T185517Z\\artifacts\\ingolstadt_cooked_perception_v1_b9e07465_window_osm.glb'}
- duration: 24.558 s
- GLB valid: True (GLB header valid)
