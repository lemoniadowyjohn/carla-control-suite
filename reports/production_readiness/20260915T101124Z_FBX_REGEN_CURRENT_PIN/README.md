# FBX regen against the current pinned map (2026-09-15)

Full detail: `SUMMARY.json` in this directory. This file is a short human-readable pointer.

- Run ID: `20260915T101124Z_FBX_REGEN_CURRENT_PIN`
- Repo commit: `8408d3df1b6673e5341b56e95adf3bed6b6073b7` (integration/session-batch1-20260912)
- Map-of-record (untouched by this task): `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr` (sha256 `2ca342d8...`)
- OSM source used: `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm`, sha256 `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`, 11,154,738 bytes -- the FULL file (74874 nodes / 17250 ways), matching the pin's `INPUTS_MANIFEST.json` `roads_osm` entry exactly. The stale `reports/post_audit_hardening/20260804T125500Z/` artifacts used a 773,744-byte bounding-box CLIP of this same file; this run is the full extent, not a different source.

## Result

| Stage | Status | Duration | Key output |
|---|---|---|---|
| OSM2World (OBJ+PNG+GLB) | `ok` (OBJ/PNG passed; GLB rejected by validator) | 52.0s | `artifacts/scene.obj` (945 v / 876 f / 72 groups, 49,199 bytes) |
| Blender OBJ->FBX | `ok` | 6.3s | `artifacts/ingolstadt_cooked_perception_v1_b9e07465_full_pin.fbx` (149,180 bytes, 61 objects, 975 v / 876 f, 6 materials) |
| fbx_roundtrip.py | `ROUNDTRIP_PASS` | ~seconds | 61/61 objects match, 0 missing, 0 extra, 0 field diffs |

## Findings (task item 5: does the scaffold hold up at real scale?)

1. **A real OSM2World bug surfaced at full scale, not visible in the old 773KB test window.**
   `org.osm2world.world.modules.building.indoor.IndoorModule$Elevator` throws
   `InvalidGeometryException: polygon must not not have duplicate points` on 3 ways
   (w462314990, w359550749, w359550745) somewhere in the full file's indoor/elevator
   tagging. OSM2World's own fault-tolerant iteration silently drops the 3 offending
   objects in the OBJ pass and continues (harmless to this task); the same error
   crashes the GLB pass outright, producing a `scene.glb` that fails Blender's own
   gltf-import validation (`Bad glTF: json error: utf-8`). The `osm2world_runner.py`
   validator correctly caught this and excluded the invalid GLB from `outputs`, so no
   bad artifact was silently accepted. Net effect: **OBJ/FBX path unaffected, GLB path
   currently broken at this input's full scale.**

2. **No timing or memory problems at all.** Total wall-clock for OSM2World + Blender
   + roundtrip was about a minute against the full 11.1MB / 74,874-node source, well
   under the 1800s/600s configured timeouts. This was faster than expected.

3. **Architectural gap, not a bug: OSM2World is wired to the roads file, not the
   buildings file.** `ultimate_pipeline/main_pipeline.py`'s
   `_run_osm2world_visual_stage` feeds `OSM2WorldRunner` from `settings.OSM_FILE`,
   which resolves to `ingolstadt_authoritative.osm` -- and that file is documented
   (`campaigns/ingolstadt_cooked_perception_v1/source/manifest.json`) to have
   `building_way_count: 1`. The pin's actual 5,693 building ways live in a **separate**
   file, `ingolstadt_buildings_overpass.json`, in Overpass-JSON format that OSM2World
   cannot consume directly (it only reads `.osm`/`.osm.xml`/`.pbf`). No
   Overpass-JSON-to-OSM-XML converter exists in this codebase today. This run is
   therefore a faithful full-extent run of the pipeline's **actual current wiring**,
   and produces genuine (not placeholder) full-map clutter geometry -- but it is
   **not** a full building-volume reconstruction of the pin's 5,682/5,693 real
   buildings. Closing that gap is a distinct, larger follow-up task (write a
   buildings-JSON -> OSM-XML bridge, or point OSM2World at a merged file), out of
   scope for "run the existing scaffold."

## Files in this directory

- `SUMMARY.json` -- full structured provenance (hashes, commands, timings, findings)
- `run_roundtrip.py` -- driver script used to invoke `fbx_roundtrip.run_fbx_roundtrip()`
  (the module itself has no CLI entry point)
- `artifacts/` -- all raw outputs: `scene.obj`/`.mtl`/`.png`/`.glb`, OSM2World status +
  logs, the FBX, Blender conversion manifest + status + logs, and the roundtrip
  manifest/report/logs

This directory does not overwrite or modify `reports/post_audit_hardening/20260804T125500Z/`,
which remains on disk unchanged.
