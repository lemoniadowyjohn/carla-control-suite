# C29 (HIGH — map-correctness) — building `cornerGlobal` frame mismatch, root cause (2 files)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803` · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1
Rules: TDD (RED→GREEN); full-suite green; **EXPLICIT-PATHSPEC commit**; this touches the canonical regen path
(`scripts/regen_map_of_record.py`) — **map/result-touching, human review before any re-pin.**
**Model: your call (Codex xhigh for the mechanical geodetic-math parts, Claude for the two-file coordination
and the pinned-map remediation decision).**

## Severity (quantified 2026-08-26, verified directly against the real pinned map `69b1f520`)
```
road local-frame centroid:     (7204.6, 6802.0)   bbox x[0, 13267.1] y[-0.0, 14070.9]
building cornerGlobal centroid: (1545.1, 1632.7)   from 35,703 corner points
OFFSET (building - road centroid): (-5659.5, -5169.3)  magnitude = 7,665 m
```
On a map whose road network spans only ~13×14 km, the buildings' `cornerGlobal` centroid sits **7.665 km** from
the road centroid — buildings cluster almost entirely **outside** the road network's own bounding box. This is
not a cosmetic measurement artifact: `BuildingExtruder`'s own docstring
(`ultimate_pipeline/enrichment/building_extruder.py:31-34`) states *"absolute cornerGlobal coordinates are used
so CARLA can place the mesh regardless of the chosen road's local (s,t) frame"* — i.e. `cornerGlobal` is designed
to be read as an absolute map-frame position by any OpenDRIVE/CARLA consumer, including CARLA's own standalone
`generate_opendrive_world` building-block renderer (the near-term RQ2 Path-A plan, C17). **If uncorrected, the
5,686 buildings on the pinned map render ~7.7 km from the roads they're supposed to sit beside.**

## Root cause — TWO independent bugs, both required for a correct fix

**Bug 1 — wrong projection origin (`ultimate_pipeline/enrichment/osm_polygon_loader.py:35-38`):**
```python
PROJ_STRING = (
    f"+proj=tmerc +lat_0={_lat0} +lon_0={_lon0} "   # _lat0/_lon0 = GPS bbox lat_min/lon_min
    "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
)
```
Buildings are projected with tmerc origin at the **configured GPS bbox corner**. The road network (Osm2Odr
output) instead uses a **bare** `+proj=tmerc` (implicit `lat_0=0 lon_0=0` — the equator/prime-meridian global
origin), confirmed in `ultimate_pipeline/domain_gap/local_registration.py`'s `BARE_TMERC_DEFAULT` +
`read_georef_proj4`. Two different tmerc origins → two unrelated small-number coordinate spaces that only
coincidentally both look "local-sized."

**Bug 2 — rebase never touches buildings (`scripts/regen_map_of_record.py::_rebase_to_local`, ~line 142):**
```python
for g in root.findall(".//planView/geometry"):
    xs.append(float(g.get("x", "0"))); ys.append(float(g.get("y", "0")))
...
for g in root.findall(".//planView/geometry"):
    g.set("x", f"{float(g.get('x', '0')) - dx:.6f}")
    g.set("y", f"{float(g.get('y', '0')) - dy:.6f}")
```
`_rebase_to_local` computes `dx, dy` from road `planView/geometry` bounds and shifts **only** those elements
into the local frame (recording the offset in the header). It never touches `.//object/outline/cornerGlobal`.
Even if Bug 1 were the only issue, post-rebase roads would still drift away from un-rebased buildings.

**Why the current offset is ~7.7 km and not the road network's ~832k/5458k global magnitude:** Bug 1's GPS-bbox
origin happens to already produce small ("local-looking") numbers, so the two bugs partially mask each other in
magnitude — this is NOT evidence the problem is minor; it's evidence the two independently-wrong frames happen to
both be small numbers that don't happen to coincide.

## Task — fix both, TDD, in this order
1. **`osm_polygon_loader.py`:** change buildings' `PROJ_STRING` to the **same bare tmerc** frame roads use
   (`+proj=tmerc +datum=WGS84 +units=m +no_defs`, no `lat_0`/`lon_0` — matching
   `local_registration.BARE_TMERC_DEFAULT`), so raw projected building coordinates land in the same **global**
   frame as pre-rebase road geometry. TDD: project a known lon/lat through both the old and new PROJ_STRING and
   assert the new one matches `local_registration.read_georef_proj4`'s bare-tmerc expansion.
2. **`regen_map_of_record.py::_rebase_to_local`:** extend the shift to also apply to
   `.//object/outline/cornerGlobal` (`x`/`y`, not `z`) using the **same** `dx, dy` computed from road geometry.
   TDD: a synthetic XODR with both `planView/geometry` and a `cornerGlobal`-bearing building object — assert
   both get shifted by the identical `(dx, dy)` and the rebase report still validates.
3. **End-to-end verification (offline, no live regen required for this check):** using the ALREADY-PRODUCED
   pipeline output from the most recent regen run under `campaigns/.../regen/*/pipeline_out/` (find the pre-rebase
   final XODR — do not re-run the full pipeline), manually apply the fixed rebase logic and confirm the
   building/road centroid offset drops from **7,665 m to a small residual** (expect not-exactly-zero — buildings
   are spread across the map, not co-located with the road centroid — but the magnitude should collapse from
   km-scale to a footprint-sized residual, sanity-checked against `local_registration.py`'s own
   `building_frame_shift_to_auto_local` correction value on the SAME data as a cross-check).
4. **Do NOT re-pin or modify `69b1f520` in this task.** The already-pinned map keeps its known, now-documented
   defect (buildings ~7.7 km mislocated) until a human decides the remediation path (options below) — this task
   only fixes the **canonical regen path** so *future* regens are correct.

## Remediation options for the ALREADY-PINNED `69b1f520` (do not decide unilaterally — present to the user)
- **(a) Leave as-is, documented.** Cheapest; the map remains usable for RQ1 (roads-only) and the already-built
  local-registration crop (which already works around this via `building_frame_shift_to_auto_local`). RQ2 Path-A
  (CARLA standalone building rendering) would still show mislocated buildings if run against this exact pin.
- **(b) Surgical patch.** Re-write `69b1f520`'s existing `cornerGlobal` x/y in place using the known correction
  shift (`building_frame_shift_to_auto_local`'s inverse), producing a NEW sha (cannot silently overwrite the
  pinned digest) — small, fast, but is itself a "patch not a regen," needs explicit review since it changes a
  pinned artifact's bytes outside the canonical regen path.
- **(c) Full re-regen.** Cleanest (goes through the now-fixed canonical path), but Osm2Odr is byte-non-
  deterministic (C15) and a live-CARLA drivability re-check would ideally follow — costs a regen cycle.
Flag this decision explicitly in the report; do not pick one silently.

## Boundaries
- Do not touch `carla_utils.py` or anything in the currently-active C21/C27 territory
  (`domain_gap_gnn/`, `perception/*.py`).
- `local_registration.py`'s existing `building_frame_shift_to_auto_local` workaround should be **left in place**
  even after this fix — it correctly compensates for the CURRENT pinned map's frame mismatch, and older/other
  pinned maps may still carry the same historical bug.

## Deliverables / verdict
- `osm_polygon_loader.py` + `regen_map_of_record.py` fixed (TDD, both GREEN).
- `reports/post_audit_hardening/C29_BUILDING_FRAME_FIX.md`: before/after offset numbers, the end-to-end
  verification result, and the three remediation options presented (not decided) for `69b1f520`.
- Full suite green; push (explicit pathspec); local==remote.
- **Verdict:** `BUILDING_FRAME_FIXED canonical_path=<fixed> offset_before_m=7665 offset_after_m=<x> pinned_map_remediation=<DEFERRED_TO_USER>` | PARTIAL | BLOCKED.
