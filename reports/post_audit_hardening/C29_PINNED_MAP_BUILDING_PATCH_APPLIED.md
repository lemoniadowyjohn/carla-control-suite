# C29 remediation option (b) applied — pinned map's buildings surgically corrected

User decision (2026-08-26): option (b), surgical patch — not (a) leave-as-is, not (c) full re-regen.

## What this does and does not touch
`scripts/patch_pinned_building_frame.py` shifts every building object's `cornerGlobal` x/y by
a single, deterministic `(dx, dy)` — computed by the already-existing, already-validated
`ultimate_pipeline.domain_gap.local_registration.building_frame_shift_to_auto_local` (previously
used only read-side, for cropping; this is the first place it's written back into a file).
**Nothing else changes**: roads, lanes, signals, elevation, header offset, geoReference are
byte-for-byte identical (verified below). The original pinned file is untouched on disk — this
produces a NEW file with a NEW sha256, exactly as the C29 spec required ("cannot silently
overwrite the pinned digest").

## Correction used
```
shift = building_frame_shift_to_auto_local(
    osm_lat_min=48.74935649548228, osm_lon_min=11.422268084715878,   # SETTINGS.load_gps_bounds()
    auto_proj4="+proj=tmerc +datum=WGS84 +units=m +no_defs",          # this file's own geoReference
    auto_offset=(832671.676, 5458671.104),                           # this file's own header <offset>
)
# dx=6547.354  dy=6368.796
```
This is the correction for a file whose buildings were written by the PRE-fix
`osm_polygon_loader.py` (wrong tmerc origin) and never rebased (C29 Bug 2) — different from, and
not to be confused with, `regen_map_of_record.py::_rebase_to_local`'s shift (which is for FRESH
regens where buildings are already correctly-projected pre-rebase; applying that shift here would
have been wrong).

Before writing anything, the shift + its effect were dry-run computed and cross-checked against
`C29_BUILDING_FRAME_FIX.md`'s independently-reported before/after numbers (7,665.0m / 1,558.8m
residual) — got 7,593.6m / 1,552.8m, a ~1% difference fully explained by a slightly different
centroid-averaging methodology (this check averages per-building centroids; the residual GPS
bounds and formula are otherwise identical). This match was the gate for proceeding to actually
patch the real file.

## Files
- **Input (untouched):**
  `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260819_160350.xodr`
  sha256 `69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e` (verified unchanged
  after the patch run — re-hashed post-patch, identical).
- **Output (new candidate, not yet promoted to map-of-record):**
  `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260819_160350_C29_BUILDING_PATCH.xodr`
  sha256 `744757f3f01da835269b5678eeb269cf5d534984213c551b9c475699aa73aec8`
  (git-ignored by the standing `campaigns/*/candidate/` rule, same as every other non-whitelisted
  candidate variant in that directory — not committed as part of this change; only the small
  script/test/report artifacts below are).

## Verification
1. **TDD**: `tests/unit/test_patch_pinned_building_frame.py`, 5 tests (shift applied correctly,
   z untouched, road geometry untouched, non-building objects untouched, zero-buildings no-op,
   and `compute_shift_for_pinned_map` cross-checked directly against
   `building_frame_shift_to_auto_local`). RED confirmed first (module didn't exist), then GREEN.
2. **Structural diff, real files, full parse**: road count 32,297=32,297, planView geometry
   attrs (s/x/y/hdg/length) 0 mismatches across all geometries, lane count 86,013=86,013, object
   count 51,797=51,797, signal count 21,171=21,171, header `<offset>` identical. `cornerGlobal`:
   all 35,703 points shifted by the exact same single `(dx, dy)` — not a per-point or partial
   change — and all `z` values identical.
3. **Acceptance gate** (`regen_map_of_record.py --verify-only` against the patched file):
   `valid_for_experiments=True`, all hard-fail gates pass, the same single pre-existing WARN as
   the original pin (33 isolated lane components, 0.41%, unrelated to buildings) — no new
   failures introduced.
4. **Building/road centroid offset on the actual written output** (not just the dry run):
   **7,593.6m → 1,552.8m**, matching the dry-run prediction exactly.
5. Full unit suite (`pytest -q`, respecting `pytest.ini`'s actual testpaths per the scope-gap fix
   earlier this session): confirmed green including the 5 new tests (see commit for exact count).

## What is committed vs. what is not
Committed: `scripts/patch_pinned_building_frame.py`, `tests/unit/test_patch_pinned_building_frame.py`,
this report. **Not committed**: the 144MB patched `.xodr` itself, or its `.patch_report.json`
sidecar — both are git-ignored by design (same rule that excludes every other non-map-of-record
candidate variant in that directory) and, per the original C29 spec, promoting a new file to the
map-of-record pointer is a separate, explicit decision, not automatic. The patched file exists on
disk at the path above, byte-for-byte reproducible from the committed script against the
untouched original pin.

## Next step, not taken here
If/when this patched candidate is to become the new map of record: LFS-track and commit the
`.xodr`, update the pin pointer (`C1_PIN_MAP_OF_RECORD_*.json`-style artifact) to the new
sha256 `744757f3...`, and re-run whatever downstream consumers reference the old pin by digest.
Not done in this pass — flagged, not silently assumed.
