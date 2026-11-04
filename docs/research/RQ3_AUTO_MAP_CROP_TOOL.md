# RQ3 Auto-Map Footprint Crop Tool

Usage notes for `tools/rq3_crop_auto_to_manual_footprint.py` and the module it
wraps, `ultimate_pipeline/domain_gap/footprint_crop.py`. Read-only with
respect to the map-of-record and Grid0828: this tool only ever writes a new,
derived file to a scratch output directory.

---

## 1. Purpose

RQ3's paired-capture protocol needs a same-place auto-map counterpart to the
manual reference map (Grid0828/Grid0821) so the two can be driven over
identical ground. This tool produces that counterpart by deriving a **pure
subset** of the auto map-of-record: it crops the full auto map down to the
footprint Grid0828 actually covers, so the auto and manual maps describe the
same patch of ground at the same scale.

It creates and modifies no geometry. Every `<road>`/`<junction>` element that
survives the crop is an unmodified clone of the corresponding element in the
source map-of-record file; the only mutations performed are **removals** of
links that the subset itself would otherwise leave dangling
(`ultimate_pipeline/domain_gap/footprint_crop.py:1-11`). This keeps the
operation inside the AGENTS.md boundary that generator fixes happen at source
stage only and that there is no final-XODR cosmetic mutation — the crop is
neither a generator fix nor a cosmetic edit, it is a derived, self-consistent
subset of an already-frozen map-of-record.

---

## 2. Inputs

Both inputs are resolved exclusively through the pinned map registry,
`ultimate_pipeline.carla_tools.map_registry.verify_pinned_map`
(`tools/rq3_crop_auto_to_manual_footprint.py:105-107`, calling
`ultimate_pipeline/carla_tools/map_registry.py:935`). There is no glob or
mtime-based path discovery anywhere in this tool.

- `auto_map_of_record` — the map-of-record pin
  (`ultimate_pipeline/carla_tools/map_registry.py:703-765`), currently
  `sha256=370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`,
  `bytes=149799632`, path
  `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr`.
- `manual_grid0828` — the manual reference map
  (`ultimate_pipeline/carla_tools/map_registry.py:911-926`), currently
  `sha256=5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`,
  `bytes=66530869`, path
  `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr`.
  The registry entry documents `equivalent_names: ["Grid0821", "Grid0828"]`
  as an explicit, non-inferred alias — both names resolve to the one pinned
  file.

`verify_pinned_map` is fail-closed
(`ultimate_pipeline/carla_tools/map_registry.py:942-947`): it raises
`LookupError` for an unregistered name, and `MapRegistryDriftError` for a
missing file, an un-smudged git-LFS pointer, a byte-size mismatch, or a
sha256 mismatch against the pin. The CLI catches exactly these two exception
types and fails closed before any crop logic runs
(`tools/rq3_crop_auto_to_manual_footprint.py:138-142`):

```
FAIL-CLOSED (registry verification): <exception message>
```
(exit code `3`).

---

## 3. CLI

Entry point: `tools/rq3_crop_auto_to_manual_footprint.py:110-123`
(`argparse.ArgumentParser`). Every flag below is copied verbatim from the
argparse block; nothing here is inferred or invented.

| Flag | Required | Default | Notes |
|---|---|---|---|
| `--repo-root` | yes | — | `type=Path`. Repo root to resolve registry-relative map paths against; read-only, may be a different worktree than the tool's own. |
| `--out-dir` | yes | — | `type=Path`. Output directory; must not be inside `<repo-root>/campaigns` or collide with any registry-pinned path. |
| `--buffer-m` | no | `0.0` | `type=float`. Forwarded to `crop_auto_to_manual_footprint`'s `buffer_m`. |
| `--selection` | no | `"any_point"` | `choices=SELECTION_MODES` (`("any_point", "centroid")`, `ultimate_pipeline/domain_gap/footprint_crop.py:153`). |
| `--sample-spacing-m` | no | `DEFAULT_SAMPLE_SPACING_M` (`2.0`, `ultimate_pipeline/domain_gap/footprint_crop.py:154`) | `type=float`. |
| `--overwrite-scratch` | no | `False` | `action="store_true"`. Allows reusing a non-empty `--out-dir`. |

### Safety refusals

`_assert_safe_out_dir` (`tools/rq3_crop_auto_to_manual_footprint.py:81-102`)
runs before any directory is created or any map is read, and raises
`OutDirUnsafeError` — caught in `main()` and printed to stderr with exit code
`2` (`tools/rq3_crop_auto_to_manual_footprint.py:128-132`):

- Out-dir equal to, or nested under, `<repo-root>/campaigns`:

  ```
  REFUSED: --out-dir <resolved> is inside the registry's campaigns/ directory (<campaigns_dir>); refusing to write a derived crop there.
  ```

- Out-dir equal to, a parent of, or the direct parent of any path named in a
  `PINNED_MAP_REGISTRY` entry (`tools/rq3_crop_auto_to_manual_footprint.py:68-78,89-94`):

  ```
  REFUSED: --out-dir <resolved> collides with a registry-pinned map path (<pinned>); refusing to write there.
  ```

- Out-dir already exists and is non-empty, without `--overwrite-scratch`
  (`tools/rq3_crop_auto_to_manual_footprint.py:96-102`):

  ```
  REFUSED: --out-dir <resolved> already exists and is non-empty (<N> entries); pass --overwrite-scratch to reuse it.
  ```

This out-dir guard is independent of, and runs in addition to, the
registry's own read-side fail-closed checks on the two input maps
(`tools/rq3_crop_auto_to_manual_footprint.py:14-16`).

---

## 4. Selection rules

Implemented in `ultimate_pipeline/domain_gap/footprint_crop.py`, rules (a)
and (b) of the module docstring (lines 1-131).

**Footprint polygon (rule a, lines 18-32):** the convex hull of the manual
map's `planView` geometry points
(`local_registration.manual_geometry_convex_hull`), transformed into the
auto map's local frame
(`local_registration.transform_manual_points_to_auto_local`), then
optionally dilated by `buffer_m` via shapely `Polygon.buffer`. `buffer_m`
must be finite and `>= 0`
(`ultimate_pipeline/domain_gap/footprint_crop.py:168-169`); a negative value
raises `ValueError` rather than eroding the footprint. "Inside" is tested
throughout with shapely's `contains`/`prepared.contains`, which is
**boundary-exclusive** — a point lying exactly on the hull (or
buffered-hull) boundary does not by itself keep a road. With `buffer_m > 0`
this moves the boundary off the hull's own vertices, making an exact-touch
case practically impossible.

**Road selection (rule b, lines 34-56):** applies only to non-junction roads
(`road[@junction='-1']`); junction-member roads are governed entirely by
junction closure (rule c), never by this per-road test
(`ultimate_pipeline/domain_gap/footprint_crop.py:245-246`).

- `any_point` (default, `select_non_junction_roads` ->
  `_road_matches_any_point`,
  `ultimate_pipeline/domain_gap/footprint_crop.py:201-228`): a road is kept
  iff any point sampled along any of its `planView/geometry` primitives
  (sampled through `opendrive_geometry_kernel.sample`, which is
  paramPoly3/spiral-aware) lies inside the footprint polygon. A cheap, exact
  (non-heuristic) pre-filter skips the per-geometry sampling when the
  primitive's stored `(x, y)` anchor is farther from the polygon's bounding
  box than the primitive's own `length`, since arc length upper-bounds
  displacement from the start point for every supported primitive kind
  (`ultimate_pipeline/domain_gap/footprint_crop.py:186-190,213-216`). If
  `kernel_sample` raises on an unsupported/malformed primitive, the code
  falls back to the one point it does have — the stored anchor — rather than
  silently dropping coverage (`ultimate_pipeline/domain_gap/footprint_crop.py:220-224`,
  counted as `sampling_fallback_count`).
- `centroid` (legacy/cheaper, matching `local_registration.road_centroid`,
  `ultimate_pipeline/domain_gap/footprint_crop.py:248-251`): kept iff the
  mean of the road's stored `<geometry x y>` anchor points lies inside the
  polygon. Coarser and not curve-aware; kept only for parity with RQ1's
  existing crop rule.

---

## 5. Closure and pruning

**Junction closure (rule c), `resolve_junction_closure`
(`ultimate_pipeline/domain_gap/footprint_crop.py:261-329`):** a junction is
kept iff, after discarding any of its own `<connection>` elements whose
`incomingRoad` or `connectingRoad` id is absent from the auto map entirely
(a pre-existing data-integrity defect, independent of this crop — counted as
`connections_removed_dangling`), at least one valid connection remains **and**
every remaining valid connection's `incomingRoad` is itself a kept road. This
is resolved to a fixed point with a `while changed:` loop
(lines 284-321), not a single pass, so nested junctions converge correctly
regardless of evaluation order. Once a junction is kept, all roads with
`@junction` equal to that junction's id are kept — never partially. Junctions
never resolved to "kept" are left in `pending` and recorded with reason
`incoming_road_not_in_footprint` (lines 323-324); a junction with zero
`<connection>` children is dropped with reason `no_connections`
(line 291); a junction whose connections are all dangling is dropped with
reason `zero_valid_connections_after_dangling_removal` (line 308).

**Link consistency (rule d), `apply_link_consistency` /
`apply_connection_pruning`
(`ultimate_pipeline/domain_gap/footprint_crop.py:374-422`):** applied only to
roads/junctions already kept by (b)/(c).

- A road-level `<link><predecessor/successor elementType="road" ...>`
  pointing at a non-kept road is removed (`road_link_predecessor_removed` /
  `road_link_successor_removed`).
- A road-level link pointing at a non-kept `elementType="junction"` is
  removed by the same code path and counter.
- Removing a road-level link also removes the matching lane-level link in
  the boundary `laneSection` — the first `laneSection` for a removed
  predecessor, the last for a removed successor, since those are the only
  `laneSection`s whose lane `<link>` can reference another road
  (`_drop_boundary_lane_links`, lines 342-355, counted as
  `lane_link_boundary_predecessor_removed` /
  `lane_link_boundary_successor_removed`).
- A defensive, non-standard-dialect check
  (`_drop_explicit_road_lane_links`, lines 358-371) removes any
  `<lane><link>` child carrying an explicit `road` attribute naming a
  non-kept road (as produced by some internal tiling representations; see
  `tiling/tile_extractor.py`'s `_drop_links_outside_tile`), counted
  separately as `lane_link_explicit_road_removed`.
- `apply_connection_pruning` (lines 404-422) is a defensive second pass over
  already-cloned, kept junctions: it removes any surviving `<connection>`
  whose `incomingRoad`/`connectingRoad` fell outside the final kept-road set.
  Given the closure guarantees above this should normally remove nothing; it
  exists so the output's own dangling-check always passes even under future
  changes to the closure logic.
- None of this can add or invent a link — only remove ones that would
  otherwise dangle.

**`<controller>` preservation/pruning (rule e),
`apply_controller_pruning` / `apply_junction_controller_ref_pruning`
(`ultimate_pipeline/domain_gap/footprint_crop.py:426-488`):** top-level
`<controller>` elements are first copied byte-faithfully, in document order,
into the output (line 643-644 of `crop_auto_to_manual_footprint`), then
pruned in place:

- A `<control signalId=...>` child is removed if it no longer resolves to a
  `<signal>` on a kept road (signals are scanned map-wide by id, independent
  of which road currently owns them), counted as
  `controller_controls_removed`.
- A controller left with zero `<control>` children **after** pruning is
  dropped entirely, counted as `controllers_dropped_zero_controls` — but
  only if it originally had at least one `<control>` child.
- A controller that was already empty of `<control>` children in the source
  is never dropped by this rule and is preserved untouched, counted as
  `controllers_empty_preserved`.
- A `<junction><controller id=.../>` grouping reference is removed if the
  controller it names was dropped, counted as
  `junction_controller_ref_removed`.
- `<signal>`/`<object>` elements need no special handling — they are
  children of `<road>` and survive or drop automatically with their owning
  road.

**Top-level element accounting (rules f/g,
`ultimate_pipeline/domain_gap/footprint_crop.py:112-131,646-682`):** any
top-level `OpenDRIVE` child kind with no dedicated reference-aware rule
(e.g. `junctionGroup`, `station`, `userData`, `include`) is preserved
byte-faithfully and unconditionally — the module's selection/closure rules
are scoped to `road`/`junction` only, so an unknown top-level kind carries no
reference this module could validate, and silently dropping it would break
the "pure subset" contract. Every top-level tag seen in the input is
recorded in the report's `top_level_accounting`
(`input_count`/`kept_count`/`dropped_count` per tag); for every handled kind
`kept_count + dropped_count == input_count` by construction, and for every
unknown kind `dropped_count` is always `0`. Output element order matches
source document order throughout (filter-by-membership over
`root.findall(...)`, never an unordered `set`/`dict` iteration), so given
byte-identical inputs and arguments the output is byte-identical.

---

## 6. Manifest

Written by the CLI to `<out-dir>/crop_manifest.json`
(`tools/rq3_crop_auto_to_manual_footprint.py:50-51,220-272`), schema
`rq3_crop_manifest/v1`. Top-level fields:

- `schema`, `tool`, `git_sha` (resolved via `git rev-parse HEAD` against the
  tool's own worktree, `"UNKNOWN"` on failure), `generated_at_utc`.
- `status` — `"PASS"` iff every entry in `hard_checks` is true, else
  `"FAIL"` (`tools/rq3_crop_auto_to_manual_footprint.py:215`). The process
  exit code mirrors this: `0` on `PASS`, `1` on `FAIL`
  (`tools/rq3_crop_auto_to_manual_footprint.py:277`).
- `hard_checks` — exactly **7** boolean checks, confirmed by reading the
  `hard_checks` dict literal
  (`tools/rq3_crop_auto_to_manual_footprint.py:206-214`):
  - `xml_well_formed`
  - `zero_dangling_references`
  - `check_lane_link_targets_exist_ok`
  - `check_road_link_reciprocity_ok`
  - `xodr_strict_validator_ok`
  - `controller_references_resolve`
  - `no_unaccounted_top_level_loss`

  `no_unaccounted_top_level_loss` is independently re-derived by the CLI
  itself from the source `auto_root` (parsed before any crop logic ran) and
  the output file re-parsed fresh from disk, not merely re-stated from the
  crop module's own report
  (`tools/rq3_crop_auto_to_manual_footprint.py:181-203`).
- `args` — `repo_root`, `out_dir`, `buffer_m`, `selection`,
  `sample_spacing_m` (the resolved values actually used).
- `inputs.auto_map_of_record` / `inputs.manual_grid0828` — each with
  `registry_key`, `path`, `sha256`, `bytes`, `verification_status` as
  returned by `verify_pinned_map`.
- `polygon_wkt`, `polygon_bounds_auto_local` — the footprint polygon from the
  crop report, verbatim.
- `counts` — the full counts dict from `crop_auto_to_manual_footprint`'s
  report (see §5's named counters, plus the totals in
  `ultimate_pipeline/domain_gap/footprint_crop.py:684-705`).
- `junctions_dropped_reasons`, `top_level_accounting` — verbatim from the
  crop report.
- `output.path`, `output.sha256`, `output.bytes` — of the written crop file.
- `validation` — the raw per-check results backing `hard_checks` (including
  `dangling_references.details` and
  `controller_references_resolve.details`).
- `timing_s` — `registry_verify`, `parse_inputs`, `crop`, `write_output`,
  `validate_output`, `total`.

---

## 7. Verified real-map result (2026-11-03)

Measured against the committed artifact at
`E:/wt/rq3_crop_artifact/auto_crop_grid0828_footprint.xodr` and its sibling
`crop_manifest.json` (both read-only during this verification pass; this
tool does not write there):

- `sha256sum auto_crop_grid0828_footprint.xodr` ->
  `b2bc2712d1a236deec167c04391aa0f711cfc0a176e6bbfa8b4b31c3ea147d12`. Matches
  the expected `b2bc2712` prefix and matches the sha256 already recorded in
  `crop_manifest.json`'s `output.sha256`.
- Recounted directly from that file with an `xml.etree.ElementTree.iterparse`
  script (the file is ~19 MB on disk; `iterparse` avoids holding the whole
  tree in memory): **3,584 `<road>` elements and 450 `<junction>`
  elements**. Both match the manifest's own `counts.roads_kept_total` (3584)
  and `counts.junctions_kept` (450) — no discrepancy to flag.
- `0` dangling references and all 7 hard checks `PASS`, taken from the
  committed manifest (`hard_checks`: `xml_well_formed`, `zero_dangling_references`,
  `check_lane_link_targets_exist_ok`, `check_road_link_reciprocity_ok`,
  `xodr_strict_validator_ok`, `controller_references_resolve`,
  `no_unaccounted_top_level_loss` all `true`; `counts.dangling_references_found`
  and `counts.unresolved_controller_references_found` both `0`); manifest
  `status` is `"PASS"`.
- Covers 100% of Grid0828 and 93% of auto road length inside the hull — as
  reported from the 2026-11-03 verification run.
- Road `49556` (4.48 km) is kept whole by design — confirmed present in the
  crop with `length="4477.96412626"` (4,477.96 m, i.e. ~4.48 km), read
  directly from the `<road id="49556" ... length="...">` attribute in the
  output file.

Manifest inputs recorded for this run:
`auto_map_of_record` sha256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`
(`verification_status: VERIFIED`), `manual_grid0828` sha256
`5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`
(`verification_status: VERIFIED`) — matching the current registry pins in
`ultimate_pipeline/carla_tools/map_registry.py` (§2 above). Run args:
`selection="any_point"`, `buffer_m=0.0`, `sample_spacing_m=2.0`.

---

## 8. Known limits

- **CARLA load not yet verified.** GAP-077 (RPC handshake hang) blocks
  loading this crop — or any map — into a live CARLA session from this
  environment; see
  `reports/production_readiness/20261104T000000Z_GAP_REGISTER_ADDENDUM_2/`.
- **Paired routes need surveyed same-place anchors.** The crop guarantees
  footprint equivalence, not route-level correspondence; RQ3 route pairing
  still requires a separate surveyed-anchor step.
- **Inherited map-of-record defects.** The crop is a pure subset of the
  pinned `auto_map_of_record`, so it inherits that map's known defects
  unchanged:
  - **GAP-070** — junction-exit kinks caused by the default-on junction
    connector snap rotating connectors at the exit join; root cause
    confirmed, a Hermite-refit remediation candidate exists but is unmerged
    and gated on a governed regeneration.
  - **GAP-079** — ~0.1 m single-line junction connectors with a ~180-degree
    reversed heading relative to their exit road; a distinct finding from
    GAP-070, not addressed by GAP-070's candidate fix.

  See
  `reports/production_readiness/20261104T000000Z_GAP_REGISTER_ADDENDUM_2/GAP_REGISTER_ADDENDUM_2.md`
  for both entries' full status and evidence commits.

---

## 9. Reproduce

```bash
mkdir -p E:/scratch/rq3_crop_repro
python tools/rq3_crop_auto_to_manual_footprint.py \
  --repo-root E:/wt/repair-map-realism-p0-837a8504 \
  --out-dir E:/scratch/rq3_crop_repro \
  --buffer-m 0.0 \
  --selection any_point \
  --sample-spacing-m 2.0
```

`--out-dir` must be a scratch location on a drive with headroom — never
under `<repo-root>/campaigns/` (refused by `_assert_safe_out_dir`, §3
above). Re-running with the same `--out-dir` requires `--overwrite-scratch`
if that directory is already non-empty.
