# Independent verification: O3 tile-frame-consistency report + 20260924T100614Z full-grid tile FBX cook

Date: 2026-09-29. Verifier: independent Claude subagent, no trust extended to the
committed O1-O20 work beyond what was independently re-derived below. Branch under
review: `o20-failure-recovery-resume-audit` @ `a189c1e6`. This file is pushed on
`docs/verify-o3-tile-frame-fullgrid-cook-20260929` (verification only, no merge).

## 1. O3's actual methodology (`4d51b357`, `tools/tile_frame_consistency.py`)

**Weaker than a real world-space numeric seam check**, despite superficially computing
a numeric "delta":

- It reads `exported_object_bounds` (min/max XYZ) straight out of each tile's
  `fbx_roundtrip_manifest.json` — i.e. the **raw, per-tile-local** bounding box that
  Blender reports after importing that tile's own FBX in isolation. It never applies
  any tile-placement transform (no `+ tx*tile_size_m`, no registry offset, nothing).
- `actual_exported_boundary_delta_m = abs(right.min[axis] - left.max[axis])` is
  therefore a delta between **two independently-centered local coordinate systems**,
  not a real-world seam gap/overlap. The tool's own `limitations` list actually admits
  this: "boundary delta is not a seam defect by itself" and "the visual layer is a
  centroid-partitioned building set, not a continuous surface."
- **Per-pair `status` is dead code.** `pair["status"]` is initialized to `"INCOMPLETE"`
  and never reassigned anywhere in `generate_report()`. All 31 `adjacent_pairs` in the
  committed `tile_frame_consistency.json` are literally `"INCOMPLETE"` — the report's
  top-level `"status": "PASS"` is driven only by tile-level manifest/SHA presence
  checks, never by any pass/fail judgement on the seam deltas themselves. The
  committed deltas range up to `max_seam_delta_m: 1085.43m` (mean `434.23m`) and this
  is *consistent with PASS* under O3's own schema — the number is descriptive noise,
  not a checked tolerance.
- Confirmed via the test file (`tests/unit/test_o3_tile_frame_consistency.py`): all 5
  tests only exercise frame-offset-string equality and SHA/manifest presence; none
  assert anything about the numeric seam-delta values.

**Verdict: O3 is the weaker methodology named in the task — closer to "confirms the
same CRS constant is referenced" than a real geometric seam check.** It does compute a
number, but that number is provably not gated on anything and mixes two different
coordinate frames.

## 2. Full-grid cook evidence (`reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK/`)

### 2a. Source SHA binding — independently CONFIRMED CURRENT

- Ran `verify_pinned_map('auto_map_of_record')` fresh (not from any committed report):
  resolves to `sha256_actual = 370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`,
  `verification_status: VERIFIED`.
- Recomputed sha256 of the actual 149,799,632-byte git-lfs object on disk myself
  (`sha256sum .git/lfs/objects/37/0a/370abbbbb...`): matches exactly.
- `COOK_RESULTS.json.source_provenance.map_of_record_sha256` = same hash. All 20
  per-tile `tile_fbx.json` manifests independently checked (B5 report + spot checks):
  same hash.
- **This is genuinely the current map-of-record**, not a stale pin (contrast with the
  *previous* `20260915T180446Z_FULL_GRID_TILE_FBX_COOK` evidence, which
  `LARGE_MAP_PACKAGE_CONTRACT_AUDIT.md` records as bound to a stale SHA `2ca342d8...`
  vs. the then-current `370abbbbb...`).

### 2b. Per-tile roundtrip status — genuinely 20/20 PASS, no glossed-over failures

- `COOK_RESULTS.json` top level: `tiles_attempted=20, tiles_ok=20, tiles_failed=0,
  tiles_empty=0, roundtrip_pass=20, roundtrip_fail=0, buildings_loaded=5711,
  buildings_placed=5711, buildings_unplaceable=0, anomalies=[]`.
- Checked `blender_status.json` for all 20 tiles individually: `status: "ok"` in every
  one, with plausible byte sizes/object counts (263-625 objects for the dense tiles,
  5-28 for the sparse edge tiles — consistent with an urban-core-to-outskirts
  gradient, not fabricated uniform data).
- `fbx_roundtrip_manifest.json` has no explicit `roundtrip_ok` flag; "pass" is
  presence + successful parse + populated per-object `bounds`/`vertices`/`faces`,
  which all 20 tiles have. No FAIL/partial tiles found anywhere in this evidence set.

### 2c. My own numeric seam check (real vertex coordinates, not the manifests' claims)

Parsed raw `.obj` vertex data directly (not the FBX/Blender bounds) plus the raw
per-tile `.osm` input XML for 4 tiles: `tile_7_8`, `tile_7_9`, `tile_8_8`, `tile_8_9`.

**Key finding #1 — OSM2World auto-centers every tile independently.** All 4 tiles'
raw OBJ x/z ranges are symmetric around (0,0) with magnitude ~400-560m, *regardless*
of the tile's true geographic position (confirmed distinct, non-overlapping real
lat/lon bboxes per tile from the `.osm` inputs, e.g. tile_7_8 lon
[11.4318,11.4470] vs tile_8_8 lon [11.4451,11.4595] — genuinely different geography).
`blender_convert.py` applies **zero** translation on OBJ->FBX (`global_scale=1.0`, no
transform ops). So raw per-tile coordinates are never placed in a shared frame
anywhere in the actual artifact chain — confirms/strengthens finding 2a's conclusion
about O3 independently.

**Key finding #2 — ground-truth-anchored seam check.** For each tile, I:
1. Parsed all named (`building=*` + `name=*`) OSM ways, computed each one's true
   lat/lon centroid.
2. Projected via the pipeline's own established native frame
   (`+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs`,
   i.e. `ultimate_pipeline/dem/dem_crs_contract.py::OSM2ODR_NATIVE_PROJ4`), then
   subtracted the registry's rebase offset (dx=832671.676, dy=5458671.104) to get a
   ground-truth local-frame position, independent of OSM2World.
3. Matched each named way to its mesh object in `fbx_roundtrip_manifest.json` by
   exact name (`Building <name>`), took the bbox centroid (discovered OSM2World's OBJ
   Z axis is south-positive, i.e. `world_northing = -mesh_z`; confirmed via two
   independent building-pair relative-distance checks, e.g. "Kavalier Dalwigk"<->
   "Flankenbatterie 92": true geodesic distance 251.64m vs raw-mesh distance 248.22m,
   1.4% agreement, only after applying the Z-flip).
4. Computed per-building `K = (true_position - mesh_centroid) - (tx,ty)*1000` — the
   residual offset needed on top of the naive nominal-grid placement
   (`tx*1000, ty*1000`, the *only* placement convention referenced anywhere in this
   pipeline, e.g. O3's own `expected_world_origin_m`).
5. Took the per-tile median K (n=12/14/5/6 named buildings respectively) and compared
   adjacent tiles' medians, with a standard-error estimate from the per-building
   spread.

| Pair | axis | ΔK (m) | standard error (m) | significance |
|---|---|---|---|---|
| tile_7_8 vs tile_8_8 | x (east-west border) | 46.1 | ~16.5 | ~2.8σ, modest |
| tile_8_8 vs tile_8_9 | y (north-south border) | **176.5** | ~13.9 | **~12.7σ** |
| tile_7_8 vs tile_7_9 | y (north-south border) | **270.1** | ~21.5 | **~12.6σ** |

**Real, independently-measured finding: both north-south adjacent pairs show a
statistically overwhelming (~170-270 m, >12 standard errors) inconsistency** in the
offset needed to place their OSM2World output at true geographic position, versus what
the pipeline's only documented tile-grid convention (`tx*1000, ty*1000`) would apply.
The east-west pair is comparatively closer to consistent (46m vs ~16m noise budget —
borderline, plausibly within my own centroid-vs-bbox measurement noise).

**Interpretation:** this is not proof of a bug in the cooked artifacts themselves
(each tile's own internal geometry is plausible and the roundtrip evidence is real) —
it demonstrates that **if these 20 tiles were ever assembled into a shared scene using
the only placement convention this codebase documents**, the north-south seams would
be visibly misaligned by ~200-270m (roughly the entire tile size), because OSM2World's
default per-file auto-centering does not coincide with the nominal tile-cell center,
and nothing downstream corrects for that. This is a *real*, previously-undetected,
numerically-demonstrated latent frame-consistency defect that O3's check (comparing
two already-uncorrected local frames to each other) could never have caught even in
principle, since O3 never introduces an independent ground-truth reference at all.

## 3. Does this supersede "no full-grid current-pin evidence exists"?

**Yes — this appears to be genuinely the first current-pin-bound full-grid cook
evidence**, and the prior finding needs updating, not deleting:

- `LARGE_MAP_PACKAGE_CONTRACT_AUDIT.md` (O2, same day) explicitly documents the
  *previous* full-grid cook (`20260915T180446Z_...`) as stale-SHA-bound
  (`2ca342d8...` vs then-current `370abbbbb...`).
- The `20260924T100614Z_...` run is independently confirmed (§2a) to be bound to the
  SHA that `verify_pinned_map('auto_map_of_record')` resolves to *right now*, live.
- Caveat worth flagging prominently: `scripts/cook_full_grid_tiles.py` **cannot be
  imported on the current branch HEAD** — reproduced independently:
  `ValueError: Registry entry 'auto_map_of_record' is missing structured frame fields
  'rebase_dx' / 'rebase_dy'`. Traced this to commit `f7934c13` ("O1: enforce
  current-pin cook provenance chain", 2026-09-24 13:14:49 +0200 = 11:14:49 UTC) which
  replaced a **hardcoded** `HEADER_OFFSET_XY = (832671.676, 5458671.104)` literal with
  a call to `_header_offset_from_registry(verify_pinned_map(...))` that needs fields
  `verify_pinned_map()`'s receipt-building code never actually populates (confirmed by
  reading `map_registry.py`'s return dict directly — a static, pre-existing gap, not a
  recent regression). The cook run itself is timestamped `20260924T100614Z` = 10:06
  UTC, **over an hour before** O1's commit — i.e. the cook genuinely ran against the
  pre-O1 script version (hardcoded offset, which correctly matched the registry's
  documented rebase values), so the cook evidence's validity is unaffected. But **as
  of right now, this branch cannot reproduce or extend this cook** — a live,
  independently-reproduced regression, ironically introduced by the very O1 task whose
  stated goal was hardening this exact script. Worth a follow-up fix (copy the
  structured frame fields from `norm` into `verify_pinned_map`'s returned receipt).

So: Phase 7's "no full-grid current-pin coverage exists" finding is **now outdated**
for the narrow claim "does current-pin-bound full-grid cook evidence exist" (yes, as
of 2026-09-24), but the pipeline is presently unable to regenerate it, and — per §2c —
the existing evidence has a real, newly-discovered latent seam-consistency gap that
was never checked by anything in the existing evidence trail.

## 4. OSM2World availability cross-check

**Genuinely available and genuinely used** — not a mock/stub:

- `OSM2World.jar` exists on local disk at
  `carla_governed/OSM2World-latest-bin/OSM2World.jar` (506,756 bytes, mtime
  2026-08-04, untracked by git — matches O1's commit-message note "untracked
  binary"). This predates the cook run by ~7 weeks.
- Per-tile `osm2world_status.json` (all 20 tiles checked) shows `status: "ok"`,
  real `java -jar .../OSM2World.jar convert -i ... -o ... --config ...` command
  lines, real `java_version: "openjdk version \"17.0.17\" 2025-10-21"`, `exit_code: 0`,
  plausible per-tile durations (7-8 sec, timestamped `2026-09-24T12:06:48` to
  `12:06:56`, consistent with the cook's overall `wall_elapsed_sec=448.55` for 20
  tiles), and sha256 hashes of input `.osm`/config/output `.obj`.
- Independently recomputed the sha256 of `tile_7_8`'s output `.obj` from the actual
  checked-out working-tree file: matches the manifest's claimed hash exactly (an
  initial apparent mismatch was a red herring from extracting the git blob via `git
  cat-file -p`, which bypasses the repo's `core.autocrlf=true` LF->CRLF smudge that
  the real working-tree file — and presumably the original run — went through;
  resolved by comparing on-disk-checked-out bytes, which match).
- The `.osm` input files contain thousands of real, distinct, geographically-coherent
  lat/lon building nodes per tile (not synthetic/duplicated placeholder data) — this
  is real OSM data genuinely run through a real OSM2World.jar invocation.
- This is consistent with, not contradictory to, the prior "OSM2World not installed"
  findings in memory (all dated 2026-07-31 through 2026-08-30, i.e. **before** this
  cook): those findings characterized OSM2World as "referenced-not-integrated" / "no
  real cook has run yet" even though (per the jar's Aug 4 mtime) the binary had
  already been placed on disk by early August — i.e. it sat unused for ~7 weeks until
  this 2026-09-24 run, which is plausibly the actual first genuine end-to-end
  exercise of it. This is a significant, surprising, but well-corroborated finding:
  **OSM2World was both available and genuinely, successfully used for this cook.**

## Bottom line

1. O3's methodology is the weaker kind named in the task brief — it never places
   tiles in a shared frame and its per-pair status field is dead code that can never
   fail.
2. The 20260924T100614Z full-grid cook is real, current-pin-bound, and 20/20
   genuinely passed its own (real) roundtrip checks — but my own independent,
   ground-truth-GPS-anchored seam reconstruction found a real, large (~170-270m,
   >12σ), previously-undetected north-south frame-consistency defect that neither O3
   nor any other evidence in this tree ever checked for, because nothing in the actual
   pipeline places tiles in a shared coordinate frame at all yet.
3. This does supersede "no full-grid current-pin evidence exists" as a factual
   coverage claim, but the branch currently cannot reproduce this cook (live,
   reproduced `cook_full_grid_tiles.py` import crash, introduced by O1 itself).
4. OSM2World availability and successful real use for this cook are both confirmed
   genuine, resolving/updating the older "not installed"/"not integrated" findings.
