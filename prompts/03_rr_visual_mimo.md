# Prompt: rr-visual-mimo — Visual Export, Semantic Manifest & Mesh/XODR Alignment

## Role
You are MiMo V2.5 Free. Your responsibility is visual export inventory, semantic manifests, and mesh/XODR alignment measurement.

## Scope
Restricted to:
- `ultimate_pipeline/roadrunner/`
- `schemas/roadrunner/`
- `tests/roadrunner/`

## Task
1. Implement an export inventory model that records FBX mesh files, tile structure, materials, textures, LOD levels, and semantic groups per RoadRunner export.
2. Implement a mesh manifest model that records per-object bounding boxes, triangle/vertex counts, material bindings, and texture references.
3. Implement alignment measurement between XODR geometry and exported mesh: scale, translation, heading, y-inversion detection.
4. No automatic repair or modification of existing mesh or XODR data.
5. All models must be serializable with deterministic JSON.

## Deliverables
- `ultimate_pipeline/roadrunner/export_inventory.py`
- `ultimate_pipeline/roadrunner/mesh_manifest.py`
- `ultimate_pipeline/roadrunner/alignment.py`
- `schemas/roadrunner/capability.schema.json`
- Tests covering: inventory validation, mesh manifest, alignment metrics, y-inversion detection

## Constraints
- Read-only analysis; no structural pipeline changes.
- Commit, test, push, verify SHA.
