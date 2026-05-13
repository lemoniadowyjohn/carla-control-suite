# CARLA Fatal Error (EXCEPTION_ACCESS_VIOLATION in `Map::GenerateChunkedMesh`) — Test & Documentation Runbook

This runbook is designed for your thesis pipeline: it turns a **CARLA crash on map load** into a **documented, reproducible, preflight-tested outcome**.

Crash signature you saw (typical when CARLA fails while generating road mesh from OpenDRIVE):

- `carla::road::Map::GenerateChunkedMesh()`
- `AOpenDriveGenerator::GenerateRoadMesh()`
- `AOpenDriveGenerator::BeginPlay()`

That means: **the OpenDRIVE content was accepted far enough to start mesh generation**, but CARLA hit a fatal geometry/topology condition (or a null pointer due to invalid internal assumptions).

---

## 1) What to capture every time (minimum thesis-grade provenance)

For each failing XODR/map import, capture:

- **Input XODR path**
- **SHA256** of the input XODR
- Pipeline **settings snapshot** (or `run_manifest.json`)
- The **exact CARLA version** and build (`0.9.16`, shipping exe path)
- The crash stack trace text (copy/paste)
- The output of your **XODR preflight gates** (see below)
- If applicable: the output of **SUMO repair / hardener** stages and the chosen “final xodr”

### One-liner: hash the XODR (PowerShell)

```powershell
Get-FileHash .\path\to\map.xodr -Algorithm SHA256 | Format-List
```

---

## 2) Fast “Preflight Gates” before loading into CARLA

Goal: **fail fast** in Python with a human-readable error report **instead of** a CARLA crash.

You already have a growing set of “quality” tests that are intentionally **skipped** unless enabled:

- `UP_RUN_XODR_PREFLIGHT_TESTS=1`
- `UP_TEST_XODR_PATH=...`

### Run ALL preflight tests against one XODR

```powershell
$env:UP_RUN_XODR_PREFLIGHT_TESTS="1"
$env:UP_TEST_XODR_PATH="C:\path\to\candidate.xodr"
pytest -q ultimate_pipeline\tests\quality
```

Expected behavior:
- If the XODR violates known crash patterns: tests **FAIL** with a precise reason.
- If you don’t set env vars: tests **SKIP** (safe default for CI).

### Recommended: store preflight outputs next to the XODR

Add this before CARLA import in your pipeline (or run manually):

```powershell
$env:UP_RUN_XODR_PREFLIGHT_TESTS="1"
$env:UP_TEST_XODR_PATH="C:\path\to\candidate.xodr"
pytest -q ultimate_pipeline\tests\quality | Tee-Object -FilePath ".\preflight_report.txt"
```

---

## 3) Known CARLA crash triggers (what your gates should detect)

These are common OpenDRIVE patterns that frequently crash/soft-lock CARLA mesh generation:

### Geometry / PlanView issues
- `paramPoly3` coefficients with extreme curvature spikes (rapid heading changes)
- Zero-length geometry segments
- Very short segments with large curvature (numerically unstable)
- Discontinuous planView chains (gaps/jumps)

### Lane topology issues
- Missing lane successors/predecessors
- Lanes changing ID unexpectedly without proper `laneLink`
- Lane width becoming negative or exploding
- `laneOffset` with unrealistic derivatives (especially in/near junctions)

### RoadMark issues (a *classic* CARLA crash vector)
- Degenerate roadMark `line` elements (e.g., zero-length segments, NaNs)
- RoadMark types not supported / malformed attributes

### Elevation issues
- Elevation profile discontinuities (big z-jumps)
- Unrealistic slope spikes across short `s` distances

### Junction / roundabout issues
- Junctions with inconsistent connectivity
- Roundabout centerline geometry with “self-crossing”
- Entry/exit links missing or contradictory

Your test suite should convert these into:
- **FAIL** (fatal pattern detected)
- **SKIP** (preflight disabled)
- **PASS** (no known fatal pattern detected)

---

## 4) Minimal Repro: isolate CARLA import from everything else

When CARLA crashes, you want to know it’s **the map**, not sensors, traffic manager, etc.

### A) Use a map-only probe (no sensors, no recording)

If you have a probe script (common names in your repo):
- `ultimate_pipeline/tools/carla_probe.py`
- `ultimate_pipeline/tools/probe_carla.py`
- `ultimate_pipeline/core/carla_preflight.py`

Run it with ONLY the XODR (or town) and a short timeout.

Example shape (adjust to your tool’s CLI):

```powershell
python -m ultimate_pipeline.tools.probe_carla --xodr "C:\path\to\candidate.xodr" --timeout_s 60
```

If you don’t have a stable probe entrypoint yet, create one with these requirements:
- Imports CARLA only inside `main()`
- Loads map (xodr) and exits after world tick
- Writes `probe_result.json` (success/failure + exception text)

### B) Disable traffic manager and autopilot in repro
TrafficManager often hides root causes. For map load debugging:
- Don’t spawn traffic
- Don’t enable autopilot
- Don’t run synchronous fixed-delta unless needed

---

## 5) “Binary search” where the XODR becomes toxic (pipeline stage bisect)

If your pipeline produces intermediate artifacts (raw xodr → repaired xodr → hardened xodr → tiled xodr), you can bisect:

1. Test **raw** output from OSM conversion
2. Test after **SUMO repair** (if used)
3. Test after **xodr_carla_hardener**
4. Test after **tiling/stitching**
5. Test after **elevation injection**
6. Test after **roundabout reconstruction**

For each stage artifact:
- Run **preflight gates**
- Run **map-only CARLA probe**
- Record pass/fail in a table

This gives you a thesis-grade statement:
> “CARLA crash appears only after Stage X (elevation), while Stage X−1 loads reliably.”

---

## 6) Recommended documentation structure for your thesis

Create a section in “Methods / Quality Gates”:

### A) Failure is data
- Treat “CARLA crash on import” as a measurable failure mode
- Log as an outcome (not “noise”)

### B) Preflight rules
- List your gate categories: geometry, topology, road marks, elevation, roundabouts
- Explain why they reduce invalid evaluation runs

### C) Reproducibility
- Hashes + manifest snapshots
- Deterministic seeds
- Versioned toolchain

### D) Validation matrix
A simple matrix per map:

| Map ID | Stage | Preflight (Y/N) | CARLA Import (Y/N) | Notes |
|---|---|---:|---:|---|

---

## 7) Where to wire variables/settings (practical guidance)

You asked: *“where to add the variables… settings for last run or main_pipeline before loading map?”*

Recommended approach (clean + reproducible):

### Option 1 (best): **Settings + manifest**
- Add environment variables controlling preflight gates:
  - `UP_RUN_XODR_PREFLIGHT_TESTS`
  - `UP_TEST_XODR_PATH`
- When running `main_pipeline` or batch experiments:
  - set env vars
  - write them into `run_manifest.json` for traceability

### Option 2: call preflight gates from `main_pipeline` automatically
Before CARLA import (or before writing final xodr):
- If `SETTINGS.ENABLE_PREFLIGHT_GATES` is true:
  - run the Python preflight checks on the candidate xodr
  - abort early with a report if a fatal pattern is found

This is the “industrial” solution: **pipeline refuses to generate broken CARLA runs**.

---

## 8) A clean “Actions” checklist for every new generated map

1. Generate candidate `.xodr`
2. Compute SHA256 and store it
3. Run `pytest ultimate_pipeline/tests/quality` with env vars set
4. If FAIL:
   - Save `preflight_report.txt`
   - Mark map as “blocked” and don’t import into CARLA
5. If PASS:
   - Run CARLA map-only probe (60s)
6. If CARLA crashes:
   - Save stack trace
   - Attach preflight report
   - Add to your “crash corpus” (a folder of known-bad xodrs)
7. If CARLA loads:
   - proceed to perception recording / domain-gap metrics

---

## 9) Suggested filenames for a thesis-friendly crash corpus

Create:

- `crash_corpus/`
  - `bad_001_<sha256_prefix>/`
    - `map.xodr`
    - `preflight_report.txt`
    - `stacktrace.txt`
    - `run_manifest.json`
    - `notes.md`

This becomes gold for your thesis defense.

---

## 10) Appendix: quick “enable markers” fix (Pytest warning cleanup)

You saw warnings:

> `PytestUnknownMarkWarning: Unknown pytest.mark.quality`

Register the custom mark in `pytest.ini`:

```ini
[pytest]
markers =
    quality: slow/offline quality gate tests (enabled via UP_RUN_XODR_PREFLIGHT_TESTS)
```

This removes noise and makes your test suite look professional.

---

## TL;DR (the pointy end of the spear)

- Don’t try to “handle” `EXCEPTION_ACCESS_VIOLATION` in CARLA — you can’t.
- Instead: **preflight gates** + **map-only probe** + **manifest logging**.
- You get scientific value: failure becomes a tracked, reproducible datum.

