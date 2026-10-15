# Affected Mesh Diagnostics

Generated offline by `scripts/analyze_mesh_geometry.py`. All values measured from
artifact bytes; none assumed. No Blender, no UE4, no CARLA.

## Method

- OBJ: exact parse of Wavefront OBJ (v/vn/vt/f); areas and channels computed in float64
- FBX: ascii node-name byte search over the FBX payload to determine which vertex layers exist; binary FBX stores node names as plain ascii so presence/absence is an exact test
- Not done: FBX *geometry* is not parsed: Blender's FBXHeaderExtension writes a name length one byte short of the name it emits, so a hand-rolled binary geometry parser could not be trusted. Geometric metrics come from the OBJ instead, which is exact.

## Aggregate (OBJ geometry)

| metric | value |
| --- | --- |
| meshes | 2 |
| faces | 18708 |
| vertices | 11954 |
| degenerate_faces | 0 |
| zero_area_faces | 0 |
| sliver_faces | 0 |
| collinear_faces | 0 |
| uv_degenerate_faces | 18708 |
| tangent_degenerate_faces | 18708 |
| near_zero_binormal_faces | 18708 |
| vertices_without_normal | 0 |
| non_unit_normals | 0 |
| meshes_without_uv | 2 |
| meshes_without_smoothing | 2 |
| meshes_without_normals | 0 |

## Files

| path | source | phase | UV layer | smoothing layer | normals |
| --- | --- | --- | --- | --- | --- |
| reports\production_readiness\20260924T100614Z_FULL_GRID_TILE_FBX_COOK\artifacts\tile_10_9\Ingolstadt_Tile_10_9.obj | obj | - | NO | n/a (OBJ `s`) | yes |
| reports\production_readiness\20260924T100614Z_FULL_GRID_TILE_FBX_COOK\artifacts\tile_6_6\Ingolstadt_Tile_6_6.obj | obj | - | NO | n/a (OBJ `s`) | yes |
| reports\production_readiness\20260924T100614Z_FULL_GRID_TILE_FBX_COOK\artifacts\tile_10_9\Ingolstadt_Tile_10_9.fbx | fbx | before | NO | NO | yes |
| reports\production_readiness\20260924T100614Z_FULL_GRID_TILE_FBX_COOK\artifacts\tile_6_6\Ingolstadt_Tile_6_6.fbx | fbx | before | NO | NO | yes |
| C:\Users\admin\AppData\Local\Temp\opencode\geom_verify\fixed_10_9\Ingolstadt_Tile_10_9.fbx | fbx | after | yes | yes | yes |
| C:\Users\admin\AppData\Local\Temp\opencode\geom_verify\fixed_6_6\Ingolstadt_Tile_6_6.fbx | fbx | after | yes | yes | yes |

## FBX channel delta (before -> after the fix)

| layer node | before | after | delta |
| --- | --- | --- | --- |
| LayerElementNormal | 1132 | 1132 | +0 |
| LayerElementUV | 0 | 1132 | +1132 |
| LayerElementTangent | 0 | 0 | +0 |
| LayerElementBinormal | 0 | 0 | +0 |
| LayerElementSmoothing | 0 | 1132 | +1132 |
| LayerElementMaterial | 1132 | 1132 | +0 |


## Root-cause findings

### RC-UV-MISSING (root_cause)

No mesh carries a UV channel. Blender exported with use_tspace=False, so the FBX contains no explicit tangents and UE4/MikkTSpace must derive them from UVs. With zero parametric area on every face, every face has a degenerate tangent basis and a near-zero bi-normal.

Predicted UE4 warnings:

- `has degenerate tangent bases which will result in incorrect shading`
- `has some nearly zero bi-normals`

Evidence:

- OBJ: vt record count == 0
- FBX (before): LayerElementUV node count == 0
- blender_convert.py: use_tspace=False
- blender manifest (before): uv_layers == 0 on every object

Fix: generate a validated UV channel in the Blender conversion stage

### RC-SMOOTHING-MISSING (root_cause)

No FBX carries LayerElementSmoothing because Blender exported with mesh_smooth_type='OFF'. This is the direct cause of UE4's missing smoothing group warning and is fully independent of the UV problem.

Predicted UE4 warnings:

- `missing smoothing group information`

Evidence:

- OBJ: s record count == 0
- FBX: LayerElementSmoothing node count == 0
- blender_convert.py: mesh_smooth_type='OFF'

Fix: export with mesh_smooth_type='FACE' plus angle-based sharp edges

## Fix projection (dry run, no Blender)

What the planned per-object box projection would achieve on these exact
meshes. This is the numeric evidence that the UV fix works, produced
offline from the real OBJ.

| mesh | faces | degenerate UV faces before | after | min UV area after |
| --- | --- | --- | --- | --- |
| Ingolstadt_Tile_10_9.obj | 8443 | 8443 | 0 | 4.832e-08 |
| Ingolstadt_Tile_6_6.obj | 10265 | 10265 | 0 | 1.152e-07 |
