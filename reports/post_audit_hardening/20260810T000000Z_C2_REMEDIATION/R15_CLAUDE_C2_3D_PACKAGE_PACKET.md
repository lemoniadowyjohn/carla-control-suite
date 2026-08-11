# R15 CORRECTED CLAUDE C2 3D PACKAGE PACKET (C2R2)

*Run: `20260810T000000Z_C2_REMEDIATION` · branch `fix/post-audit-phase-e-junctions-roundabouts-20260803` · freeze tag `c2_freeze_20260810T000000Z_C2R2`*

## Purpose

C2R2 corrects and completes the C2 3D-package evidence (C2R1 =
`c2_freeze_20260809T000000Z_C2`). It packages the full-map visual layer
(buildings/vegetation) as SOURCE_ADDED_VISUAL_LAYER (no longer LIVE_DEFERRED_C4),
decomposes the full-map and visual meshes per-feature against the governed XODR
(32,710 roads, corridor gate 6.5 m), and freezes a byte-exact full-map mesh
(combined roads + visual, sha `a147f4fe…`). Governed payload unchanged
(`248ffbbe…`). All offline — no CARLA runtime.

## Claimed anchors

| Anchor | Value |
| --- | --- |
| Parent freeze (C2R1) | `c2_freeze_20260809T000000Z_C2` → commit `36432027bf9be1cbc9b7ab66f39d2ff00062f877` |
| Lineage anchor (C1) | `c1_freeze_20260809T000000Z_C1` → commit `8b400351d13634104090b31e535ced6e6d748648` (`review_anchor_commit`, not parent) |
| Governed payload | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr` :: sha `248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c` (81,007,405 B) |
| Visual OSM input | `visual_osm_merged/ingolstadt_visual_merged_clean.osm` :: sha `61892da81b8e0b48f41acc90f9e12df83b1cb64b13ff7c5db913c17f17186725` (40,542,221 B) |
| XODR geometry frame | `+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs` (EPSG:32632-compatible native) |

## Environment reclassification (corrects C2R1)

C2R1 deferred all building/vegetation clutter to C4 because the authoritative
roads OSM extract contains no building/vegetation ways. C2R2 packages the visual
layer from the full-bbox visual OSM extract (`ingolstadt_visual_merged_clean.osm`):

- **Reclassification**: building/vegetation clutter `LIVE_DEFERRED_C4` →
  `SOURCE_ADDED_VISUAL_LAYER` with per-class counts from the visual OBJ:
  **Building 51,898 · trees 3,489 (= Tree 2,831 + TreeRow 658)** ·
  Forest 832 · SurfaceArea 2,804 · PoleFence 3,661 · others in
  `PART1_VISUAL_LAYER.json` / `PART3_FULLMAP_MESH.json`.
- `LIVE_DEFERRED_C4` now covers ONLY runtime items: collision volumes, actor
  binding, navmesh bake (server-gated, no waiver).
- Alignment guard (`C2_VISUAL_LAYER_ALIGNMENT_GUARD.json`) PASS:
  single-origin, origin within road bbox, mesh covers road bbox (1.0000),
  10/10 projection rule-outs, governed XODR unchanged.

## Part 2 — per-feature residual decomposition (frozen)

Producer `stage_c2_remediation_part2_feature_residuals.py` →
`PART2_FEATURE_RESIDUAL_DECOMPOSITION.json`, verdict
`PART2_FEATURE_DECOMPOSITION_PASS`.

- XODR primitives: **curve 29,162 / line 3,548** — curves are `paramPoly3`
  (CARLA Osm2Odr emits no `arc`/`spiral`); primitive-aware classification.
- Road classes (frozen): **STRAIGHT 228 · CURVE 157 · JUNCTION 31,937 ·
  ROUNDABOUT 66 · BRIDGE_TUNNEL 310 · CONNECTOR 12** (sum 32,710).
  Class order: CONNECTOR > ROUNDABOUT > BRIDGE_TUNNEL > JUNCTION > CURVE >
  STRAIGHT.
- Roundabouts: OSM-authoritative — `junction=roundabout` ways (135) matched to
  XODR centerlines (length 3–60 m, one-way, curved, road-side coverage ≥0.6
  within 3 m) → 66 roads. Rejected broad heuristics (26,496 / 14,917).
- Corridor gate (frozen): `CORRIDOR_RADIUS_M = 6.5` (lane half-width 3.5 +
  collision_lod_policy buffer 3.0). Vertices ≤6.5 m to nearest road polyline =
  road-associated and gated; beyond = off-road clutter, exempt.
- Case study road **64882**: fullmap max 508.307 m, visual max 572.304 m —
  SurfaceArea/Elevator/PoleFence/Tree plaza/street clutter, off-road → exempt → PASS.
- Crosswalk reference (`C2E_CROSSWALK_CORNER_ALIGNMENT.json`): 66 objects,
  330 corners, min 0.222 / mean 4.957 / median 4.343 / p95 10.282 / max 13.264 m —
  `CROSSWALK_ALIGNMENT_RESIDUALS_CAPTURED`.

## Part 3 — actual full-map mesh (byte-exact)

Producer `stage_c2_remediation_part3_fullmap_mesh.py` →
`PART3_FULLMAP_MESH.json`, verdict `PART3_FULLMAP_MESH_PASS`.

- `fullmap_mesh/scene_roads.obj`: road-surface mesh from governed XODR —
  32,708/32,710 roads emitted (2 skipped), 457,178 verts, 391,762 faces;
  disk sha `27b6052bed266b428c371c8189933e6178c08d35f5a94f0e3a4f03267d4d9903`.
- `fullmap_mesh/scene.obj` (combined = roads + visual layer): 3,616,900 verts,
  5,386,639 faces, 98,848 objects; **disk sha `a147f4fe9e34d8b8a6f32aaddd9de144f2b79e70b5c798fd2d5c7ab3476b9c2e`** —
  byte-exact (LF-normalized OBJ line endings; `sha256 == sha256_disk`, no CRLF drift).
- Visual layer OBJ unchanged: 3,159,722 verts / 4,994,877 faces / 66,140 objects;
  sha `15cdccbcd3374b79e63b590e6e591b9f4e4aa9b7abda6b260fb6f553e2d1907e`.
- Bbox coverage: combined covers 100% of the XODR road bbox
  (`FULL_MAP_BBOX_COVERED`; visual alone 97.5%: 224.606 vs 186.785 km²).
- Raw meshes gitignored; byte-exact disk shas recorded in
  `fullmap_mesh/fullmap_mesh_status.json` + `raw_artifacts_status.json`
  (both tracked).

## Projection / alignment carry-forward

- C2D 10/10 rule-outs re-confirmed by the visual-layer guard (no offset /
  double-origin / 165 km shift / axis inversion / 90° rotation / m-cm / 100× scale).
- OBJ origin WGS84 (48.74933925, 11.43245975) → native (839,966.7, 5,465,151.6),
  inside the XODR road bbox; mapping `xodr_x = origin_x + obj_x`,
  `xodr_y = origin_y − obj_z`, `xodr_z = obj_y`.
- Governed XODR identity unchanged (`248ffbbe…`); no CARLA runtime, no XODR edit.

## Acceptance chains (itemized)

1. **Visual clutter chain** — buildings/vegetation packaged
   (51,898 / 3,489 trees), per-class object counts match the mesh
   → SOURCE_ADDED_VISUAL_LAYER (OFFLINE_PROVEN).
2. **Per-feature residual chain** — full-map + visual meshes decomposed per
   road class; road-associated vertices within the frozen 6.5 m corridor;
   off-road clutter exempt (road 64882 case documented) → PART2_PASS.
3. **Full-map mesh chain** — combined mesh sha byte-exact on disk (LF, no
   CRLF drift), counts/bbox verified line-by-line → PART3_PASS.
4. **Projection/frame chain** — 10/10 rule-outs PASS, governed payload
   `248ffbbe…` unchanged → OFFLINE_PROVEN.
5. **Runtime chain** — collision volumes, actor binding, navmesh bake →
   LIVE_DEFERRED_C4 (server-gated).

## Freeze

- freeze_schema: `C2R_TAG_ANCHORED_V2`
- freeze_tag: `c2_freeze_20260810T000000Z_C2R2`
- parent_commit: `e554da2ce1cdc77e74f7c72baeeac9a48b799c7f` (the immediate git
  parent of the freeze commit == `tag^{commit}~1`, the remediation evidence commit)
- review_anchor_commit (C1 lineage): `8b400351d13634104090b31e535ced6e6d748648`
  (kept distinct from parent_commit — C2R1 nit fixed).
- NO head_commit / tag-object sha inside committed JSONs (non-circular; the
  annotated tag message carries freeze_commit, freeze_tree, branch, r15 sha256,
  r15b sha256, manifest sha256, governed payload sha, mesh sha).
- review invariant: no commits after tag creation; worktree clean;
  `tag^{commit} == HEAD`.

## Verification

Evidence JSONs (PART1/PART2/PART3, guard, status) record ALL PASS verdicts.
`verify_post_audit_hardening.py` ALL PASS; governed payload unchanged;
raw meshes gitignored with byte-exact disk hashes tracked.
