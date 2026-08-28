# C16 (HIGH) — Cook both maps to CARLA (UE4.26) — perception prerequisite  *(UE-operator-gated)*

Repo/branch/interp as C13. Plan: Phase R4. **Blocked on a human UE4.26 operator** (not available 2026-08-19);
code + dry-run are deliverable now, execution deferred.

## Why
Perception RQ2/RQ3 *authoritative* (`PAIRED_INGOLSTADT`) results require BOTH maps rendered as rich cooked 3D CARLA
maps with correct semantics — not OpenDRIVE-standalone (which the interim path A uses). The manual Grid0828 is
already a cooked UE map; the AUTO map must be cooked to match.

## Steps
1. **Scaffold (code, now):** parameterize the OSM2World→Blender→FBX→UE4.26 cook of the pinned auto map
   (`enrichment/osm2world_runner.py`, `enrichment/fbx_roundtrip.py`; branch `integration/unreal-fixture-cooking`):
   FBX import → XODR associate → **semantic tag per mesh** (CityObjectLabel: road/building/vegetation/pole/
   traffic-sign/traffic-light/sidewalk…) → collision → package. Dry-run validate (no UE).
2. **Semantic-tag correctness test (offline):** assert every mesh class maps to a valid CityObjectLabel and the
   mapping matches `perception/semantic_classes.py` (0..28). A mesh with no/`Any` tag must fail the gate.
3. **Execution (operator):** run the cook on a UE4.26 workstation → packaged CARLA map. Spot-check with a semantic
   camera that building/road/vegetation/pole pixels carry the right class ids (reuse the C8 raw-id reader).
4. Register the cooked auto map in the C13 registry (role=auto_cooked, sha256 of the package manifest).

## Boundaries / verdict
- Code parameterized + dry-run validated now; **do not fake a cook**. `PAIRED_INGOLSTADT` stays deferred until the
  operator runs it. Verdict: `COOK_SCAFFOLD_READY dry_run=OK` (now) → `COOKED_BOTH_MAPS semantic_tags=OK` (operator).
