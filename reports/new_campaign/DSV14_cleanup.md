# DSV14 — Doc Cleanup (AG04 CRS tag + carla_osm2odr_version re-sourcing attempt)

**Model:** DeepSeek V4 Light · **Mode:** BOUNDED WRITE (AG04_coordinate_contract.md + reports) · **Task ID:** DSV14-CLEANUP
**Branch:** `integration/governed-map-quality-20260729` · **Base SHA:** `f6448fc76e82edb6ec6a059f1ed4211c3cbe16fe`
**Writer lock:** `DSV14-CLEANUP` (acquired via canonical `WriterLock.acquire`; released after push)
**Verdict:** `CLEANUP_APPLIED`

## 1. AG04 row 2 — "Projected CRS UNKNOWN" tagged RESOLVED

`reports/architecture_gate/AG04_coordinate_contract.md` row 2 now carries the tag:
`**[07-31 #2: RESOLVED — EPSG:32632 (tmerc 9E) read from pinned XODR ff2a05e7]**`
(flagged as the one remaining staleness line in the DSV11 report; this closes it.)

## 2. carla_osm2odr_version — re-sourcing attempt (NOT found; stays UNKNOWN_UNSOURCED)

Re-attempted at the conversion donor root (`carla_main_governed\work\codex-full-pipeline-rerun-20260427`):

| Source looked for | Result |
|---|---|
| `PythonAPI/carla/dist/*.egg` or `*.whl` | ❌ no PythonAPI/dist dir in donor |
| `LibCarla/source/carla/Version.h` | ❌ not present |
| `*.dist-info` for installed `carla` package | ❌ none (no venv/site-packages markers either) |
| `carla_client.log` (2 diagnostics runs) | ❌ no version string |
| `carla_load_probe.json` / `CARLA_PROBE_*.txt` | ❌ no version field |
| wheel/egg name anywhere in donor | ❌ none |

**Conclusion:** no provenance-verifiable version string exists in the conversion environment → the manifests keep `carla_osm2odr_version: UNKNOWN_UNSOURCED` (both files untouched, per "else leave UNKNOWN_UNSOURCED").

**Where the version WOULD come from (note for the next runtime session):**
1. `carla.__version__` or `client.get_server_version()` against the actual conversion-time server — the authoritative source. (DSV13 Step 6b of the runbook now prints `get_server_version()` as a standard smoke-test pin, which will populate this field.)
2. The PythonAPI wheel filename of the source build: `carla-0.9.16-cp38-linux_x86_64.whl` (ground truth once the B4 build exists).
3. Plausible-but-unproven: the host's packaged runtime `E:\CARLA\CARLA_0.9.16` ships `carla-0.9.16-cp312…whl` — same 0.9.16 line, but not proven to be the environment used at conversion time, so it was not bound.
