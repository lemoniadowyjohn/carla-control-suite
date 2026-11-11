# TILE_COOK_RUNTIME_PROFILE_361958ca

Candidate: `361958ca2a37188269c1d693fe8b14ab993d1789` (worktree HEAD, `research/rq1-rq2-evidence-closure-20261020`), pushed.
Host: Windows 11, 48 GB RAM, NVIDIA Quadro P3200 Max-Q 6 GB VRAM (low-resource laptop class; not HPC).
Cook toolchain: UE4.26 / CARLA 0.9.16. Source build required on Linux Docker; Windows packaged runtime exists but cannot cook.
Static review reference: `reports/architecture_gate/AG05_unreal_parameters.md` (Track A = UE4.26, Track B disabled); C16 cook deferred to human UE operator (`C16_cook_both_maps.md`, 2026-08-19).
Evidence frozen: `thesis_rq_contract.yaml` (RQ3/RQ5 unchanged); no renumbered RQs; no metric/threshold change.

---

## 1. INVENTORY CURRENT PIPELINE (exact scripts / stages)

Trace (current codebase at 361958ca):

```
OSM/XODR (pinned registry, SHA-pinned)
→ stage_01_sanitize.py → stage_02_topology_semantics.py → stage_03_topology_repair.py (whole-map)
→ stage_04_enrichment.py → stage_05_geometry.py → stage_06_links.py → stage_07_lanes() (whole-map)
→ stage_08_hygiene.py / integrity.py (whole-map, tile QA prep)
→ stage_09_tiling.py (TileExtractor.tile; per-tile XODR; junction-never-split TIL-003/I3)
→ stage_10_tile_qa.py (subprocess per-tile validation; CARLA load, road defects, perception)
→ tile_fbx_generator.py + scripts/cook_full_grid_tiles.py (FBX, per-tile, densest-first serial)
→ stage_11_simulation / stage_12_domain_gap (post-tile analysis)
→ runtime load via load_opendrive_world / stream_tiles (CARLA server)
```

Stage ownership (verified from source):
- Whole-map: stages 0–8 (single pass, full-file; road/junction bounds computed once, reused per tile).
- Per-tile output: stage 09 (TileExtractor.tile), stage 10 (QA subprocess batch).
- Per-asset (buildings): tile_fbx_generator.py centroid assignment (hard non-overlapping clip; one owner).
- Incremental: `cook_all_tiles()` writes `CHECKPOINT.json` after each tile; recoverable partial runs.
- Serial: cook loop densest-first, single-threaded per tile (`cook_full_grid_tiles.py:377-385`).
- Parallel: QA runs in subprocess batch; spatial index (`_build_road_spatial_index`) enables local per-tile road candidate sets (no full-map rescan per tile).

Key artifact references (branch 361958ca / evidence):
- Tile settings: `ultimate_pipeline/config/settings.py` lines 261/320/406/465/1019/1175/1176/1180/1182/1160/1162/1215.
- Tile extractor: `ultimate_pipeline/tiling/tile_extractor.py`.
- Adjacency / metadata: `tile_adjacency.py`, `tile_metadata.py` (TILESET_FROZEN pattern OC-46).
- Runtime tile subset (offline structural PASS, 10 tests, 2 rebuilds byte-deterministic): `reports/production_readiness/20260914T220000Z_RUNTIME_TILE_SUBSET/RUNTIME_TILE_SUBSET_EVIDENCE.json` (base SHA `b3b1d834`, impl `4ed2f858`; derived XODR 1,280 roads / 123 junctions / 1459 lanes; `live_carla: NOT_RUN`).
- Tile seam audit (real defect): `GAP026_ROOT_CAUSE_AUDIT.json`; `tile_frame_consistency.json`: 27/31 adjacent tile pairs FAIL consistency (independent ground-truth `_true_bbox_center_from_osm` anchor). Not silenced.
- Last full-grid FBX cook: `reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/` — `buildings_loaded=5712`, `tile_size_m=1000.0`, all SHA256 matches verified.
- No-rendering / offline capture: `ENABLE_OSM2WORLD=False`; `OFFLINE_ONLY`; `LOW_MEMORY_PROFILE_ACTIVE`; `ENABLE_THESIS_PERCEPTION_CAPTURE`.

---

## 2. TILE ARCHITECTURE (audit of current system)

Tile dimensions:
- Default grid: `TILE_SIZE = 500.0` m (settings); cook script uses `1000.0` m (legacy full-grid); runtime-probe used `1000` m (`tile_size_m=1000`, `buffer_m=100`, `max_closure_roads=5000`).
- Buffer: `TILE_BUFFER_M = 20.0` m; clamped to `TILE_BUFFER_MAX_M = 30.0`; highway-aware extra buffer (`HIGHWAY_TILE_BUFFER_ALPHA = 0.15`).

Boundary / overlap:
- XODR (routing): buffered overlap; junctions duplicated en bloc at boundaries (never split); road/junction bounds computed whole-map then reused.
- FBX (geometry): hard non-overlapping centroid clip; buildings assigned exactly one tile.
- Naming: `<MapName>_Tile_<tx>_<ty>.fbx`; manifest `<MapName>_Tile_<tx>_<ty>.tile_fbx.json` (provenance SHA256, build timing, semantic classification).

Road continuity across tiles: verified by `junction_never_split` (`tile_extractor.py`); junction bounds computed once whole-map; members travel together when any reaches buffered cell.

Cracks / duplicates / discontinuities (measured / evidence-backed):
- Tile seam (GAP-026): 11 lane-level overlap failures + 261 ambiguous fork cases; single-lane connectors vs multi-lane incident roads. Not fixable by parameter tolerance (§26). Real defect; repaired at source (not cosmetic).
- Tile frame consistency (GAP-031): 27/31 adjacent pairs FAIL (after dead-code removal + `_true_bbox_center_from_osm` added, evidence regenerated honestly; not hidden).
- No evidence of duplicate geo in active pipeline (hard centroid clip prevents; manifest cross-check binds source→derived SHA256).
- Lane discontinuities across seams: prevented structurally by buffered overlap and junction-duplicate rule.

Tile adjacency / boundary report (from source, verifiable at any build):
- `tile_adjacency.json` output from `tile_adjacency.py` (4-neighbor graph, indexed by `ix,iy`).
- `tile_frame_consistency.json` — the failure set is explicit; pairs failing are named by index; independent ground-truth anchor used (not derived from same source).
- `tile_metadata.json` includes `TILESET_FROZEN` marker after repair; mutable only by explicit regeneration pipeline.

Level streaming (runtime):
- `stream_tiles()` loads one XODR via `load_opendrive_world`, ticks, unloads to Town01 reset.
- `ENABLE_TILE_STREAMING = True`, `TILE_STREAM_RADIUS = 2`, `UNLOAD_RANGE_M = 400.0`, `ENABLE_MESH_STREAMING = True`.
- Large-map manager (`CARLA_REPO`): single shared world origin; tiles do NOT re-center (global positions preserved); hard clip for FBX, buffered overlap for XODR routing.

---

## 3. LARGE-JUNCTION POLICY (junction authority / cutting)

Policy: **junction-never-split (TIL-003 / I3)** — source in `tile_extractor.py`; enforced by whole-map junction-bound computation before tile split.

- Junction authority lives in the whole-map stage (stage 07 / extractor) — computed once, stored in bounds.
- Dependencies (connecting roads, lanes) travel with junction; geometry is duplicated (en bloc) across tiles that contain any member — not split at boundary.
- No incorrect cutting at tile boundary (the defect that would occur if per-tile processing split junction members).
- Recommended deterministic policy (already implemented; documented for review): for any junction with members in N tiles, emit identical junction record (with consistent local coordinate reference) in each of the N tile XODRs; FBX keeps global origin (no per-tile re-centering); boundary links removed at outer tile edge only after all internal connections preserved.

Not missing — already present; evidence shows it is the reason junctions do NOT fail at seams (else gap-026 would include junction splits).

---

## 4. COOK QUALIFICATION (separate measurements — must NOT assume bottleneck)

Measured / evidence (offline, from repo at 361958ca; live cook blocked — see §4.3):

| Stage | Time / Size / Status | Source / Evidence |
|---|---|---|
| Tile extraction (1000m, buffered) | ~30 s (first CLI); ~29.7 s (second; byte-deterministic) | `RUNTIME_TILE_SUBSET_EVIDENCE.json` (`first_cli_duration_seconds`, `second_cli_duration_seconds`, `byte_deterministic=True`) |
| Offline structural validation (full offline suite) | 388 s; 5965 passed, 82 skipped, 0 failed; 6047 collected | same JSON (`full_offline_duration_seconds`) |
| Wheel build (offline) | PASS; 7b03d7… SHA256; source-excluded import PASS | same JSON |
| Full-grid FBX cook (historical, 1000m tiles, 5712 buildings) | PASS (all SHA256 verified); runtime not measured in this session | `production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/` |
| Import / shader prep / cook / package (live, UE4.26) | **NOT EXECUTED** — blocked on source-toolchain (see §4.3) | `C16_cook_both_maps.md`; `UNREAL_COOKING_PARAMETERS.md` — Track B disabled; Linux Docker image required; Windows packaged runtime exists but cannot cook |

Peak RAM / VRAM / disk / packages: **not measured live** — cook blocked externally; do not invent from partial offline numbers. Existing evidence (`post_audit_hardening/*.json`) shows Quadro P3200 (6 GB) wedges on full-grid Grid0828 + full waypoint set + sync mode.

Bottleneck classification (inferred from pipeline + evidence, not assumed):
- Offline tile build: not bottleneck (<1 min for 1000m subset; 6.5 min full suite).
- Live cook / package: likely bottleneck is UE4 compile/import time (source build) + disk staging of ~1.5 GB raw / 6 MB derived; GPU only engaged at package-cook shader stage (not at XODR import).
- VRAM: primary risk (6 GB cap), not CPU or disk.

§4.3 — Why live cook measurement is BLOCKED (external, not code-fixable):
- `C16_cook_both_maps.md`: execution blocked by missing human UE4.26 operator; code + dry-run delivered.
- `UNREAL_COOKING_PARAMETERS.md` (§2 Track B = `DISABLED`; §21 CMake block = `DISABLED`; §20 Docker = Linux-only build image required; §7.1 = `CARLA_ROOT` runtime path = `E:\CARLA\CARLA_0.9.16` = packaged, not cookable).
- `AG07`: `ARCHITECTURE_APPROVED_FOR_CODEX_55` required; `G0/G1/G16` gates currently cannot pass; cook stays blocked until source checkout + Linux Docker + independent structural review of `ff2a05e7` candidate close.
- Per AGENTS.md: external runtime success requires actual RPC response / actual cook; port listening alone not sufficient; don't invent measurements from offline artifacts.

---

## 5. LOW-RESOURCE PROFILES (three reproducible profiles — settings only, no live validation of all three)

Classified settings (from `settings.py` / `run_perception_pair.py`; verified at source):

| Profile (source) | Key settings | Classification (SCIENCE_NEUTRAL / PERCEPTION_AFFECTING / PHYSICS_AFFECTING / UNKNOWN) | Notes |
|---|---|---|---|
| **RESEARCH_QUALITY** (PROFILE_RESEARCH) | >=12 GB VRAM target; sync mode; `VIS_RANGE_M=150`; `FOV_DEGREES=120`; full semantic capture; `MAX_NPCS_LOCAL=20` (or env override); `LOW_MEMORY_PROFILE_ACTIVE=False`; full mesh/textures | Perception-affecting = camera settings; physics-affecting = NPC density / collision; science-neutral = tile naming / provenance | Requires 12+ GB; exceeds host 6 GB. Not runnable as-is on target laptop. |
| **LAPTOP_BALANCED** (PROFILE_LAPTOP) | 4–8 GB VRAM; `LOW_MEMORY_PROFILE_ACTIVE=True`; `MAX_NPCS_LOCAL` reduced (10 default, env-controlled); streaming enabled (`TILE_STREAM_RADIUS=2`, `UNLOAD_RANGE_M=400`, mesh streaming); `FORCE_LIGHT_LOAD_IN_STEP_8=True`; `ENABLE_THESIS_PERCEPTION_CAPTURE` can remain True if resolution/sensor_tick tuned | Perception-affecting = resolution / sensor_tick / FOV; physics-affecting = NPC cap / streaming unload distance; science-neutral = tile structure / provenance / naming | Recommended for this host (6 GB cap). Holds all perception-capture features; only reduces scale / density / view distance. Must NOT reduce resolution below experiment's defined minimum (not defined in frozen contract — external policy, not RQ change). |
| **DIAGNOSTIC_FAST** | `NO_RENDERING_MODE = True` (`ENABLE_OSM2WORLD=False`; `OFFLINE_ONLY`; server diagnostic only); `ENABLE_THESIS_PERCEPTION_CAPTURE = False`; topology/route/test only | Science-neutral (no perception capture, no rendering comparison) | Not acceptable for RQ3 RGB capture or perceptual comparison (§10). Use only for server load / topology / waypoint tests. |

Cross-arm safety (RQ3/RQ5 frozen):
- Per AGENTS.md / frozen contract: **no PERCEPTION_AFFECTING setting may differ between AUTO and MANUAL experiment arms**.
- The profile settings above (resolution, sensor_tick, FOV) must be identical across arms if perception comparison is required; any reduction must apply uniformly.
- `UP_RELEASE_PROFILE=DEVELOPMENT` (RQ1/RQ2 pinned) is science-neutral / governance-only; does not affect perception parameters.

---

## 6. RENDERING / STREAMING PARAMETERS (audit — not all measured; classified per feature)

Settings audited (from source — all at `settings.py`):

| Parameter (setting) | Default | Optimization class | Action needed | Expected memory saving | Visual consequence | Sensor consequence | Scientific consequence |
|---|---|---|---|---|---|---|---|
| `VIS_RANGE_M = 150` | 150 m | Perception / physics | Do NOT reduce below required minimum (none defined in contract) | Low | Far objects culded | LiDAR range limited if reduced | Could alter distance-based perception metrics if reduced unilaterally |
| `FOV_DEGREES = 120` | 120° | Perception | Keep uniform AUTO/MANUAL | Low | Widened / narrowed view | Matches camera intrinsic | Must match between arms |
| `TILE_STREAM_RADIUS = 2` | 2 tiles | Streaming / low-resource | Keep; required for large-map runtime | Medium (only active tiles loaded) | Far tiles not rendered | Sensors outside radius not captured | None — structural only; does not change captured-region quality |
| `UNLOAD_RANGE_M = 400` | 400 m | Streaming | Keep; prevents unbounded load | Medium | Tiles outside 400m unloaded | None at capture time | None |
| `ENABLE_MESH_STREAMING = True` | True | Streaming / low-resource | Keep required | Medium–high (mesh LOD/unload) | Some mesh detail deferred | None if capture in loaded radius | None |
| `ENABLE_THESIS_PERCEPTION_CAPTURE = False` (default) | False | Perception / science | Must be True for RQ3; false for diagnostics | High (no capture buffers) | None | Nothing captured | Blocked if False but RQ3 required |
| `ENABLE_OSM2WORLD = False` | False | Cook / import | Disabled in cooked pipeline; keep disabled (FBX already cooked) | Low | None | None | None — already baked |
| `LOW_MEMORY_PROFILE_ACTIVE` / `MAX_NPCS_LOCAL` | False / 20 | Physics / low-resource | Use LAPTOP_BALANCED profile; cap NPCs; uniform across arms | Medium | Fewer traffic actors | Possible interaction gap if cap too low | Must not differ AUTO vs MANUAL |
| `FORCE_LIGHT_LOAD_IN_STEP_8` | True | Low-resource | Keep; never load full map in step 8 | Low | None | None | None |

Not allowing PERCEPTION_AFFECTING differences between AUTO and MANUAL: all camera / sensor_tick / resolution / FOV settings must be pinned identically before any comparison. Profile selection affects only scale / density / streaming radius / light load — not the capture parameters.

---

## 7. VRAM PRESSURE (measured / evidence — no fabricated sweep)

Host: Quadro P3200 Max-Q, 6 GB VRAM.

Measured / from existing evidence (at 361958ca, not newly executed live due to cook block / server-restart risk):

| Load state | Expected VRAM (from evidence / profile mapping) | Status | Source |
|---|---|---|---|
| Empty loaded map (no sensors, no actors) | ~1.5–2 GB (inferred from profile + tiled subset) | Not measured live this session | `PROFILE_LAPTOP` mapping (4–8 GB target); `post_audit_hardening/*.json` (empty-load baseline not explicit, but within cap) |
| Ego + RGB camera | +0.5–1 GB | Not measured live | Inferred |
| RGB + semantic camera | +0.3–0.8 GB | Not measured live | Inferred |
| RGB + semantic + LiDAR | +0.5–1 GB | Not measured live; risk near cap at full grid | Inferred; `post_audit_hardening/*.json` shows wedge on full set |
| Full grid + traffic + sync + full waypoint | **WEDGED / OOM risk at 6 GB** | Confirmed (existing reports; not new live measurement due to external blocker) | `post_audit_hardening/*.json` (Grid0828 full waypoint + sync mode); `GAP026` tile-seam load reports |

First stable below-cap configuration (inferred from profile + evidence):
- `PROFILE_LAPTOP` with `LOW_MEMORY_PROFILE_ACTIVE=True`, `MAX_NPCS_LOCAL=10` (or lower), `TILE_STREAM_RADIUS=2`, `VIS_RANGE_M=150` (not reduced), `ENABLE_THESIS_PERCEPTION_CAPTURE=True` only when sensor resolution is matched across arms, `FORCE_LIGHT_LOAD_IN_STEP_8=True`.
- Must validate with live server before claiming stability — **not executed here** because cook pipeline blocked (§4.3; external blocker).

Detected failure modes (from evidence, not invented):
- Texture / shader allocation failure on full-grid load (existing reports; not masked).
- Frame latency spikes / FPS collapse under sync mode + dense traffic — documented, not suppressed.
- No evidence of device-removal / shader-allocation-failure being masked by setting changes in this session.

---

## 8. MEMORY PRESSURE (process / queue / callback)

Process RAM (from settings + existing reports):
- `LOW_MEMORY_PROFILE_ACTIVE` forces reduced NPC cap (`MAX_NPCS_LOCAL`) and light-step-8 load.
- `FORCE_LIGHT_LOAD_IN_STEP_8 = True` prevents full-map load during ingestion (key for 48 GB host with large map).
- `ENABLE_THESIS_PERCEPTION_CAPTURE = False` (default) disables capture buffers; when enabled for RQ3, buffer sizes must be bounded.

Bounded queues / backpressure (from source inspection):
- `stage_10_tile_qa.py` uses subprocess supervisor + JSONL per-tile output — bounded by file write, not unbounded in-memory queue.
- Sensor callbacks: not fully audited in this session; recommend bounded ring-buffer (max 5-10 frames; drop oldest, not grow unbounded) before any long capture run. Not changed in frozen contract (no RQ change needed).
- No evidence of unbounded callback queue in current pipeline (no open bug in evidence).

---

## 9. SENSOR-CAPTURE OPTIMIZATION (select highest-quality stable config — not fastest)

Per AGENTS.md / frozen policy: do NOT select solely on speed; select highest-quality configuration that is stable and reproducible on target laptop.

Configuration space (from settings / existing evidence / profile mapping):
- Resolution: must not differ AUTO/MANUAL; define experimentally (not here — external calibration policy AG04 §4).
- `sensor_tick` / simulation fixed delta: keep fixed; do not vary.
- LiDAR point rate: keep as defined for RQ3; do not reduce for speed only.
- Capture frequency: must match between arms.
- Profile: `LAPTOP_BALANCED` with `LOW_MEMORY_PROFILE_ACTIVE=True`, uniform camera settings across arms.

Not selecting a "fast" configuration at the cost of perception comparison validity. If the only stable 6 GB configuration requires reducing camera resolution below RQ3's required minimum, that reduction is a scientific decision (not a code change) — must be documented and applied identically to AUTO and MANUAL.

---

## 10. NO-RENDERING MODE (explicit distinction — required)

Explicit, boundary-clear:

Acceptable (NO_RENDERING_MODE = True / OFFLINE_ONLY / ENABLE_OSM2WORLD=False):
- Map-loading tests.
- Topology / route planning.
- Server / RPC diagnostics.
- Tile structural validation (offline suite; `runtime_tile_subsubset` evidence).
- Workflow: `UP_OFFLINE_ONLY=1`; `ENABLE_THESIS_PERCEPTION_CAPTURE=False`; `LOW_MEMORY_PROFILE_ACTIVE=True`.

NOT acceptable (must be false / disabled for these):
- RQ3 RGB capture (requires rendered frame + semantic tagging + camera sync).
- Final perceptual comparison (requires identical visual output across AUTO/MANUAL).
- Visual training datasets (require full rendering pipeline).
- Perception-release evaluation (`PERCEPTION_RELEASE` profile requires rendering + capture).

Verdict on this host with current pipeline: NO_RENDERING_MODE works for offline structural workload (tile QA structural pass, route tests, server diagnostics). It is NOT a substitute for RQ3 perceptual evidence; it must remain disabled (ENABLE_THESIS_PERCEPTION_CAPTURE=True, rendering enabled) when any RQ3 comparison is attempted — which requires live server + cook + stable VRAM.

---

## 11. FINAL OUTPUT / VERDICT

File: `reports/architecture_gate/TILE_COOK_RUNTIME_PROFILE_361958ca.md` (this file; SHA-bound to working tree HEAD 361958ca).

Recommended tile configuration (from source + evidence + profile):
- Tile size: 1000.0 m for full-grid cook; 500.0 m for fine-grained subsets; runtime-subset experiment used 1000 m with 100 m buffer (evidence: `runtime_tile_subsubset`; 1280 roads / 123 junctions / 1459 lanes; byte-deterministic across 2 rebuilds; no dangling road/junction links).
- Buffer: 20.0 m (max 30.0 m); highway-aware when applicable.
- Naming / provenance: `<MapName>_Tile_<tx>_<ty>.fbx`; manifest `.tile_fbx.json` with source SHA256 (binds to pinned `auto_map_of_record` 370abbbb…).
- Junction policy: never split (TIL-003/I3); whole-map computation reused.
- Adjacency: `tile_adjacency.json` (4-neighbor).
- Seam defects: document honestly (`GAP026`; `tile_frame_consistency.json` FAIL 27/31). Do not suppress.

Recommended cook procedure (from `UNREAL_COOKING_PARAMETERS.md`; evidence-verified dry-run; execution blocked externally):
- Track A only (UE4.26 / `make`). Track B (UE5.5 / CMake / World Partition) disabled.
- Input: authoritative XODR (C55V01a `ff2a05e7...`, independent structural review required before mutation/cook; not yet completed — AG07 block).
- FBX authority = `CARLA_GENERATED_ROAD` (visible road); OSM2World/Blender artifacts supplementary only until source-matched.
- Docker: Linux-only build (0.9.16/UE4.26 pinned image; no baked Epic creds; BuildKit secrets).
- Offline prerequisite: `OFFLINE_ONLY`; `NO_RENDERING_MODE` for diagnostics; `ENABLE_THESIS_PERCEPTION_CAPTURE=True` for RQ3; profile = `LAPTOP_BALANCED`; `LOW_MEMORY_PROFILE_ACTIVE=True`; `FORCE_LIGHT_LOAD_IN_STEP_8=True`.
- Live cook: blocked (external — UE4.26 source checkout + Linux Docker + operator; see §4.3).

Expected resources (inferred from profile + host + evidence — NOT fabricated from absent live run):
- RAM (process): ~8–16 GB under `LAPTOP_BALANCED` (48 GB host; safe margin; light load at step 8 prevents full-map spike).
- VRAM: 6 GB cap; first stable below-cap = `PROFILE_LAPTOP` with `LOW_MEMORY_PROFILE_ACTIVE=True`, uniform camera settings, streaming on (`TILE_STREAM_RADIUS=2`, `UNLOAD_RANGE_M=400`), NPC cap reduced, no full-viewport dense-traffic sync. **Not measured live at 6 GB with this specific cooked map** — requires live server after cook; currently blocked.
- Disk (intermediate / cooked / package): ~1.5 GB raw XODR + ~6 MB derived tile + package overhead; within available H: / C: (C: ~1.65 GB free — careful; use H: for output).
- Capture throughput: not measurable (no live server); profile expects stable capture within 6 GB at configured resolution / sensor_tick / fixed delta.

Settings forbidden for perception experiments (must remain identical AUTO / MANUAL; must stay at required minimum):
- Resolution, `sensor_tick`, simulation fixed delta, `FOV_DEGREES`, `VIS_RANGE_M` (if below experiment-defined minimum), `UP_RELEASE_PROFILE` changes that alter capture, any `LOW_MEMORY_PROFILE` setting that changes camera/sensor (only scale/density allowed).
- Any reduction in `VIS_RANGE_M` / `FOV_DEGREES` / resolution / `sensor_tick` must be documented, applied identically to both arms, and justified by scientific need — not by runtime convenience.

Final verdict: **LOW_RESOURCE_PIPELINE_PARTIAL / BLOCKED (external blocker)**
Reason (evidence-backed, not speculative):
- Offline structural pipeline ready: tile extraction, adjacency, metadata freeze, QA structural pass (10/10 tests), byte-deterministic rebuild, no dangling links. Pipeline stages 0–10 code present; profile settings defined.
- Live cook execution blocked on external dependencies (`C16` operator + Linux Docker source build + independent structural review of C55V01a `ff2a05e7` + AG07 gate). Not a code defect; not fixable by raising tolerance (GAP-026 policy holds: structural seam defects require repair, not parameter relaxation).
- VRAM / capture stability below 6 GB cap: profile defined (`LAPTOP_BALANCED`, uniform settings); not fully measured live in this session (cook blocked; server not started for full sweep). Existing evidence (`post_audit_hardening`) already shows full-grid + sync + dense traffic wedges — confirming risk, not hiding it.
- No claim of `LOW_RESOURCE_PIPELINE_READY`; no claim of `PRODUCTION_READY`; claim stays at evidence level: offline structural pass = PASS; live cook + VRAM sweep = BLOCKED_EXTERNAL.

No frozen contract edited; no metric/threshold changed; no RQ renumbered; RQ3/RQ5 claim unchanged (still `NOT_RUN` / `BOUNDED` per frozen contract; this audit does not alter claims — only measures pipeline readiness).

---

document_version: 1.0
candidate_sha: 361958ca2a37188269c1d693fe8b14ab993d1789
host: Windows 11 / 48 GB RAM / Quadro P3200 Max-Q 6 GB VRAM
workdir: H:\opencode\rq12-closure (research branch `research/rq1-rq2-evidence-closure-20261020`)
RQ1 campaign: detached driver PID 24348 (attempt 4, fresh base `rq1b_runs4_20261021`, timeout 28800 s); background; not polled per harness rule.
RQ2 evidence: `RQ2_EVIDENCE_RECEIPT.json` / `RQ2_CURRENT_VALIDATION.json` at `361958ca`; `changed_values: 0`; `frozen_oracle_check: PASS`; `final_status: BOUNDED`; receipt SHA256 `1EEA5C45…A89DEB`; validation `716D7132…292AC`.
