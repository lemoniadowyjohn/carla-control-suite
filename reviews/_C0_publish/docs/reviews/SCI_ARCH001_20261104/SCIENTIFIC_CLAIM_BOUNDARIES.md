# SCI-ARCH-001 — Scientific claim boundaries per RQ (2026-11-04)

**Verdict: `NEEDS_METHOD_CHANGE`.** RQ1, RQ2 and RQ4 have reproducible numbers, but their current
wording exceeds what the evidence supports. RQ3 and RQ5 have no measurements, and none may be
written.

Baseline: `integration/post-pr16-final-20261102` @ `1a36b560a69286841d4c42973cf00258a38f56c1`.
Provenance classes: GITHUB_VERIFIED (a committed file at that SHA), LOCAL_REPRODUCED,
CLAIMED_UNVERIFIED, NOT_RUN.

Each claim below is labelled as one of:
- **retrospective explanation** (why a number is what it is);
- **statistical assertion** (a claim with uncertainty);
- **forward-looking hypothesis** (not yet tested).

## RQ1 — determinism of OSM → OpenDRIVE

| Claim in use | Evidence | Class | Boundary |
|---|---|---|---|
| "The generator is structurally deterministic" | `reports/post_audit_hardening/C15_RQ4_DR/C15_RQ4_DOMAIN_RANDOMIZATION.json` `determinism_arm`: **3 runs**, 3 unique byte SHAs, "structure_signature_identical": num_roads = 32,920, num_junctions = 3,717, total length 1,498,527.59 m | GITHUB_VERIFIED (summary JSON); **the 3 XODRs are gitignored** (`…/determinism/.gitignore`) | The evidence covers **Osm2Odr only (stage 01)**, not the full pipeline, and the "signature" is **3 aggregates**. Identical counts and total length do not prove identical topology or geometry: two maps with swapped links or moved roads can share them. **Retrospective explanation, not a statistical assertion.** |
| "Raw bytes differ only by timestamps" | `tests/unit/test_exp_osm_to_xodr_determinism_normalized.py` (5 passed, 1 skipped): **string fixtures** for normalization | GITHUB_VERIFIED (test) | The test proves the normalizer works on toy strings. It does not prove that the 3 real XODRs differ only in timestamps; that needs the files, which aren't published. |
| Run `20261007_214826_524342` as RQ1 evidence | its manifest: `INPUT_XODR` = the map-of-record | LOCAL_REPRODUCED | **Not RQ1 evidence**: Osm2Odr is not executed (ARCH-003 errata X5). |
| Full-pipeline determinism (through 07, post-enrichment) | — | NOT_RUN | Open scope gap (already acknowledged). |

**Minimum remedy:**
- publish (or archive by hash) the 3 Osm2Odr outputs;
- replace the aggregate signature with a **canonical structural hash**: sorted per-road (id-free)
  geometry tuples, lane tuples and link graph;
- run N ≥ 3 full-pipeline repetitions (X8 arm C_OFF plus its repeat gives 2);
- state "structurally deterministic at stage 01 for 3 runs" until then.

## RQ2 — structural domain gap (auto vs manual Grid0828)

| Claim | Evidence | Class | Boundary |
|---|---|---|---|
| Map identities | `reports/production_readiness/20260923_RQ2_REVERIFICATION/local_registration.json` `source_files`: auto = `…map_of_record_20260916_232831.xodr` sha256 `370abbbb…`; manual = `Grid0828.xodr` sha256 `5eaece23…`. Registry `ultimate_pipeline/carla_tools/map_registry.py:741, 912-913` match. | GITHUB_VERIFIED | **Reconciled:** the 2026-08-19 pin (`…20260819_160350.xodr`) was stale and was replaced 2026-09-17 (`docs/research/THESIS_TO_CURRENT_PROGRESS.md:93-104`). The current RQ2 numbers use the 2026-09-16 map. |
| Hull-local ratios 2.683 (length), 3.782 (junctions), 3.561 (roads) | `local_registration.json` `hull.crop`: 143,606.1 / 53,525.3 m; 3,536 / 993 roads | GITHUB_VERIFIED | Correct as computed. **Footprint-sensitive:** with a bbox the length ratio is **4.488**. Report both. |
| "lane width and curvature agree closely" inside the footprint | hull-local lane_width_gap **0.0597**, curvature_gap **0.2206** (curvature Wasserstein 0.0752); whole-map 0.0415 / 0.0931 | GITHUB_VERIFIED | The current wording mixes whole-map and local values (errata X6). Moreover, "close" has no reference scale. Without a null (gap between two halves of the same map, or between two manual maps), 0.06 and 0.22 cannot be called small or large. |
| "A real completeness gap (full OSM extraction vs a curated hand model)" | counts and lengths only | interpretation | **Retrospective explanation, unproven.** The count ratios can also come from **authoring conventions**: Osm2Odr splits roads at every OSM way and node, makes per-direction twin roads (shared-reference U-turns, ARCH-003 L-02) and adds many short connectors, whereas the hand model may merge them. Requires road-network correspondence (spatial matching of centre lines, length-weighted) and a segmentation-invariant metric (total drivable lane-km, junction count after merging junctions within r m). |
| CRS / SE(2) alignment | `provenance`: auto tmerc WGS84 with offset (832671.676, 5458671.104); manual tmerc with its own parameters | GITHUB_VERIFIED (record) | Alignment residuals are not reported in this file. Require the fit residuals of the alignment (RMS, max) and a holdout check. |
| Map quality of the auto map | ARCH-003: about 3,700 U-turn lane links are lane-discontinuous in the map-of-record | LOCAL_REPRODUCED | Lane-width and curvature metrics on junction areas are affected. Report RQ2 with and without junction connectors. |

## RQ3 — perceptual domain gap (paired CARLA capture)

**No measurement exists. Status: DEFERRED / NOT_RUN.** Nothing may be stated beyond the plan.

Required before any number:
- the same geographic route on both maps, registered with ≥ 3 fit + 2 holdout surveyed anchors (the
  project's own CHAT-05 requirement; none supplied);
- identical sensor intrinsics and extrinsics (`SENSOR_CALIB_JSON` sha256 `054a2d8b…` is recorded in
  the run manifest), weather, lighting and time of day;
- synchronous mode with a fixed tick;
- a route-level (not frame-level) sampling unit;
- a site-aware route subset that excludes junction areas affected by GAP-070/L-02, or stratifies by
  them.

Label class ids must map identically on both maps. **Capture existence, label correctness and
admission are three separate states:** a signed review receipt gives admission only (no trust root
exists). The CARLA runtime is blocked (GAP-077).

## RQ4 — structural variability in a learned latent space (GNN)

| Claim | Evidence | Class | Boundary |
|---|---|---|---|
| "cosine distance 0.921, 95% CI [0.845, 0.976]" | `reports/production_readiness/20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN/aggregate_stats.json`: 5 seeds (42-46), values 0.905, 0.775, 0.967, 0.963, 0.994; std 0.088; bootstrap n_boot = 2000 **over the 5 seeds** | GITHUB_VERIFIED (JSON); **checkpoints on local G:** (md5 recorded), not published | **Statistical assertion about training-seed variability for one fixed map pair.** It is **not** uncertainty over maps or regions. With n = 5, a percentile bootstrap is unstable; report the 5 values and their range. |
| "Auto and manual maps occupy clearly separated regions" | `ci_excludes_zero_similarity = true` | — | **Rejected as a separation test.** A cosine distance > 0 is expected for any two non-identical inputs. Separation needs a **null**: within-domain distances (manual vs manual tiles, or auto vs auto from disjoint regions, or a split of the same map), and a permutation test on domain labels. **[corrected 2026-11-04]** A thesis-era K=1000 permutation test (p<0.001) is reported in `docs/research/THESIS_TO_CURRENT_PROGRESS.md:14`. It is REPORTED_NOT_REPRODUCED (unit and statistic undocumented), and it predates the 2026-09-01 graph-builder fix and the GAP-010 leak fix. No null exists for the leak-free 0.921 retrain. |
| Which maps | the training exclusion contract excludes `cities/ingolstadt/manual_grid0821.xodr` and `candidate_connectivity_repaired.xodr` | GITHUB_VERIFIED (JSON) | **The RQ4 pair is not the RQ2 pair** (Grid0828 and the 2026-09-16 map). Name the pair explicitly in every RQ4 sentence, and do not combine RQ2 and RQ4 as one map comparison. |
| Graph representation | `ultimate_pipeline/domain_gap_gnn/graph_builder.py:55-57`: `JUNCTION_EDGE_POLICY = "no_edge_when_junction_mediated"` (tile XODRs carry no `<junction>`); `:26-27`, `:161-183`: width mode legacy (`width_a_only_v0`) or polynomial | GITHUB_VERIFIED (code) | The latent space **omits junction topology**. The post-hoc audit used `width_mode="legacy"` (`post_hoc_leakage_audit.py:46`); the training script `run_seed_ensemble_leakfree.py` passes no `width_mode`, and the default is `"legacy"` (`graph_builder.py:309`; polynomial mode was added in `ad63cee5` on 2026-09-23, the day before the retrain). *Hypothesis (inferred from defaults, unrecorded):* training used legacy width (the `a` coefficient only). State both limitations. |
| Leak-free | `PRE_TRAINING_LEAKAGE_AUDIT.json`, `POST_HOC_LEAKAGE_AUDIT.json` | GITHUB_VERIFIED | Source-SHA exclusion closes the content-identity channel only. Spatial-adjacency leakage (neighbouring tiles of the same region in train and eval) is not addressed. |
| Population claims ("auto maps differ from manual maps") | one region (Ingolstadt), one map per domain | — | **Not supported.** Needs independent multi-region data. Historical values (0.643 superseded, 0.921) are kept, with a restricted interpretation. |

## RQ5 — generalization (sim → manual; sim → real)

**No measurement exists. Status: DEFERRED / NOT_RUN.** RQ5a depends on RQ3 captures; RQ5b has no
real-world data.

Required:
- the frozen protocol `configs/rq5_protocol_freeze_v1.json` (sha256 `db7155fe…`);
- data admission;
- per-class IoU **support**: the pixel count per class. Classes absent in an evaluation split must be
  reported as absent, not as IoU 0 or 1 (`ultimate_pipeline/perception/eval_sim_labeled.py:152-196`
  supports `ignore_index` and returns `per_class_iou`);
- uncertainty by **route or scene-block bootstrap**, never by frames (adjacent frames are
  correlated);
- variance across seeds, maps and routes reported separately;
- for RQ5b, a held-out real dataset with label-space mapping.

No RQ5a or RQ5b value may be fabricated or extrapolated.

## Governance
- **Fail-open paths to check (SCI-001 patch, when it exists):** any RQ table exporter that reads a
  value without verifying the source hash; any default map path resolved without the registry.
- **Missing source identity:** the RQ1 XODRs (gitignored), the RQ4 checkpoints (G:), the 562-tile
  set (location not in the repo), and the stage inputs of run `20261007_214826_524342` (local).
