# OSM2World building-source fix: real buildings now reach the visual-clutter FBX (2026-09-15)

Full detail: `SUMMARY.json` in this directory. This file is a short human-readable pointer.

- Run ID: `20260915T123949Z_OSM2WORLD_BUILDING_SOURCE_FIX`
- Base repo commit: `c8108ecab2f2a75c941b83217650806f15f21bcb` (`integration/session-batch1-20260912`)
- Branch: `feature/osm2world-building-source-fix-v1-20260915`
- Map-of-record (untouched by this task): `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr` (road geometry, not touched)

## Problem being fixed

A prior task (`reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/`) found that
`ultimate_pipeline/main_pipeline.py`'s `_run_osm2world_visual_stage` fed `OSM2WorldRunner` from
`settings.OSM_FILE` alone -- a roads-oriented Overpass export
(`ingolstadt_authoritative.osm`, `building_way_count: 1`). The pin's real 5,693 building ways live in a
**separate** file, `ingolstadt_buildings_overpass.json`, in Overpass "out geom" JSON format that
OSM2World cannot read (it only accepts `.osm`/`.osm.xml`/`.pbf`). Every FBX this pipeline had ever
produced via that stage was therefore near-empty full-map clutter (61 objects / 975 vertices for the
whole city), not a real building-volume reconstruction.

## What this task built

### 1. Converter: `ultimate_pipeline/enrichment/overpass_to_osm_xml.py`

Two public functions:

- `convert_overpass_json_to_osm_xml(overpass_json_path, output_osm_path, emit_relations=False)` --
  parses Overpass "out geom" JSON (`elements`: `way`/`relation` objects, each carrying an embedded
  `geometry` array of `{lat, lon}` points plus `tags` -- the same shape
  `ultimate_pipeline.enrichment.osm_polygon_loader.OSMPolygonLoader.load_buildings_from_geojson` already
  parses for OpenDRIVE building-footprint insertion) and synthesizes a minimal, valid OSM XML document:
  - One `<node>` per **distinct** coordinate, deduplicated by rounding to OSM's own 1e-7-degree
    precision (~1.1cm), so ways/rings that share a corner in the source data share one synthesized node
    in the output. This directly targets the "polygon must not have duplicate points" failure mode
    OSM2World's IndoorModule hit in the prior task.
  - One `<way>` per source way (and per multipolygon relation's outer member way(s)), referencing its
    deduplicated node ids in order, carrying that way's/relation's original `tags` verbatim
    (`building`, `height`, `building:levels`, `name`, etc. -- nothing dropped).
  - Node ids and way ids are synthetic, negative, and drawn from disjoint ranges (nodes from `-1`
    downward, ways from `-1,000,000,000` downward) -- standard OSM convention for "new" elements,
    guaranteed not to collide with any real (always-positive) OSM id from a roads file merged in later.
  - Multipolygon relations (courtyard/multi-part buildings) are flattened to their outer ring(s), tagged
    with the relation's own tags -- mirrors `OSMPolygonLoader`'s own C25/C28 convention (inner-ring
    holes are a documented, accepted minor over-fill). `emit_relations=True` additionally emits
    `<relation type="multipolygon">` elements if a caller needs true multipolygon semantics.

- `merge_osm_xml_files(primary_osm_path, secondary_osm_path, output_osm_path)` -- combines two OSM XML
  files into one (used to merge a roads `.osm` with the converted-buildings `.osm`, since
  `OSM2WorldRunner`'s CLI only accepts a single `-i` input). Renumbers any genuinely colliding ids in the
  secondary file into unused negative space and rewrites `<nd ref>`/`<member ref>` accordingly; on the
  real pin (roads uses positive ids, buildings converter uses negative ids) zero renumbering was needed.

Not hardcoded to Ingolstadt: both functions take arbitrary paths, and the pipeline wiring below reads
`settings.PINNED_BUILDINGS_SOURCE` (already a per-campaign, env-overridable setting) rather than a fixed
filename.

Tests: `ultimate_pipeline/tests/unit/test_overpass_to_osm_xml.py` (16 tests) -- node/way count
correctness, tag preservation (including relation-tags-on-outer-way), synthetic-id disjointness/
uniqueness, coordinate deduplication, closed-ring invariant, `<nd ref>` referential integrity, an
end-to-end check that the converter's own output round-trips through this codebase's existing
`OSMPolygonLoader.load_buildings_from_osm` reader, and merge-specific tests (no-collision path,
genuine-collision renumbering path, merged-output still loadable).

### 2. Pipeline wiring: `ultimate_pipeline/main_pipeline.py`

New module-level helper `_resolve_osm2world_input_path(settings_obj, cache_dir)`, called from
`_run_osm2world_visual_stage` right before constructing `OSM2WorldRunner`:

- If `settings.PINNED_BUILDINGS_SOURCE` is unset/missing, or `settings.OSM_FILE` is missing, or the
  buildings source is not `.json` (already OSM XML -- nothing to convert), or conversion/merge raises
  for any reason: falls back to the **old, unchanged** behaviour (`osm_path = settings.OSM_FILE` alone).
  This stage is optional/supplemental and must never turn a buildings-source problem into a hard
  pipeline failure.
- Otherwise: converts the buildings JSON and merges it with the roads file into
  `<out_dir>/osm2world_input/{converted_buildings.osm,merged_roads_and_buildings.osm}`, and passes the
  **merged** path to `OSM2WorldRunner` instead.
- The resolution outcome (`source`, `buildings_source`, `reason`, `convert_stats`, `merge_stats`) is
  recorded in the stage's JSON receipt (`osm2world_pipeline_stage.json`) under the new
  `osm2world_input_resolution` key, for provenance/debugging.

New tests in `ultimate_pipeline/tests/unit/test_osm2world_pipeline_wiring.py` (7 new tests, 13 total in
that file): the resolver's 5 fallback/merge branches directly, plus one end-to-end test asserting
`_run_osm2world_visual_stage` actually passes the merged `osm_path` (not the bare roads file) to
`OSM2WorldRunner` when a real buildings source is configured. All 6 pre-existing tests in that file still
pass unmodified -- the default `SimpleNamespace` test fixture has no `PINNED_BUILDINGS_SOURCE` attribute
at all, exercising the `getattr(..., "")`-then-fallback path for free.

Change is narrowly scoped: only `_run_osm2world_visual_stage`'s `osm_path` resolution changed. No other
stage, and no OpenDRIVE/road-authority code, was touched.

## Regeneration against the real pin

| Stage | Status | Duration | Key output |
|---|---|---|---|
| Convert (Overpass JSON -> OSM XML) | ok | 1.62s | `artifacts/converted_buildings.osm` (5711 ways, 27188 nodes, 0 skipped-degenerate) |
| Merge (roads + buildings) | ok | 5.33s | `artifacts/merged_roads_and_buildings.osm` (15,116,883 bytes; 0 id collisions/renumbers) |
| OSM2World (OBJ+PNG+GLB) | `ok` (OBJ/PNG passed; GLB rejected by validator, pre-existing issue -- see below) | 65.9s | `artifacts/osm2world/ing..._merged_full_pin.obj` (102,852 v / 162,313 f / 5,838 groups, 13,495,272 bytes) |
| Blender OBJ->FBX | `ok` | 24.8s | `artifacts/ing_f3e82001_merged.fbx` (15,495,996 bytes, **5,772 objects / 108,827 v / 162,313 f**, 15 materials) |
| fbx_roundtrip.py | `ROUNDTRIP_PASS` | ~seconds | **5772/5772 objects match, 0 missing, 0 extra, 0 field diffs** |

### Object/vertex counts: before vs. after

| | Before (roads-only, `20260915T101124Z_FBX_REGEN_CURRENT_PIN`) | After (roads+buildings merged, this task) |
|---|---|---|
| OBJ vertices | 945 | 102,852 (109x) |
| OBJ faces | 876 | 162,313 (185x) |
| OBJ groups | 72 | 5,838 (81x) |
| FBX objects | 61 | 5,772 (95x) |
| FBX vertices | 975 | 108,827 (112x) |
| FBX materials | 6 | 15 |
| FBX file size | 149,180 bytes | 15,495,996 bytes (104x) |

Source data: 5,693 building ways / 19 relations in the pin's `ingolstadt_buildings_overpass.json`
(sha256 `f3e82001...`, matches `campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json`
exactly). The converter emitted 5,711 usable ways (5,693 direct ways + 18 relation outer rings; one of
the 19 relations produced 0 usable outer members after the degenerate-ring filter). OSM2World's own
per-object rendering (materials, LOD, roof/wall decomposition) explains why FBX object count (5,772,
close to but not identical to the 5,711 input ways) differs slightly from raw way count -- some ways
render as multiple mesh objects (e.g. separate roof/wall groups), some adjacent/degenerate ones are
dropped or merged by OSM2World's own geometry pipeline. This is consistent with, not a discrepancy from,
"real buildings are now rendering."

### GLB path: same pre-existing issue as the prior task, not caused by this change

OSM2World's stderr for the merged input shows the identical 3 pre-existing errors from the *roads* file
that the prior task already documented and root-caused to `ingolstadt_authoritative.osm`'s indoor/
elevator tagging (not the buildings file this task added):

```
ERROR[w462314990]: polygon must not not have duplicate points
ERROR[w359550749]: polygon must not not have duplicate points
ERROR[w359550745]: polygon must not not have duplicate points
```

Same three way ids (`w462314990`, `w359550749`, `w359550745`) as the prior run -- confirms this is the
roads file's pre-existing `IndoorModule$Elevator` bug, not something introduced by the buildings merge or
the converter. OBJ/PNG generation tolerates it (3 objects silently dropped); GLB generation crashes on it
and produces an invalid `.glb` that Blender's own import validator correctly rejects
(`Bad glTF: json error: utf-8`), exactly as before. `osm2world_runner.py`'s validator caught this and
excluded the invalid GLB from `outputs`, so no bad artifact was silently accepted.

### No new duplicate-point failures from the converter's own output

Verified directly: zero consecutive-duplicate `<nd ref>` pairs across all 5,711 converter-emitted ways in
`converted_buildings.osm`, and the 3 errors above are exclusively against roads-file way ids (not any of
the converter's synthetic negative way ids). The coordinate-rounding dedup design worked as intended.

### Timing/memory

No new timing or memory problems. Convert (1.6s) + merge (5.3s) + OSM2World (65.9s) + Blender (24.8s) +
roundtrip (a few seconds) totals under two minutes end-to-end against the full 15.1MB merged
(11.2MB roads + 3.9MB buildings) source, well under the 1800s/600s configured timeouts.

## Files in this directory

- `SUMMARY.json` -- full structured provenance (hashes, commands, timings, findings)
- `build_merged_osm.py` -- driver that ran the converter + merge against the real pin, wrote
  `artifacts/merge_summary.json`
- `run_osm2world.py` -- driver that ran `OSM2WorldRunner` against the merged OSM XML
- `run_blender.py` -- driver that ran `BlenderRunner` (OBJ -> FBX) against the OSM2World OBJ output
- `run_roundtrip.py` -- driver used to invoke `fbx_roundtrip.run_fbx_roundtrip()`
- `artifacts/` -- all raw outputs: `converted_buildings.osm`, `merged_roads_and_buildings.osm`,
  `merge_summary.json`, OSM2World's OBJ/MTL/PNG/GLB + status + logs, the FBX, Blender conversion
  manifest + status + logs, and the roundtrip manifest/report/logs

This directory does not overwrite or modify
`reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/` or
`reports/post_audit_hardening/20260804T125500Z/`, both of which remain on disk unchanged.
