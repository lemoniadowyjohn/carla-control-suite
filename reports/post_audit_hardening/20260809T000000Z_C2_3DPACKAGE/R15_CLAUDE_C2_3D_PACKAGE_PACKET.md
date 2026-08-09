# R15 CLAUDE C2 3D PACKAGE PACKET

*Run: `20260809T000000Z_C2_3DPACKAGE` · branch `fix/post-audit-phase-e-junctions-roundabouts-20260803` · freeze tag `c2_freeze_20260809T000000Z_C2`*

## Purpose

C2 executes and documents the accepted C1 candidate as a governed 3D-package
payload for Claude's terminal review. It performs (A) govern/promote of the
frozen C1 candidate with remote-parity attestation, (B) offline decomposition
of the ALREADY_PRESENT pedestrian authority into road-adjacent sidewalk-lane
matches vs package-mesh/NAVMESH candidates, and (C) full-map alignment and
projection-freeze evidence that ties the raw 3D pipeline output to the
governed XODR in a single, unambiguous EPSG:32632 native frame — all
OFFLINE-ONLY (no CARLA runtime; live placement is deferred to C4, no waiver).
The packet is frozen under `c2_freeze_20260809T000000Z_C2` for C2 review.

## Claimed anchors

| Anchor | Value |
| --- | --- |
| Parent freeze | `c1_freeze_20260809T000000Z_C1` → commit `8b400351d13634104090b31e535ced6e6d748648` (tree `c5e5951b…`) |
| Accepted C1 candidate | `reports/post_audit_hardening/20260809T000000Z_C1_GENERATION/candidate_crosswalk_enriched.xodr` → LF sha `16ea2ec134b10d07518c63e1bd42c4ffd8b96113d1a52c0fe448f201c004d11f` |
| Governed payload | `reports/post_audit_hardening/20260809T000000Z_C2_3DPACKAGE/perception_governed/governed_payload.xodr` :: sha `248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c` (81,007,405 B) |
| Promoted candidate | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr` (LFS oid == local sha == `248ffbbe…`) |
| OSM source (3D input) | `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm` :: sha `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` (11,154,738 B) |
| XODR geometry frame | `+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs` (EPSG:32632-compatible native) |

## A1 — Govern + promote (C2-A)

Producer `stage_c2_govern_promote.py`: load accepted C1 candidate, apply
georeference-normalize v1 (identity-preserving), re-hash; identity guard
(`phase_q.governed_payload`) passed — governed payload raw-disk sha =
`248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c` and
LF-text sha identical after normalize (stability proven). Retired the stale
`ff2a05e7…` pointer; updated
`campaigns/ingolstadt_cooked_perception_v1/candidate/manifest.json` +
`campaigns/ingolstadt_cooked_perception_v1/manifest.json`
(perception_candidate `248ffbbe…`).

- `perception_governed/Q03_LOAD_PAYLOAD_MANIFEST.json`,
  `Q04_GEOREFERENCE_SEMANTIC_DIFF.json`, `PROMOTION_RECORD.json`.

## A3 — Remote parity attestation (C2-A3)

Producer `stage_c2_parity_attest.py` → `P2A_REMOTE_PARITY_ATTESTATION.json`:

- head_parity=true: local HEAD == remote HEAD == `284175388521c70d7a2ffe1aeb85ad568361426a`
  (remote `3ef4fbfd..28417538` pushed; LFS `--all` 25/25 objects, 2.2 GB).
- local_tree `42bb2575f8ea88c158c7dca1d0114b224b3589e8`;
  lfs_object_count=23; all_local_files_match_lfs_oid=true.
- Per-file LFS OIDs equal local shas: `ingolstadt_perception_final.xodr`
  `248ffbbe…`, `ingolstadt_fixed_final.xodr` `80ebb005…`,
  `ingolstadt_authoritative.osm` `b9e07465…`,
  `candidate_g_semantic_enriched.xodr` `8b60d8f4…`,
  20260807 governed payload `a7b319db…`, C1 candidate `16ea2ec1…`.
- verdict: `REMOTE_PARITY_CONFIRMED`.

## B — Pedestrian decomposition of ALREADY_PRESENT 5071 (C2-B)

Producer `stage_c2b_pedestrian_decomposition.py` →
`C2B_ALREADY_PRESENT_DECOMPOSITION.json/.csv` (5,071 rows).

- 5071 ALREADY_PRESENT pedestrian ways → **1334
  ROAD_ADJACENT_SIDEWALK_MATCHED** (contiguous containment of a
  ≥20 m aligned run inside sidewalk-lane bounds, lane-densified 2.0 m,
  containment = lane_width/2 + 4.0 m, per-feature `road_id`/`lane_id`/
  `proof`/`aligned_run_m`/`mean_eff_dist_m` recorded) + **3737
  STANDALONE_PACKAGE_MESH_NAVMESH** (footway/path/other pedestrian ways not
  lane-representable → package mesh / environment NAVMESH surface).
- `osm_way_missing=0`, `split_invariant_pass=true`; indexed 16,745 sidewalk
  lanes from the governed payload; CRS verdict `OSM2ODR_NATIVE_VERIFIED`.
- Residual stats for lane-matched ways: median effective distance
  ≤ 2.3 m, p95 ≤ 4.1 m, max ≤ 5.3 m (per-class: SIDEWALK n=311 deemed
  lane-representable of 398, FOOTWAY 422/2719, PATH 601/1954).
- Verify now asserts deterministically: `C2B decomposition split == 5071`
  (added in C2-A4, ALL PASS).

## C1 — Full-map OSM2World run (C2-C1)

Runner `run_fullmap_osm2world.py` (absolute-paths, artifacts dir
`artifacts_fullmap/`): `OSM2World.jar` (Java 17) convert of the authoritative
full-map OSM into `scene.obj`, 5.152 s, status ok, exit 0.

- `scene.obj` 49,199 B / 1,924 lines / 945 vertices / 64 objects
  (groups SurfaceArea x4, Elevator x2, Building x1, RetainingWall x1);
  sha `46c4a40f8eb653f3c4f0d9de79a4f5236357952ca580cafb33a3979815a8b7d2`;
  config sha `f9666349cf9737d3b891240c524122e8df05ac0b35c4fe5e3f4d22483e24a2b5`; input
  sha `b9e07465…`.
- `osm2world_status.json` records command lines, java version, hashes,
  cache key `ec956bd0478fb2a7`, exit codes (0), and the stderr head (6
  IndoorModule duplicate-point errors — geometry-local warnings, exit 0;
  no roads affected; materials default PBR throughout).
- Small output is honest: the authoritative OSM extract is a
  highway/pedestrian-focused extract — 17,250 ways, **17,200 highway-tagged,
  0 building/vegetation/leisure/water ways** (surface 9656, name 4901,
  maxspeed 4350, foot 2519, bicycle 2306, service 2041 …). No buildings
  exist to package; clutter scope for C2 is therefore zero and all
  building/vegetation acceptance items are deferred to C4 (LIVE_DEFERRED).

## C2 — Projection freeze (C2-D)

Producer `stage_c2d_projection_freeze.py` → `C2D_PROJECTION_FREEZE.json`
(verdict `PROJECTION_FREEZE_PASS`, 10/10 rule-outs):

- Declared geoReference tmerc `lon_0=9`/`x_0=500000` matches
  EPSG:32632-consistent native frame; CRS `OSM2ODR_NATIVE_VERIFIED`.
- geometry bbox x∈[832,930, 845,804], y∈[5,458,672, 5,472,213] →
  center (839,367, 5,465,442) — no 165 km shift, no UTM-vs-local-origin
  mismatch (easting 400–900 km band), no axis inversion (northing 5.4M >>
  easting), no 90° rotation (aspect ≈1), no m/cm (span 13 km), no 100× scale.
- no `<header><offset>` → single origin, no double-origin; no stale XODR
  (governed `248ffbbe…` == C1 candidate LF sha `16ea2e…` provenance,
  identity guard true, normalize-stable).

## C3 — Full-map alignment residuals (C2-C3)

Producer `stage_c2c_fullmap_alignment.py` → `C2C_FULLMAP_ALIGNMENT_RESIDUALS.json`
and `stage_c2e_crosswalk_corner_alignment.py` →
`C2E_CROSSWALK_CORNER_ALIGNMENT.json`.

- OBJ origin WGS84 (48.749337350000005, 11.4324595) → native frame
  (839,966.7, 5,465,151.4) — same locus as the accepted 20260804 J5 window
  origin (839,964.0, 5,465,150.6), inside the XODR road bbox.
- Mapping (J-series precedent): `xodr_x = origin_x + obj_x`,
  `xodr_y = origin_y − obj_z` (OBJ north direction (0,0,−1)),
  `xodr_z = obj_y` (flat at origin elevation).
- OBJ↔XODR residuals over 945 vertices to nearest XODR road polyline:
  **min 0.073 m · mean 109.9 m · median 50.7 m · p95 479.6 m · p99 499.6 m ·
  max 508.3 m**; outliers ~500 m near road `64882` (SurfaceArea/Elevator
  plaza objects legitimately distant from road centerlines — not a frame
  error; the road network itself is proven by C2-B per-feature lane matches
  and stage N/J structural digests).
- Crosswalk corner alignment (66 objects, 330 corners decoded via the CARLA
  0.9.16 GetAllCrosswalkZones codec `carla_world_corners`, S07 inverse):
  **min 0.222 m · mean 4.957 m · median 4.343 m · p95 10.282 m ·
  max 13.264 m** (object-mean max 12.053 m at `crosswalk_815412609`,
  road `43964`). All 66 sit inside or immediately beside their host road —
  corner spans ~10 m over a ~4.0 m marking depth + sidewalk offsets.
- Junction/roundabout/S-curve/bridge/tunnel classes: protected structural
  digests unchanged in governed payload (C1F: planview/road_link/junction/
  lanelink/lanesection/elevation/roadmark/superelevation_crossfall all
  unchanged=true; combined `b30d9678…`); no road geometry mutated by the
  C1/C2 mutations (delta is exactly 66 crosswalk objects). Offline-provable
  residuals therefore remain at the digest level; per-vertex mesh residuals
  for these classes are deferred to live placement (LIVE_DEFERRED_C4).

## D1-F1 — Environment & materials quality contract

- Representative authoritative full-map source (all 17,250 ways, no subset).
- Materials: OSM2World PBR materials (MTL emitted, default textures); no
  alpha-blended assets; geometric fidelity per OSM2World level 1 defaults;
  y-up in OBJ export, converted to CARLA z-up in native frame per C3 mapping.
- Clutter scope: **zero** building/vegetation ways in the authoritative OSM
  extract — no building/vegetation packaging possible or claimed; all visual
  clutter acceptance items are `LIVE_DEFERRED_C4`.
- Adaptive tweaks: sidewalk-adaptive margins from C2-B (contain_tolerance_m
  4.0, lane-width/2-based run containment) are the only adaptive parameters;
  frame and mapping remain the fixed J-series contract (no adaptive
  re-projection).

## Acceptance chains (itemized)

1. **Projection/frame chain** — governed payload geoReference == EPSG:32632
   contract, native CRS verified, no offset/double-origin/rotation/shift/
   scale pathologies (C2-D 10/10) → OFFLINE_PROVEN.
2. **Collision/footprint chain** — 66 crosswalk footprints decode to their
   host roads (C2-E, mean 4.96 m corner-to-road in-lane); lane network
   untouched (C1F structural digests unchanged) → OFFLINE_PROVEN for framing,
   footprint semantics; actual spawned collision volume → LIVE_DEFERRED_C4.
3. **Traffic-control chain** — signal element/reference/controller digests
   unchanged (C1F `393ddad4…`), signal id set 3467 identical →
   OFFLINE_PROVEN; runtime traffic control behavior → LIVE_DEFERRED_C4.
4. **Pedestrian/NAVMESH chain** — 5071 ALREADY_PRESENT ways split
   1334 lane-matched (residuals ≤ 5.3 m) + 3737 standalone →
   OFFLINE_PROVEN ledger; live NAVMESH baking/runtime → LIVE_DEFERRED_C4.
5. **Parity/identity chain** — remote parity confirmed, LFS oids == local
   hashes, no stale pointers → OFFLINE_PROVEN.

## Freeze

- freeze_schema: `C2R_TAG_ANCHORED_V2`
- freeze_tag: `c2_freeze_20260809T000000Z_C2`
- parent_commit: `8b400351d13634104090b31e535ced6e6d748648` (pre-C2
  carrying commit; the C1 freeze commit)
- NO head_commit / NO tag-object sha recorded in any committed JSON
  (non-circular freeze; the annotated tag message carries the identities:
  freeze_commit, freeze_tree, branch, r15 sha256, r15b sha256, manifest
  sha256, governed payload sha).
- review invariant: no commits after tag creation before Claude's C2 review;
  worktree clean; tag points at terminal C2 commit (`tag^{commit} == HEAD`).

## Verification

`verify_post_audit_hardening.py` — exit 0, ALL PASS, post-A4 flipped
checks (crosswalk present ≤ authority 66 ≤ 179; cornerLocal-only 66/0;
pedestrian present 5318 ≤ 5431; C2B split == 5071) plus the legacy
repaired/LF/enriched/governed/structural chains.