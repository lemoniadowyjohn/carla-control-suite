# Thesis baseline vs. current state

This tracks what has changed in each research question's evidence since the submitted thesis
(`submission/thesis_source/`). RQ numbers match the thesis (`Chapter1/chap1.tex`, lines 24-28), which
is the authoritative source if this table and the code ever disagree — verify against
`reports/post_audit_hardening/C19_THESIS_ASSEMBLY/rq_tables.json` (regenerate via
`tools/export_thesis_tables.py`) rather than trusting this file's prose in isolation.

| RQ | Thesis baseline | Current state | What changed |
|----|-----------------|----------------|---------------|
| RQ1 — Determinism | Byte-level nondeterminism with stable structural/topological signatures under fixed inputs; thesis did not fully isolate the byte-level source. | AUTHORITATIVE for structural repeatability and raw byte non-repeatability; BOUNDED for timestamp-normalized byte equality. Three repeated Osm2Odr outputs differ at raw hash level and preserve the same road/junction/length signature; portable committed fixtures cover timestamp-only normalization in CI, while large local artifacts remain optional governed integration evidence. | Post-thesis root-causing (`C15_RQ4_DR`) and normalized-hash tests support timestamp metadata as the observed byte-level source. Do **not** claim exhaustive source isolation until the large-artifact evidence is regenerated and available after a clean clone. |
| RQ2 — Structural domain gap | Whole-map comparison only; a delivered discrete-Fréchet number computed on an uncropped, misaligned network | BOUNDED, with a corrected **local** (manual-map-footprint) comparison as the primary result: lane-width gap is small and the maps agree; curvature/road-length ratios show a real completeness gap (~2.7-3.8x under a convex-hull footprint, revised down from an earlier 4.5-6x bbox-footprint estimate); building density is now a genuine in-footprint comparison instead of force-excluded. A recomputed local Fréchet distance is ~30-50x smaller than the thesis's original whole-network number. | `C14_RQ1_STRUCTURAL_GAP` + `C26` local-registration work; closes thesis future-work item #14 (Fréchet distance) with a corrected, scope-appropriate methodology. |
| RQ3 — Perceptual domain gap | Direct generated-vs-manual paired perceptual measurement was NOT completed. Generated-map capture failed at the CARLA runtime boundary; Town10HD validated only the sensor-rig implementation. | `DEFERRED_RUNTIME` — no generated/manual paired Ingolstadt evidence exists. | No scientific upgrade. The blocker is now precisely characterized: a live CARLA server never becomes RPC-responsive, confirmed independent of map choice and rendering backend (`-nullrhi` isolation) and independent of the GPU driver (a chronic TDR watchdog fault was found and fixed separately, but the RPC hang persists) — see `reports/post_audit_hardening/C20_TIER1_PROBE_20260821/` and related C20 reports. |
| RQ4 — Structural variability / latent representation | The thesis fixed GNN representation collapse using NT-Xent and obtained statistically supported latent separation, including a K=1000 permutation test with p<0.001. | AUTHORITATIVE extension: a 5-seed GNN ensemble trained on the union of both maps' road-network graphs reports cosine_distance mean 0.6434 (95% bootstrap CI [0.616, 0.676]), CI excludes zero across all 5 seeds. The 95% CI is a bootstrap over only **n=5 seeds** (fragile tails — read as indicative; the thesis's K=1000 permutation p<0.001 remains the *primary* statistical support), and the metric is an in-sample union-domain latent-separation **diagnostic**, not held-out accuracy or transfer (see `reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/C21_STATISTICAL_PROVENANCE.md`). Explicit domain-randomization wiring is confirmed, but governed natural-vs-explicit DR experiments remain a separate extension. | The new contribution is the post-thesis multi-seed union-domain robustness layer (`C18_GNN_LATENT_GAP` → `C21_GNN_AUTHORITATIVE`), not the entire RQ4 result. The numbers changed materially on 2026-09-01 after fixing a graph-construction bug (lane-link edges were resolving to their own lane section instead of the successor's, making ~99.8% of training edges self-loops). |
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
every prior run). No change is being made to the RQ2 row's authoritative ~2.7-3.8x local
completeness-gap number; if this whole-map result is ever thought to warrant revisiting that number,
that is a human call, not an automatic swap.

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
  The RPC-hang blocker is environment-level, not something further code changes here can resolve.
- **RQ5(b) real-world evaluation**: needs an operator-supplied real-world Ingolstadt dataset.
- **RQ2 thesis-vs-current controlled comparison, RQ4 multi-seed extensions**: legitimate follow-up
  research, not corrections — not attempted as part of infrastructure hardening passes.
