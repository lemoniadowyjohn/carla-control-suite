# Codex PROMPT KK: determine whether tile-scale CARLA loading is feasible on this hardware

## Context

The `ultimate_pipeline/` map-generation pipeline (CARLA/OpenDRIVE) has a
tiling subsystem (`ultimate_pipeline/tiling/`, `ultimate_pipeline/domain_gap/`,
`ultimate_pipeline/carla_tools/tile_world_runner.py`,
`ultimate_pipeline/tile_validation/`) that was built primarily for domain-gap
COMPARISON (splitting the map into a grid to compute per-tile
structural/curvature metrics vs. a manual reference map). It was NOT built or
validated as a way to reduce CARLA's own rendering/VRAM load.

Goal: determine whether it's actually possible to load and drive a
tile-sized subset of the pinned Ingolstadt map-of-record
(`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`,
32267 roads, ~148MB) in live CARLA on a machine with a 6GB VRAM Quadro P3200
Max-Q GPU, which currently hits a GPU-driver-TDR livelock when loading the
full map (see repo memory `project_carla_runtime.md` and
`project_rq2_rq5_blocker_root_causes_20260830.md` for the TDR root cause).

## Known facts to build on (verify only if something looks stale, don't re-derive)

- `ultimate_pipeline/tiling/tile_extractor.py:TileExtractor.tile()` already
  splits an XODR into `tile_<i>_<j>.xodr` files with a configurable buffer
  (`TILE_BUFFER_M`, default 20m in `settings.py:1149`; `TILE_SIZE` default
  500.0 in `settings.py:1144`). It's documented as producing "observation
  windows" with intentional successor/predecessor leakage outside the tile
  (tracked in `tile_health.semantics.successor_leakage` /
  `predecessor_leakage`), NOT self-contained routing graphs, unless
  strict_semantics/standalone routability is explicitly enabled.
- `ultimate_pipeline/carla_tools/tile_world_runner.py:TileWorldRunner.load()`
  is a real, wired-up code path that reads one tile `.xodr` and feeds it
  through `load_opendrive_world()`/`carla.OpendriveGenerationParameters()`
  exactly like a full map load. It's invoked by
  `ultimate_pipeline/tile_validation/carla_tile_tester.py`, the STEP10
  ("Unified Tile QA") subprocess worker
  (`ultimate_pipeline/pipeline_stages/stage_10_tile_qa.py`).
- STEP10 is gated by `SETTINGS.ENABLE_SIMULATION_GATE`, which defaults to
  `False` (`settings.py:1337`) and causes STEP10 to unconditionally skip. As
  a result, no `campaigns/*/tiles/` directory and no `step10_tile_qa*.json`
  result has ever been produced for the pinned Ingolstadt map on this
  branch.
- The only tile `.xodr` files that exist anywhere in the repo are 4 stale
  samples under `reports/post_audit_hardening/20260804T060000Z/tiles/` from
  an older, much smaller map (32710 roads scanned but only 1555 union roads
  / 1414 "core" roads across a 2x2 grid at `tile_size_m=1000`). These are
  NOT representative of tile density for the current 32267-road Ingolstadt
  map and must not be reused as evidence of feasibility.
- `reports/post_audit_hardening/20260804T060000Z/PHASE_I_TILING_STRATEGY.json`
  explicitly records the policy decision `carla_map_identity=ONE_LOGICAL_MAP_PER_CAMPAIGN`
  and `xodr_logical_partitioning=NOT_APPLIED_cooked_single_identity` — i.e.
  tiling was deliberately never connected to CARLA map identity/loading for
  production use. Treat this as a policy that must be either deliberately
  superseded (with a new dated strategy artifact explaining why) or
  respected — do not silently contradict it.
- CARLA's native "Large Maps" / World Composition streaming feature is
  unrelated: it streams pre-baked UE4 tiled levels, not raw OpenDRIVE files
  loaded via `generate_opendrive_world()`. Do not conflate the two; this
  task is about standalone single-tile XODR loading via `TileWorldRunner`,
  not CARLA's own streaming.

## Tasks (work through in order; stop and report if a step shows the approach is infeasible rather than forcing it)

1. Generate real tiles for the actual pinned map. Run
   `ultimate_pipeline/tiling/tile_extractor.py`'s `TileExtractor.tile()` (or
   the pipeline stage that wraps it) against the pinned candidate with the
   default 500m tile size. Write outputs to a clearly-scoped directory
   (e.g. `campaigns/ingolstadt_cooked_perception_v1/tiles_500m/`) — do not
   write into `MANUAL_TILES_DIR`, which is reserved for the manual
   reference map. Record per-tile road counts, file sizes, and
   `tile_health` metadata (drivability, leakage) for every tile produced.
2. Identify whether any tile's road count is small enough to plausibly
   avoid the TDR livelock. There is no established road-count/VRAM budget
   for this GPU in the repo yet — derive one: find the smallest full map
   that has successfully loaded live on this machine's CARLA install
   (check repo memory / CI logs for any prior successful live-CARLA load
   and its road count) and use that as a provisional ceiling. Flag clearly
   if no such baseline exists, since that means step 3 is an unvalidated
   guess.
3. Enable `SETTINGS.ENABLE_SIMULATION_GATE` for a scoped local run (do not
   change the default in `settings.py`) and actually invoke
   `TileWorldRunner.load(<one candidate tile>.xodr)` against a running
   CARLA server on this machine, exactly the same way
   `ultimate_pipeline/tile_validation/carla_tile_tester.py` does it.
   Capture whether it loads successfully, how long it takes, and whether
   the known TDR livelock reproduces. This is the single most important
   piece of missing evidence identified by the investigation behind this
   prompt — do not skip it or substitute a dry-run/mock.
4. Because tiles are "observation windows" with intentional
   successor/predecessor leakage and are not guaranteed locally-closed
   routing graphs, determine what breaks when actually driving in one
   (e.g. via CARLA's traffic manager or manual control) — check whether
   vehicles can path-plan to/through leaked links that point at roads
   absent from the tile. If tiles need to be standalone-routable for a
   driving demo (not just a visual load test), evaluate
   `tile_extractor.py`'s `strict_semantics` /
   `allow_successor_outside_tile=False` option and note the tradeoff
   (smaller buffer-preserving tiles vs. dangling routes).
5. If tile loading works within VRAM budget: wire a minimal, documented
   way to pick and load a single tile for local dev/testing on this
   machine (a small CLI wrapper or a settings flag is fine — do not build
   a full streaming system, that's explicitly out of scope per the
   PHASE_I strategy policy unless this task's findings justify revisiting
   it). If it does NOT work (VRAM budget still exceeded, or TDR still
   reproduces even at tile scale): report that plainly as the outcome —
   do not paper over a negative result.
6. Update or add a dated strategy/status artifact (following the existing
   convention in `reports/post_audit_hardening/*/PHASE_I_TILING_STRATEGY.json`)
   recording: actual tile road counts for the current pinned map, whether
   a live CARLA load was attempted and its result, and an explicit go/no-go
   verdict on using tiling as a VRAM-reduction technique on this hardware.
   Add a new `project_*.md` repo-memory entry summarizing the outcome so
   future sessions don't re-investigate from scratch.

## Constraints

- Do not change `ENABLE_SIMULATION_GATE`'s default or any other pipeline
  default as a side effect of testing.
- Do not delete or overwrite the 2026-08-04 sample tiles in
  `reports/post_audit_hardening/20260804T060000Z/tiles/`; they're
  historical artifacts referenced by `PHASE_I_TILING_STRATEGY.json`.
- If CARLA cannot be started live on this machine at all in your execution
  environment, state that explicitly as a blocker rather than fabricating
  results — this mirrors a documented prior failure mode in this repo (see
  the fabricated-memory-content caveat in memory
  `project_c0_clean_regen_pinned.md`).
- Run the full test suite (bare `pytest`, not a manually typed path list —
  `pytest.ini`'s `testpaths` covers several directories a manual list
  misses) before calling anything done, and report pass/fail counts.
- Push your branch and report status; do not merge into
  `integration/session-batch1-20260912` yourself.
