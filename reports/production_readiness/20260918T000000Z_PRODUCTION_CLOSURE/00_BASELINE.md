# Production Closure Baseline — 20260918T000000Z

## Git state

- Integration lineage: `integration/session-batch1-20260912`
- Verified HEAD: `1a42cd89bbaaeca95e6f326225afa5a4c23e707d`
- `main` is a disconnected old lineage — **not used as baseline**.
- Production branch: `integration/production-large-map-20260918` — did not exist before this run.

## Pending branches (P0 work package A)

Neither has been merged into integration HEAD as of this baseline:

1. `fix/large-map-transactional-staging-integrity-v1-20260917` @ `c75fd8c9` — 4 files, +224/-11.
   Fixes: hardlink→copy for staged artifacts (byte-independence); FBX roundtrip `False` now fails
   closed instead of being overwritten to `status="ok"`.
2. `feat/pipeline-stage-dependency-contract-v1-20260917` @ `e99ec35b` — 4 files, +638.
   Adds `StageCapabilitySpec`/requires-provides validation/current stage-sequence model. Does not
   itself reorder stages.

## Reference-only branches (do not wholesale-merge)

`recovered-large-map-offline-hardening-f43bf84c`, `feature/ue4-large-map-production-v2`,
`fix/grid08210828-runtime-rca-v3`, `fix/geometry-crs-dem-correctness-v1-20260915`, old `audit/*`
branches, disconnected RoadRunner/Codex lineages. Several fixes from these have already been
independently reimplemented on integration this session — compare before porting anything.

## Current map-of-record

- `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr`
- SHA256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`, 149,799,632 bytes
- 32,267 roads / 3,561 junctions. `valid_for_experiments=true`, `hard_fail_reasons=[]`.
- Soft warnings: `lane_count_changes` unexplained=3007 (first-ever measurement of this gate against
  this map lineage — see P1 work package G), `component_reachability` 3 isolated components
  (within precedent).
- Manual reference: `Grid0828.xodr`, SHA256 `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`
- Pinned OSM SHA256: `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`

## Tool/environment availability

| Tool | Status | Detail |
|---|---|---|
| Python (venv) | ✅ | 3.12.2 |
| Git / Git LFS | ✅ | 2.46.2 / 3.5.1 |
| Blender | ✅ | `E:\Program Files\Blender Foundation\Blender 4.3\blender.exe` |
| SUMO netconvert | ✅ | `C:\Sumo\sumo-win64extra-1.24.0\...\netconvert.exe`, v1.24.0 |
| OSM2World | unverified this pass | used elsewhere this session via `osm2world_runner.py` |
| CARLA 0.9.16 runtime | ⚠️ installed, **RPC blocked** | `E:\CARLA\CARLA_0.9.16` — packaged Shipping binary, no Source/Editor |
| CARLA source tree | ❌ | `G:\CARLA\carla_source_probe` — clone incomplete, LFS download stalled |
| UE4.26 | ❌ | `G:\UE4` — empty, no engine present |
| NVIDIA driver/GPU | Quadro P3200 Max-Q, driver 573.22, 6GB VRAM | confirmed hybrid/Optimus laptop (adapter 0=Quadro, 1=Intel UHD 630) |
| cdb.exe (Windows debugger) | ✅ | installed 2026-09-17 for the CARLA hang investigation |

## Known upstream blockers (BLOCKED_EXTERNAL, per this prompt's own evidence-class discipline)

**CARLA RPC server never becomes responsive.** Extensively re-investigated 2026-09-16/17 with real
`cdb.exe`-attached stack traces (not guesswork). Two *distinct* hangs share one external symptom:

1. Render mode: `RHIThread` stuck inside `nvwgf2umx.dll` (NVIDIA D3D driver) near `OpenAdapter10` — a
   genuine GPU-adapter/device-creation stall.
2. `-nullrhi` mode: a separate busy-spin loop, zero GPU involvement, idle in a `GetCursorPos`-adjacent
   poll.

All three cheap/local candidate fixes were tried and ruled out with real evidence, not assumption:
`-RenderOffScreen` (identical timeout), Windows per-app GPU-preference registry override (no
observable difference), `-graphicsadapter=0` and `=1` (neither connects; adapter=1 moves the hang
entirely out of the NVIDIA driver into an unrelated idle-wait state — confirms the flag does something,
just not the fix). This is a genuinely exhausted dead end for cheap fixes on this specific machine, not
an under-investigated blocker. **Blocks**: `VERIFIED_CARLA_LOAD`, `VERIFIED_STREAMING`,
`VERIFIED_6GB_RUNTIME`, real RQ3 capture, real RQ5(a) transfer-training data.

**UE4.26 not installed; CARLA source clone incomplete.** No engine source/Editor anywhere on this
machine. G: has 252GB free (disk space is no longer the blocker), but VS2022 C++ workloads /
CMake≥3.28 / Ninja / Epic-GitHub account linking have not been confirmed done, and even the CARLA
source clone itself never finished downloading its Git LFS objects. **Blocks**: `VERIFIED_UE_IMPORT`,
`VERIFIED_COOK`, and everything downstream in the promotion ladder.

**No real-world Ingolstadt dataset.** `eval_real_unlabeled.py` is built/tested, ready the moment data
exists. **Blocks**: RQ5(b) labeled evaluation.

These three blockers are logged here as `BLOCKED_EXTERNAL` per this program's own instruction ("if the
environment is not available: mark BLOCKED_EXTERNAL. Do not fabricate these levels as PASS.") — they
constrain which work packages can proceed with real, verifiable evidence right now (A–N: offline
structural/visual/packaging work) versus which remain blocked until external setup changes (O–V:
UE import/cook, live CARLA load/streaming/6GB runtime, real paired capture).
