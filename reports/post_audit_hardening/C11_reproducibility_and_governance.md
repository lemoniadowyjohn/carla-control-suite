# CODEX C11 (HIGH) — Reproducibility & governance (pin all inputs + one canonical regen command)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1
Rules: TDD; full-suite green; **EXPLICIT-PATHSPEC commit**. Model: Codex 5.x high.
**Sequencing:** land the canonical-entrypoint part AFTER C6/C7/C8/C9 so it encodes the corrected pipeline. The input-pinning + preanchor + decouple parts can start now.
**PHASE-0 dependency (reconcile first):** an uncommitted `sumo_repair.py --offset.disable-normalization` change (Claude, GLOBAL coords) overlaps the committed `1be9b767` (honor-header-offset, LOCAL coords). Per user decision they are HELD for **you (Codex) to reconcile**: pick ONE CRS approach (recommended: keep `1be9b767` local+offset; drop the SUMO flag + `tests/unit/test_sumo_repair_frame_preservation.py`), because the canonical regen entrypoint must encode a single, consistent coordinate frame. Do this before writing the entrypoint.

## Problem — the pinned map is NOT reproducible from a governed command
The C0 map-of-record required hand-assembled driver scripts + a non-default env + an uncommitted code fix, and not all inputs are pinned. A defensible thesis needs: every input digest-pinned, and ONE committed command that reproduces the map deterministically.

Confirmed gaps:
1. **Default pipeline run crashes**: `settings.PREANCHOR_INPUT_XODR` defaults `True` and imports `tools.preanchor_xodr`, which is **absent from the repo** → a clean-checkout default run dies before stage 01.
2. **Inputs not all pinned**: the road OSM is pinned (`b9e07465`), but the **DEM** (`cities/ingolstadt/dem/dem_ing.tif`) and the **building source** are not digest-pinned. A live-fetch (buildings.geojson) is in the generation path.
3. **Generation coupled to the manual map**: `THESIS_STRICT` stage-02 `_write_crs_comparability` fails closed unless a manual reference XODR is present → Phase-1 auto-map GENERATION requires the Phase-2 comparison input.
4. **No canonical entrypoint**: the exact config (env toggles + the CRS/lane fixes) lives only in scratch scripts + this report set.
5. **Environment**: pyproj `proj.db` is `VERSION.MINOR=4` (expected ≥6, "from another PROJ installation") — a latent silent-reprojection risk.

## Steps (TDD)
1. **Fix the preanchor default** (choose + document one):
   - (a) restore `tools/preanchor_xodr.py` (if it existed and is wanted), OR
   - (b) set `PREANCHOR_INPUT_XODR` default **False** (preanchoring re-frames off the Osm2Odr tmerc(0,0) frame the DEM contract needs, and no working run used it).
   Test: default settings + a seed XODR → pipeline reaches stage 01 without ImportError. Recommended: (b).
2. **Pin all generation inputs by digest** under `campaigns/ingolstadt_cooked_perception_v1/source/`:
   - roads OSM (already `b9e07465`), **DEM** `dem_ing.tif`, **building source** (from C7). Write `source/INPUTS_MANIFEST.json` (path + sha256 + bytes for each). A build-time **fail-closed** guard: if any input's sha256 ≠ manifest, ABORT. Test on a tiny manifest fixture.
3. **Decouple generation from the manual map**: in `_write_crs_comparability`, when `THESIS_STRICT` and no manual map is present, write a `crs_comparability.json` with `status="manual_deferred"` instead of raising — gate the hard-fail behind a separate `REQUIRE_MANUAL_FOR_CRS` flag (default False for generation). Test: strict + no manual → produces deferred record, does NOT raise; strict + `REQUIRE_MANUAL_FOR_CRS=1` + no manual → raises.
4. **Canonical committed regen entrypoint** (`scripts/regen_map_of_record.py` or a `run_pipeline` profile) that: verifies the INPUTS_MANIFEST digests; sets the corrected config (post C6–C10) explicitly; runs OSM→Osm2Odr seed→pipeline→acceptance; writes the provenance chain (osm→seed→candidate sha) + settings snapshot; refuses to emit a candidate unless `map_acceptance.py` passes. No hand-editing required. Document the exact one-line invocation.
5. **PROJ env guard**: add a startup check that fails-closed (or loudly warns with remediation) if `proj.db` is too old for the CRS transforms used; document the fix (align pyproj/GDAL proj data). Operator step for the actual env repair.

## Boundaries
- Deterministic; the network fetch of DEM/buildings is a documented operator step that PRODUCES pinned artifacts (not run at map-build time).
- Do NOT re-open C6–C10 concerns; consume their corrected code.

## Deliverables / verdict
- `campaigns/.../source/INPUTS_MANIFEST.json` + digest guard + tests.
- preanchor default fix + decoupled CRS gate + tests.
- `scripts/regen_map_of_record.py` (committed) + `reports/post_audit_hardening/C11_REPRODUCIBILITY.md` documenting the single reproduce command + PROJ remediation.
- Push (explicit pathspec); local==remote; full suite green.
- **Verdict:** `REPRODUCIBLE inputs_pinned=OK default_run=OK canonical_cmd=<path>` | PARTIAL | BLOCKED.
