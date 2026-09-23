# Thesis baseline vs. current state

This tracks what has changed in each research question's evidence since the submitted thesis
(`submission/thesis_source/`). RQ numbers match the thesis (`Chapter1/chap1.tex`, lines 24-28), which
is the authoritative source if this table and the code ever disagree — verify against
`reports/post_audit_hardening/C19_THESIS_ASSEMBLY/rq_tables.json` (regenerate via
`tools/export_thesis_tables.py`) rather than trusting this file's prose in isolation.

| RQ | Thesis baseline | Current state | What changed |
|----|-----------------|----------------|---------------|
| RQ1 — Determinism | Byte-level nondeterminism with stable structural/topological signatures under fixed inputs; thesis did not fully isolate the byte-level source. | AUTHORITATIVE for structural repeatability and raw byte non-repeatability; BOUNDED for timestamp-normalized byte equality. Three repeated Osm2Odr outputs differ at raw hash level and preserve the same road/junction/length signature; portable committed fixtures cover timestamp-only normalization in CI, while large local artifacts remain optional governed integration evidence. | Post-thesis root-causing (`C15_RQ4_DR`) and normalized-hash tests support timestamp metadata as the observed byte-level source. Do **not** claim exhaustive source isolation until the large-artifact evidence is regenerated and available after a clean clone. |
| RQ2 — Structural domain gap | Whole-map comparison only; a delivered discrete-Fréchet number computed on an uncropped, misaligned network | BOUNDED, with a corrected **local** (manual-map-footprint) comparison as the primary result: lane-width gap is small and the maps agree; curvature/road-length ratios show a real completeness gap (~2.7-3.8x under a convex-hull footprint, revised down from an earlier 4.5-6x bbox-footprint estimate); building density is now a genuine in-footprint comparison instead of force-excluded. A recomputed local Fréchet distance is ~30-50x smaller than the thesis's original whole-network number. **Re-verified 2026-09-17 against the current map-of-record pin (see note below): the ratio holds, 2.68x road length / 3.78x junctions / 3.56x road count (hull).** **The local Fréchet distance itself was separately re-verified 2026-09-17 against the same current pin: mean 58.18m / median 36.13m / p90 140.48m, 894 matched pairs (was mean 55.28m / median 35.26m / p90 128.01m, 895 pairs against a 6+-promotion-stale pin — see the second 2026-09-17 note below).** | `C14_RQ1_STRUCTURAL_GAP` + `C26` local-registration work; closes thesis future-work item #14 (Fréchet distance) with a corrected, scope-appropriate methodology. |
| RQ3 — Perceptual domain gap | Direct generated-vs-manual paired perceptual measurement was NOT completed. Generated-map capture failed at the CARLA runtime boundary; Town10HD validated only the sensor-rig implementation. | `DEFERRED_RUNTIME` — no generated/manual paired Ingolstadt evidence exists. | No scientific upgrade. Two distinct CARLA hangs have been identified this session — the earlier claim of GPU-independence was incorrect: **(1) Render-mode hang** — a plain/default launch (normal D3D rendering, no special flag) was debugger-attached mid-hang: the RHIThread is stuck inside NVIDIA's D3D driver (`nvwgf2umx.dll`, near `OpenAdapter10`), a genuine adapter/device-creation stall that IS GPU-driver-specific. This is a different issue from the earlier debunked TDR/watchdog hypothesis; the prior investigation proved the GPU wasn't the bottleneck for the *`-nullrhi`* hang specifically, but it did NOT prove GPU was uninvolved in the *render-mode* hang — the two hangs are unrelated. A follow-up test with `-RenderOffScreen` (CARLA's actual documented headless flag, tried as a candidate fix) showed the identical timeout signature (RPC socket binds/accepts, handshake never completes, process genuinely CPU-busy) but was not itself re-confirmed via a fresh debugger attach — consistent with, not independently proving, the same root cause. **(2) `-nullrhi` hang** — a separate busy-spin livelock with zero GPU involvement (VRAM stays at 0 MiB), confirmed via direct process sampling (CPU time advancing, working-set memory flat). Neither hang completes UE4's initialization far enough to service RPC. A Windows per-app GPU-preference override (forcing the dedicated NVIDIA GPU via the registry) was also tried as a candidate fix for hang (1) and showed no observable difference. **(3) Paired-capture protocol mismatch** — the one historical RQ3 capture attempt (2026-05-14) used mismatched frame counts (20 vs 8) and camera rigs (single vs 6-camera) between the two sides, producing null metrics; root-caused and fixed this session (`capture_config.py` PairedCaptureConfig, merged `fix/rq3-paired-capture-protocol-mismatch-v1-20260916`), so capture is ready the moment CARLA is reachable. See `reports/post_audit_hardening/C20_TIER1_PROBE_20260821/`, `C20_GPU_TDR_20260821/`, `C20_CARLA_RUNTIME_UNBLOCK/`, and the 2026-09-16/17 debugger-attached stack-trace investigation (RHIThread → `nvwgf2umx.dll` → `OpenAdapter10`, not yet formalized as a numbered report). Both cheap candidate fixes (`-RenderOffScreen`, GPU-preference override) are now ruled out — remaining paths are meaningfully more invasive (different driver branch, `-graphicsadapter=N`, or different hardware/CI runner). |
| RQ4 — Structural variability / latent representation | The thesis fixed GNN representation collapse using NT-Xent and obtained statistically supported latent separation, including a K=1000 permutation test with p<0.001. | **NOT CURRENTLY CITABLE AS AUTHORITATIVE — see 2026-09-23/24 leakage note below.** Previously reported: a 5-seed GNN ensemble trained on the union of both maps' road-network graphs, cosine_distance mean 0.6434 (95% bootstrap CI [0.616, 0.676]), CI excludes zero across all 5 seeds. The 95% CI is a bootstrap over only **n=5 seeds** (fragile tails — read as indicative; the thesis's K=1000 permutation p<0.001 remains the *primary* statistical support), and the metric is an in-sample union-domain latent-separation **diagnostic**, not held-out accuracy or transfer (see `reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/C21_STATISTICAL_PROVENANCE.md`). Explicit domain-randomization wiring is confirmed, but governed natural-vs-explicit DR experiments remain a separate extension. | The new contribution is the post-thesis multi-seed union-domain robustness layer (`C18_GNN_LATENT_GAP` → `C21_GNN_AUTHORITATIVE`), not the entire RQ4 result. The numbers changed materially on 2026-09-01 after fixing a graph-construction bug (lane-link edges were resolving to their own lane section instead of the successor's, making ~99.8% of training edges self-loops). **2026-09-23 update (GAP-010, `MASTER_GAP_REGISTER.json`): `audit_leakage()` found the eval-pair reference file (`manual_grid0821.xodr`) hash-matches content already present in the training set — a genuine train/eval content-identity leak. The exclusion mechanism was fixed and verified (`exclude_source_hashes=` threaded through `gnn_provenance.py`/`map_tile_dataset.py`/`run_ksweep.py`/`train_map_encoder.py`, real inject-leak→FAIL, fix→PASS end-to-end test), but the actual retrain on the now-leak-free split has NOT been run (assessed ~7.2h CPU-only, no CUDA on the machine that ran it — BLOCKED_EXTERNAL for the retrain specifically). The `cosine_distance=0.6434` figure above was computed BEFORE this leakage fix and must not be cited as a clean result until a leak-free retrain reproduces it (or a different number). No currently-trusted checkpoint is newly invalidated by this, since none had verified cryptographic provenance before or after — this is a forward-looking gate on future citations, not a retraction of a previously-certified one.** |
| RQ5 — Generalization and transfer | No downstream model-transfer experiment was completed; the question remained deferred. | `DEFERRED_RUNTIME` for RQ5(a) generated-train/manual-test transfer because it depends on valid RQ3 datasets. `DEFERRED_EXTERNAL_DATA` for RQ5(b) because no real-world Ingolstadt dataset exists on this machine. | No scientific upgrade. Unlabeled distribution shift/CORAL/MMD protocol checks are not model-generalization accuracy, and no manual-target training result may be relabeled as generated-to-manual transfer. |

## 2026-09-15 note: fresh whole-map domain-gap regen (does not change the RQ2 row above)

Every domain-gap comparison artifact on disk before this date compared the current pinned
auto map-of-record against nothing newer than `08_final_structural_gap.xodr`
(`submission/results/structural_gap_run11/`, whose own `fit_metric_provenance` field says its
geometry-RMSE fit was "carried forward from prior patch output, not reverified") or an even older
2026-08-19 candidate (`C14_RQ1_STRUCTURAL_GAP` / `C26`). Neither reflected the current pin
(`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`,
sha256 `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`, confirmed live against
`ultimate_pipeline/carla_tools/map_registry.py`'s `auto_map_of_record` entry and
`docs/runtime/MAP_OF_RECORD.md`), nor any of the ~10 domain-gap-computation bug fixes landed this
session (schema-order corruption in `GeoAligner.apply_to_xodr`, a point-duplication bug in the
alignment fallback extractor, a stale-header-bbox bug, a KL-divergence density-vs-probability-mass
bug in `CurvatureGap`, a header-offset rebase fix in `deterministic_alignment.py`, plus prior
paramPoly3-blindness fixes).

A fresh, real (non-synthetic) `ultimate_pipeline/run_full_domain_gap.py` **whole-map** run against
the current pin vs. `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr` is
recorded at `reports/production_readiness/20260915T101724Z_FRESH_DOMAIN_GAP_REGEN/` (see
`full_report.json`; ran end-to-end, `EXIT_CODE:0`, internal CSV/JSON parity check `ok=true` with 0
divergences). Headline whole-map numbers: geometry RMSE 85.32 m, Hausdorff 6968.60 m, curvature KL
divergence 0.00306, road-classification gap 0.0584, semantic/object gap 0.1644, intersection
normalized gap 0.1237. Auto object counts are now non-zero across the board (buildings 5682,
traffic lights 21163, lamp posts 24792, guard rails 21740, bench 1122, crosswalk 127) — the stale
run_11 artifact's 0/0/0/0 auto object counts were a pre-enrichment-snapshot artifact, not current
reality.

**Connectivity, specifically** (this session's re-examination target): the stale run_11 artifact's
`predecessor_valid_rate` / `successor_valid_rate` = 0.0 and `road_lane_link_valid_rate` = 0.0 (both
vs. manual's 1.0) — a near-total-failure reading — do **not** reproduce on the current pin. The
fresh run shows auto `predecessor_valid_rate` = 1.0, `successor_valid_rate` = 1.0,
`road_lane_link_valid_rate` = 1.0, identical to manual, with gap deltas of 0.0 instead of -1.0.
Confirmed: this was an artifact of the stale/mismatched auto candidate (and/or predates this
session's junction/lane-link bug fixes), not current reality. The one connectivity sub-metric that
still showed a gap at the time was *declared*-link rate (whether a `predecessor`/`successor` element
is present at all, mostly absent on junction-connector roads): auto ~0.29 vs. manual ~0.94 — a
different question from link *validity*, which is what run_11 had flagged as broken.

**2026-09-16 update — root-caused and fixed, was a real bug, not a spec-compliant omission.** This
gap was investigated end-to-end (see
`reports/production_readiness/20260916T142400Z_DECLARED_LINK_RATE_INVESTIGATION/`). Root cause:
`ultimate_pipeline/tools/xodr_carla_hardener.py`'s `_fix_connectivity()` unconditionally deleted the
road-level `<link>` element from every junction-connector road (`road.junction != "-1"`) under a
`JUNCTION_LINK_REMOVED` finding, on the premise "junction connectors should not have road-level
links." That premise was empirically false: the manual/RoadRunner-authored reference map
(`Grid0828.xodr`) declares `<link>` on 725/725 (100%) of its junction-connector roads, and this
pipeline's own OSM-based generator already produces the same 100% coverage on the current pin
*before* the hardener runs (verified directly against
`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`).
The hardener's blanket removal (22,589 roads on the current pin — exactly the junction-connector
count) was the sole cause of the auto/manual declared-rate gap; all removed links were independently
confirmed valid (`predecessor_valid_rate`/`successor_valid_rate` = 1.0 before removal). The two link
mechanisms are not redundant: `<junction><connection>` disambiguates which connecting road to use
for lane-level routing across multiple alternatives, while the connector road's own `<link>` is what
lets a road-by-road traversal (CARLA's `Waypoint::GetNext`/`GetPrevious`, this pipeline's own
lane-continuity phases) cross the connector without junction-aware special-casing — both this
project's own generator and the RoadRunner-authored reference agree on this and populate both.
Fixed by removing the unconditional-removal block and instead validating junction-connector links the
same way ordinary-road links already were (kept if they resolve to an existing road, removed only if
dangling); see `tests/unit/test_xodr_carla_hardener.py::test_fix_connectivity_junction_connector_valid_road_link_preserved`
and `::test_fix_connectivity_junction_connector_dangling_road_link_removed`. Before/after on the
current pin (`ConnectivityGap.compute`, real run, no mocks): `predecessor_declared_rate`
0.2898 → 0.9898 (gap -0.6458 → +0.0543), `successor_declared_rate` 0.2898 → 0.9899 (gap
-0.6779 → +0.0221). Branch: `fix/declared-link-rate-gap-v1-20260916`.

This whole-map run is **not** a replacement for the RQ2 table row above, which reports a
manual-map-footprint **local** comparison (a deliberately different, narrower-scope methodology
adopted specifically because an uncropped whole-map comparison overstates the gap — see the RQ2 row
and `C14`/`C26`). The whole-map road-length ratio in the fresh run is ~27.8x
(1,489,146 m auto / 53,525 m manual, uncropped), consistent with that concern and not a regression
signal on its own. Tile IoU / per-tile metrics were not computed in this run
(`UP_SKIP_TILE_ALIGNMENT=1`, `per_tile_status=skipped`, reason: per-tile auto-tiling subprocess
reliably exceeds its hardcoded timeout on this city-scale candidate — see the commit that added the
skip path) and elevation gap remains `disabled` (`dem_qc_failed`, planar/no-DEM map, unchanged from
every prior run).

## 2026-09-17 update — RQ2 local hull-footprint number re-verified against the current pin

The ~2.7-3.8x local completeness-gap number was, until this date, still computed by
`scripts/regen_local_registration.py` against a hardcoded, long-stale candidate path
(`ingolstadt_perception_map_of_record_20260819_160350.xodr`) — a pin that predates 5 subsequent
map-of-record promotions (09-02, 09-04 x2, 09-05 x2) and, more importantly, predates both the
map-of-record regenerated 2026-09-17 (see `docs/runtime/MAP_OF_RECORD.md`, which fixes two real
pipeline bugs: `946228f9` junction-connector `<link>` stripping, `a13efd91` degenerate-`<planView>`
deletion) and every domain-gap-computation bug fixed earlier this session (`GeoAligner` schema-order
corruption, alignment-extractor point-duplication, stale-header-bbox, `CurvatureGap` KL
density-vs-probability-mass bug, `deterministic_alignment.py` header-offset rebase — see the
2026-09-15 note above). This was exactly the "declined to re-verify" gap flagged previously; it has
now been executed and is not an automatic swap but an actual re-run with the real result reported
below, whichever direction it moved.

`scripts/regen_local_registration.py` was updated to resolve its auto-side XODR through the C13 pin
registry (`verify_pinned_map("auto_map_of_record")`) instead of a hardcoded filename, so this
specific staleness cannot recur silently on future promotions. Re-run against the new pin
(`ingolstadt_perception_map_of_record_20260916_232831.xodr`, sha256 `370abbbbb3...`) vs. the
unchanged manual reference (`Grid0828.xodr`); output regenerated at
`reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/local_registration.json`.

**Result: the ~2.7-3.8x finding holds, effectively unchanged.** Hull footprint (primary/default):
road-length ratio **2.683x** (was 2.69x), junction ratio **3.782x** (was 3.78x), road-count ratio
**3.561x** (was 3.57x), curvature_gap 0.2206 (was 0.2192), lane_width_gap 0.0597 (was 0.0415, moved
more than the others but still small in absolute terms). Bbox footprint (legacy, reported
side-by-side): road-length ratio 4.488x (was 4.5x), junction ratio 6.05x (was 6.05x), road-count
ratio 6.119x (was 6.12x). Building density (frame-corrected, in-footprint): hull gap 0.2308 (3,279
kept / 5,682 total auto buildings vs. 993 manual), consistent with the C26-era finding that both
maps show comparable, plausible building density once correctly cropped.

**Important caveat — the alignment/curvature fixes above are NOT exercised by this number.**
`ultimate_pipeline/domain_gap/local_registration.py` (the module this script calls) is a
self-contained implementation with its own convex-hull footprint crop, its own curvature-gap
calculation, and its own coordinate-frame handling — it does not import or call `GeoAligner` or
`CurvatureGap`, the two modules whose bugs were fixed this session. Those fixes live in the
*whole-map* pipeline (`ultimate_pipeline/run_full_domain_gap.py` and friends), not this one. So this
re-verification confirms the RQ2 hull-footprint ratio is stable under the regenerated,
bug-fixed **map** (the two `xodr_carla_hardener`/`GeometryValidator` fixes), but it does *not*
confirm anything about the `GeoAligner`/`CurvatureGap` fixes, because the code path that had those
bugs is not the code path that produces this number. If those specific fixes are ever expected to
move the RQ2 local number, that would require porting/reusing them inside
`local_registration.py`, which was not attempted here (out of scope for a re-verification pass —
would be a methodology change, not a re-run).

## 2026-09-17 update — RQ2 local Fréchet-distance number (thesis item #14) re-verified against the current pin

`reports/post_audit_hardening/THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md`'s headline figures
(mean 55.28m / median 35.26m / p90 128.01m, 895 matched pairs) were computed as a one-off
invocation against the map-of-record pin current on 2026-08-27 (`744757f3...`) — no dedicated,
re-runnable script for it survived in git history, unlike `scripts/regen_local_registration.py`
(fixed earlier in this same 2026-09-17 pass, see the note directly above). By 2026-09-17 that pin
was 6+ promotions stale.

New script `scripts/regen_frechet_distance.py` resolves the auto-side XODR through the same C13
pin registry (`verify_pinned_map("auto_map_of_record")`) and calls
`ultimate_pipeline.domain_gap.frechet_gap.compute_frechet_gap` directly (no math
reimplemented — that module already had its own 12-test TDD suite plus this script's own thin
wrapper is now covered too, `tests/unit/test_frechet_gap.py`). Run against the current pin
(`ingolstadt_perception_map_of_record_20260916_232831.xodr`, sha256 `370abbbbb3...`) vs. the
unchanged manual reference (`Grid0828.xodr`); output at
`reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/frechet_distance.json`.

**Result: mean 58.18m, median 36.13m, p90 140.48m, 894 matched pairs (hull footprint)** — close
to but not identical to the stale figures (mean +5%, median +2%, p90 +10%, one fewer matched
pair), reported as actually computed rather than adjusted toward the old numbers. This is
consistent with the same-day RQ2 hull-footprint re-verification directly above (ratios "held,
effectively unchanged" under the regenerated map) and with the module's own cross-check logic:
cropped-auto-road-count / manual-road-count = 3,536 / 993 ≈ 3.56x, matching the RQ1 hull finding
of ~3.561x reported in the same-day `local_registration.json` re-run. The same **"NOT exercised
by this number"** caveat as the hull-footprint re-verification applies: `frechet_gap.py`, like
`local_registration.py`, does not import `GeoAligner` or `CurvatureGap`, so this confirms
stability under the regenerated **map**, not anything about those two modules' bug fixes.

`THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md` itself is marked superseded at its top (see
`docs/research/STALE_ARTIFACT_POINTERS.md` for the full pointer); its methodology description
remains accurate, only its headline numbers are stale.

## Infrastructure changes not tied to a specific RQ

- **CI correctness**: fixed a global `builtins.print` monkeypatch that entrypoint modules applied at
  import time (corrupted JSON output for any test running later in the same process), a racy
  fake-sensor test helper that could cross-contaminate RGB/semseg frames, a gitignored-file test
  dependency, and a CRLF/LF cross-platform checkout mismatch in a frozen evidence manifest's hash
  check.
- **Packaging**: `pyproject.toml` previously packaged only `ultimate_pipeline`, silently excluding
  `opendrive_geometry/` and `phase_q/` (both actively imported elsewhere) from any built wheel.
- **RQ-numbering integrity**: `tools/export_thesis_tables.py` had drifted from the thesis's actual RQ
  numbers (structural gap tagged "RQ1" instead of RQ2, perceptual gap tagged "RQ2" instead of RQ3, GNN
  work tagged "RQ3/RQ5" instead of RQ4). Relabeled (values unchanged) and added
  `ultimate_pipeline/config/thesis_rq_contract.py`, an explicit metric→RQ allow-list that
  `audit_thesis_topic_contract.py` now validates against, so a future numbering drift fails the audit
  instead of passing silently.
- **`pipeline_health_summary.py`**: previously reported `overall_ok=True` when zero gate evidence was
  collected at all (e.g. no `qa_stage_reports/` directory) — indistinguishable from "every gate ran
  and passed." Now reports `overall_ok=False`, `status="NOT_RUN"` for that case.

## Still blocked, not a code-level gap

- **RQ3 live paired capture** and **RQ5(a) transfer evaluation**: both need a working CARLA runtime.
  Two distinct initialization hangs block this: a GPU-driver-specific adapter-creation stall in the
  render path (`nvwgf2umx.dll`), and a separate `-nullrhi` busy-spin livelock — both prevent UE4
  from reaching RPC-readiness. The paired-capture protocol mismatch that caused null metrics in the
  one historical attempt has been fixed (`capture_config.py`), so capture is ready the moment CARLA
  is reachable. The remaining blocker is environment-level (CARLA 0.9.16 Windows build on this
  GPU/driver combination), not something further code changes here can resolve.
- **RQ5(b) real-world evaluation**: needs an operator-supplied real-world Ingolstadt dataset.
- **RQ2 thesis-vs-current controlled comparison, RQ4 multi-seed extensions**: legitimate follow-up
  research, not corrections — not attempted as part of infrastructure hardening passes.
