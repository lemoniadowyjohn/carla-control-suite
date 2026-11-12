# CARLA Ops Studio — Control Center v3 preview

This package is a **modified v2 application source release**. It preserves the previous 17 screen routes and the complete source/technical-evidence pages, adding a dashboard-and-workspace layer. It is **not** a live CARLA production certification or a complete 116-control implementation.

## Start on Windows

Extract the ZIP to a separate directory (do not overwrite the verified v2 release). Run from the directory containing `pyproject.toml`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[gui]'
.\.venv\Scripts\python.exe -m ultimate_pipeline.gui.cli
```

Optional elevation raster previews:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[gui-maps]'
```

Where the local CARLA 0.9.16 SDK is absent, mock mode works without it. The real server probe will explicitly report `ModuleNotFoundError` rather than simulate a connection.

## Workspace tour

- **Dashboard** — status, G5–G8 blockers, fast navigation, control coverage.
- **Connection** — enter host/port and explicitly request a *read-only* CARLA RPC probe. Success reports observed server version and map name; this does not satisfy cook provenance or tick authority.
- **Environment Profiles** — search the 318 declaration rows, stage typed values, validate and save/load versioned local profiles. Nothing is applied to a simulator.
- **World/Time, Traffic Manager, Actors, Sensors, Calibration** — tabbed proposal forms. Export explicit `REQUESTED_NOT_APPLIED` JSON drafts. The numeric input constraints are UI guardrails, *not verified CARLA acceptance thresholds*. TM setters are WRITE_ONLY, so no confirmed values are claimed.
- **Maps / GIS / Cooking** — choose or scan `.xodr`, `.osm`, `.tif` or `.tiff`; inspect a local file on demand. OpenDRIVE line/arc preview and road elevation z(s) graph; GeoTIFF shows a downsampled elevation heatmap (if rasterio is installed). These are previews, not a world load, authoritative map acceptance or known vertical datum. Large XML inputs are capped at 256 MiB, parsed with defusedxml and DOCTYPE blocked. Geometry sample count is bounded.
- **Sensors and cameras** — 2x2 camera grid: offline placeholders, local image-folder playback, externally published frames through `FrameIngress`, or optional user-entered external HTTP(S) MJPEG stream. An external MJPEG image is **not** proof of CARLA sensor identity, frame ID or simulator timestamp. No sensor actor is spawned or tapped automatically.
- **Scenario Studio / Experiments** — create an experiment plan with deterministic seed, hypothesis, map path and notes. Plans save/load as strict versioned JSON; all retain `PLAN_ONLY_NOT_EXECUTED`. Available categories include road grade/elevation, junction geometry, camera calibration, timestamp sync, route/traffic and perception.
- **Operational Fuzzer** — inspect real registered mutator contracts and generate seeded cases, never run live campaigns from this preview. Use the original backend and source-backed Technical Evidence tab for oracle/replay/corpus evidence.
- **Technical Evidence** tab — the original v2 status views remain accessible on every route, including deferred Perception/Localization.

## Critical runtime limitations

- G5 map cook remains blocked, G6 runtime identity unbound, G7 cooked content unverified, G8 tick authority unresolved.
- Q9/Q12/Q22 ownership and policy decisions are outstanding.
- No feature in this preview starts CARLA/Unreal, cooks maps, spawns actors, applies Traffic Manager changes, takes a tick lock, or performs live fuzzing.
- Local files, MJPEG streams and RPC readback are **different evidence classes**; none is presented as automatically verified simulator ground truth.
- Most originally deferred controls remain deferred. This update makes the operator workflows and offline tools useful without changing the underlying safety contracts.

## Verification scope

The added pure-Python map and experiment-plan regression tests were executed. Python syntax compilation of new Qt modules was checked. **An actual PyQt6 renderer is not available in the build environment**, so the new GUI must be visually smoke-tested and the original 381-test suite rerun in your Windows PyQt6 environment before marking v3 offline-release-verified. v2 receipts bundled in this ZIP refer to v2 only.
