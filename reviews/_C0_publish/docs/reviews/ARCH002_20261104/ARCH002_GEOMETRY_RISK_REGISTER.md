# ARCH-002 geometry risk register (2026-11-04)

Evidence class for every row: `LOCAL_REPRODUCED_NOT_REMOTE_VERIFIED`. The input is the local
stage-5 file, sha256 `45c52059…`; it is not on GitHub.

| ID | Risk | Severity | Branch@SHA / location | Status | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-01 | The default-on snap shifts outer-lane connectors' reference lines by whole lane widths, so lane-level continuity is lost | **P0** | `1a36b560` `tools/junction_connector_snap.py:289`, `pipeline_stages/stage_05_geometry.py:103` | OPEN; lane-centre confirmation pending | snap default OFF, or a lane-border-aware skip; measure lane-centre continuity | C1 (redirected) |
| R-02 | Hermite refit collapses shared-reference U-turns (3,375) into needles | **P0** | `2cee039f` `junction_connector_snap.py:196-232` | OPEN | do not refit U-turns; or drop the refit entirely if R-01's fix lands | C1 |
| R-03 | `@length` ≠ arc length after a refit (344; max 4.02×), so s-indexed lanes, elevation and signals are mispositioned | P1 | `2cee039f` `:205-226` | OPEN | reject, or recompute and rescale | C1 |
| R-04 | Unbounded displacement (max 14 m; `rechain_guard_m` deleted) | P1 | `2cee039f` `:284-302` | OPEN | guard; the threshold is an operator decision | C1 / operator |
| R-05 | Endpoint-only validation accepts geometrically invalid curves | P1 | `2cee039f` `:408-418` | OPEN | full invariant gates (ARCH_X8_X9 matrix) | C1 |
| R-06 | The "entry mismatch" metric compares reference lines and scores correct lane-border placement as a defect; the 2026-09-12 enable-by-default decision relied on it | P1 | `junction_connector_snap.py` `_count_junction_issues` | OPEN | replace it with a lane-centre metric; re-label the old metric in reports | O-task |
| R-07 | No lane-centre / lane-boundary continuity metric exists | P1 | — | OPEN | new report-only checker | O-task |
| R-08 | Pre-existing Osm2Odr U-turns with radius ≈ 1.6 m (3,949 at stage 01, in the map-of-record) may not be drivable in CARLA | P2 | map-of-record `370abbbb…` | OPEN | operator decision on the minimum radius; CARLA check | operator |
| R-09 | Lane consistency of the 3,393 connectors that start neither on a from-lane border nor on the reference point (mostly U-turns) is unknown | P2 | stage 05 | OPEN | include in the lane-centre check | O-task |
| R-10 | Heading convention ignores contactPoint flips (latent; 0 cases on this map) | P2 | `2cee039f` `:188`, `:380` | OPEN (latent) | flip by π; add tests B8 | C1 |
| R-11 | Validator false negatives (sub-sample loops, near-needles, unsupported primitives) | P1 for X8 | O13 (missing) | OPEN | adversarial tests C1-C14 | O13 |
| R-12 | GAP-079 reversed 0.1 m stubs (58 at stage 01, 81 at stage 02), classification pending | P2 | `06a31ed1` (local) | OPEN | X9b part 2 | Codex |
| R-13 | Stage-3 and stage-5 outputs of the 2026-10-07 run are byte-identical (`45c52059…`) | P3 (provenance) | run `20261007_214826_524342` | OBSERVED, not explained | X8 must record per-stage hashes and explain any identical stages | C2 |
| R-14 | The evidence inputs exist only on this machine (about 1.06 GB of stage files) | P1 (reproducibility) | local `reports/rq1_trial_runs/run_01/20261007_214826_524342/` | OPEN | C0 archive (operator approval) | operator |
| R-15 | No CARLA traversal evidence for any connector variant | P1 | GAP-077 | BLOCKED_EXTERNAL | operator visible-window run | operator |
