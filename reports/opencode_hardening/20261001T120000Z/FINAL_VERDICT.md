# FINAL VERDICT: INTEGRATION_OFFLINE_PASS_LIVE_BLOCKED

**Repository:** `lemoniadowyjohn/carla-control-suite`
**Authoritative branch:** `integration/production-large-map-20260918` @ `f897e0eb747ac827941ac4883170a5181a603111` (verified, no drift)
**Work branch:** `integration/opencode-runtime-rig-environment-closure-20261001`
**Result head:** `5bac4c9188268d9247bb4898c040b14cbaeb0d48` (code changes at `7b09cfbc`)
**Not merged into the authoritative branch.** Left for independent review.

## Map pin

`auto_map_of_record` resolved through
`ultimate_pipeline.carla_tools.map_registry.verify_pinned_map` against the real
LFS object: SHA256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`,
149,799,632 bytes, frame `ingolstadt_local_rebased`. **VERIFIED.**

## Candidate refs

All three heads matched their expected SHAs and all three share merge-base
`f897e0eb` with the baseline, ahead 1 / behind 0. No `BASELINE_DRIFT`, no
`CANDIDATE_REF_DRIFT`, no `MAP_AUTHORITY_DRIFT`.

| Candidate | Head | Merged |
| --- | --- | --- |
| A `new293-301-route-rig` | `f5668a9e` | yes, `08f7bfa1` |
| B `new316-333-perception-environment` | `278968f9` | yes, `cee72f42` |
| C `new225-233-gap040-048` | `f3a996f7` | **no** |

Candidate C shares **zero** files with A or B. Its entire diff is the
GAP-040..048 register plus NEW-200..233 domain-gap test suites and evidence —
no runtime, rig, capture-authority, weather, TM, calibration or provenance
code. Merging it would import unrelated domain-gap policy and seven out-of-scope
test modules. No complementary capture/provenance fix was found missing from the
merged tree, so it was audited and left out.

## The merge was clean. That was not the evidence.

Text-level merge produced **zero conflicts** across the two shared files. Reading
the merged result instead surfaced three semantic defects that no conflict
marker would have shown — two of them inside Candidate A's own code:

1. **`route_frame_binding.py` could never prove a shared frame.** It compared the
   manifest's declared CRS against the map's normalized PROJ.4 string, and an
   EPSG code never equals a PROJ string. So `both_maps_share_exact_frame` was
   structurally always `False`, and a manifest declaring `EPSG:32633` while
   carrying UTM-zone-32 parameters was accepted as valid. Now resolved to
   canonical EPSG via `canonical_crs_identity()` (lazy pyproj), fail-closed on
   anything unresolvable.
2. **An inactive calibration entry aborted the entire rig.** Candidate A added
   the canonical-active-LiDAR check inside the spawn loop but never applied it to
   the spawn set, so `middle_lidar_old` reached the loop and tripped A's own
   `RuntimeError`. A historical leftover made the governed rig impossible to
   create.
3. **NEW-299's rig identity did not exist.** `canonical_lidar_hash` was imported
   into `thesis_sensor_rig.py` and never used. Added
   `runtime_rig_identity()` over the actually spawned sensors' effective
   attributes.

Plus four more found by audit: `attach_sensors_safe` passed an undefined name to
`resolve_active_lidars` (`load_calib` returns `cams, lids`) and treated a missing
required LiDAR as non-fatal; `sensors/rig_transforms.py` read `calib_data.json`
from the cwd and self-imported at module scope, making the sensors package
non-import-safe and competing with `transform_conventions` (relocated to
`tools/rig_transforms_check.py`; zero production importers, so no shim needed);
and both build tools used `next(iter((a, b)), None)`, which probes only the first
candidate name.

## The path-test false positive is confirmed — in the test

`test_no_hardcoded_username_in_production_defaults` asserted the **resolved
runtime value** of `DEFAULT_OSM2WORLD_HOME` does not contain `c:\users\admin`.
The default is correctly repo-relative; the checkout merely lives under
`C:\Users\admin`. Production path resolution was inspected and left **unchanged**.

The test now scans the *source text* of the three defining modules for hardcoded
absolute developer-path literals, and separately asserts each resolved default is
anchored at the repo root — which is what portability actually means. No xfail,
no skip, no tolerance.

## Authority preserved, no duplicates created

Single authority confirmed for: LiDAR spec (`canonical_lidar_spec.py`), route
execution/manifest/frame-binding, weather (`weather_spec.py` +
`deterministic_weather.py`), TM (`traffic_manager_session.py` — with
`fixed_traffic_manager.py` confirmed to be a delegating facade, not a second
wrapper), seed tree, calibration authority, camera response. No second LiDAR
spec, weather spec, TM wrapper, seed tree, calibration authority or route engine
was introduced.

## Tests

- `python -m compileall -q ultimate_pipeline tools tests` → exit 0
- Targeted: **179 passed, 0 failed** (A: 13, B: 57+25, integration-specific: 84)
- Full `python -m pytest -q ultimate_pipeline tests tools` → **6958 passed, 0 failed, 10 skipped**

60 new offline tests (40 cross-cutting negative controls, 20 UE4 discovery), 3
repaired. **0 new failures, 0 candidate-specific regressions, 0 tolerances
raised, 0 xfail/skip added.**

Negative controls cover every case in the brief: wrong LiDAR identity, inactive
LiDAR activation, wrong rig hash, wrong calibration hash, wrong route frame,
tampered manifest, different-seed-falsely-equal-identity, same-seed determinism,
TM strict fallback, unbound weather, actor/sensor cleanup misses, double TM
ownership, double tick ownership. Back-to-back runs prove B starts from B's
requested state across seed, weather, physics and TM.

## Live claim boundary preserved

CARLA RPC 2000: TCP timeout, `get_server_version` → `RuntimeError`. TM port 8000:
TCP timeout. The Python client library is installed, which says nothing about a
running simulator.

All 16 live items stay `BLOCKED_EXTERNAL`: weather application/readback, live TM
ownership and seed, ego/calibration binding, effective sensor attribute
readback, empirical camera reprojection, empirical LiDAR-camera alignment,
sensor callback evidence, NEW-296 live route adapter, live repeated capture,
live cleanup, repeat capture comparison, live back-to-back pair.

Port listening was never treated as CARLA success, and no build/cooked/runtime
state is inferred from a file existing — `UE_ENGINE_EDITOR_PRESENT`,
`CARLA_PROJECT_COMPILED`, `CARLA_SERVER_BINARY_PRESENT`, `CARLA_RPC_RESPONSIVE`,
`MAP_PACKAGE_COOKED` and `MAP_RUNTIME_LOADABLE` are independent, with unknown
staying unknown.

**Offline integration: PASS. Overall live runtime: cannot PASS without new live
evidence from a real CARLA server.**

Evidence: `reports/opencode_hardening/20261001T120000Z/`
