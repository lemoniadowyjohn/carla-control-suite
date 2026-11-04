# Artifacts missing for remote reproducibility

| # | Artifact | Needed for | Where it is now | Remedy |
|---|---|---|---|---|
| M1 | 3 Osm2Odr outputs `run_00{0,1,2}.xodr` | RQ1 | gitignored; location on disk not verified in this review | archive by sha256 (C0 store); add a canonical structural hash |
| M2 | full-pipeline repeated runs | RQ1 (full scope) | NOT_RUN | X8 arm C_OFF plus its repeat (needs ≥ 15 GiB) |
| M3 | Stage files of run `20261007_214826_524342` (1.06 GB) | GAP-070/079 findings | local, untracked | C0 archive (operator approval) |
| M4 | RQ4 checkpoints (5) | RQ4 re-evaluation | `G:/gap010-rq4-retrain-20260924/…` (md5 only) | archive with sha256 |
| M5 | RQ4 562 union tiles | RQ4 re-training, nulls | location not in repo | archive and hash, with a tile manifest |
| M6 | `manual_grid0821.xodr`, `candidate_connectivity_repaired.xodr` (full hashes) | RQ4 identity | local or gitignored; prefix hashes only | record full sha256 in a new manifest |
| M7 | RQ2 alignment residuals (fit + holdout) | RQ2 CRS/SE(2) claim | not reported | compute and report |
| M8 | Within-domain null distributions | RQ2, RQ4 | NOT_RUN | `STATISTICAL_NULL_AND_SAMPLING_PLAN.md` |
| M9 | Surveyed anchors (3 fit + 2 holdout) | RQ3 | not supplied (operator) | operator |
| M10 | RQ3 paired captures | RQ3, RQ5a | NOT_RUN (GAP-077) | operator CARLA run |
| M11 | Real-world dataset | RQ5b | none | external |
| M12 | Review trust root plus signed receipt | RQ3 admission | none (by design) | operator procedure |
| M13 | RQ4 training width mode (legacy vs polynomial) | RQ4 interpretation | not recorded in `aggregate_stats.json` | read `run_seed_ensemble_leakfree.py`, and record it in a new note |
| M14 | Fresh-OSM per-stage outputs | GAP-079 origin, U-turn origin | NOT_RUN (the 2026-10-07 run started from the map-of-record) | X8/X9b from raw OSM |
