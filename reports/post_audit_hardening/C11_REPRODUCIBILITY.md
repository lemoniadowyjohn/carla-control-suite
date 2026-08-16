# C11 (HIGH) — Reproducibility & governance

Branch: `fix/c11-reproducibility` (rooted at `eb5ddc71`)
Interp: `./.venv/Scripts/python.exe` (this repo's pinned `carla_-main/.venv`) · `UP_DISABLE_CARLA=1`

**SCOPE FOR THIS ROUND**: only spec steps **1, 2, 3, 5**. Step 4 (canonical
`scripts/regen_map_of_record.py` entrypoint) is explicitly **DEFERRED** to a
follow-up once C6/C7/C8/C9/C10 have all landed and it can encode the fully
corrected pipeline. The "Phase-0 dependency" (`sumo_repair.py` CRS conflict,
commit `1be9b767`) was verified already resolved before this work started —
`git status --short ultimate_pipeline/topology/sumo_repair.py` is clean
throughout; no reconciliation was needed or attempted.

## Verdict

```
REPRODUCIBLE_PARTIAL inputs_pinned=roads+dem,buildings_pending_C7 default_run=OK canonical_cmd=DEFERRED
```

## Summary of what changed

| Step | Problem | Fix |
|---|---|---|
| 1 | Default pipeline run crashed with `ImportError` before stage 01 (`Settings.PREANCHOR_INPUT_XODR` defaulted `True`, importing the absent `tools/preanchor_xodr.py`) | Flipped default to `False` (option **b**) |
| 2 | DEM and building-source inputs not digest-pinned; no fail-closed guard | Added `campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json` (roads + DEM pinned, buildings documented `pending`) + `ultimate_pipeline/governance/inputs_manifest.py` fail-closed verifier |
| 3 | `_write_crs_comparability` raised under `THESIS_STRICT` whenever no manual map was present, coupling Phase-1 generation to the Phase-2 comparison input | New `Settings.REQUIRE_MANUAL_FOR_CRS` flag (default `False`); without it, writes `crs_comparability.json` with `"status": "manual_deferred"` instead of raising |
| 5 | `proj.db` too old for CRS transforms in this repo's own pinned venv (`DATABASE.LAYOUT.VERSION.MINOR=4`, expected ≥6) — confirmed live, plus a stray `PROJ_LIB` env var pointing at a *different* venv's PROJ install | New `ultimate_pipeline/governance/proj_env_guard.py` startup check, wired into `_validate_global_safety_settings()`; loud-warns by default, opt-in fail-closed via `UP_PROJ_ENV_FAIL_CLOSED=1` |

## Step 1 — preanchor default

**Chosen: option (b) — default `PREANCHOR_INPUT_XODR` to `False`.**

Rationale (per spec's own framing, verified against the code):
- `tools/preanchor_xodr.py` does not exist anywhere in the repo (only
  `tools/verify_candidate_digest.py` is present in `tools/`). With the old
  default (`True`), any run that reaches
  `MainPipeline._maybe_preanchor_input_xodr()` with GPS bounds available
  hits `from tools.preanchor_xodr import preanchor_xodr as _preanchor_xodr`
  (main_pipeline.py) and dies with `ModuleNotFoundError` before stage 01.
  This is called directly from `MainPipeline.run()` prior to the sanitize
  stage, so it blocks every default run, not just an edge case.
- Preanchoring re-frames the input off the Osm2Odr `tmerc(0,0)` frame that
  the DEM contract needs; no known working run in this repo actually used
  it, and `MainPipeline.__init__`'s own inline comment already claimed
  preanchoring provenance defaults "OFF" — the dataclass default
  contradicted that claim.
- Explicit opt-in remains available and functional: `UP_PREANCHOR_INPUT_XODR=1`
  still reaches the real import and (correctly) fails loudly if the module
  is genuinely absent, or proceeds if it's restored later (option a).

Changed both duplicate `PREANCHOR_INPUT_XODR: bool = _env_bool(...)` field
declarations inside the single `Settings` dataclass body
(`ultimate_pipeline/config/settings.py`, ~line 708 and ~line 2067 pre-edit;
the second one is what wins as the actual dataclass default) plus the
`__post_init__` env-refresh line, all now defaulting `False`.

**Live verification** (not just unit test): constructing `MainPipeline()`
directly under `UP_DISABLE_CARLA=1` with no other env now succeeds and
reports `preanchor manifest: {'applied': False}` — previously this
construction path would eventually crash via `run()`.

Tests: `ultimate_pipeline/tests/unit/test_c11_preanchor_default.py` (5 tests) —
dataclass default assertion, `Settings()`/`SETTINGS` singleton checks, a
direct call to `_maybe_preanchor_input_xodr` proving no import of the
missing module occurs by default, and a positive control proving the
opt-in path is still live (raises `RuntimeError`/`ImportError` as expected
when explicitly enabled, rather than being silently disabled).

## Step 2 — pin generation inputs by digest

`campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json`
(new file; schema documented in the module docstring of
`ultimate_pipeline/governance/inputs_manifest.py`):

| key | status | sha256 | bytes |
|---|---|---|---|
| `roads_osm` | pinned | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` | 11,154,738 |
| `dem` | pinned | `3cfa665dde3782a015502beaf457854db2f639d01008a386c925d171e41f4ff8` | 1,711,684 |
| `buildings` | **pending** | `null` | `null` |

- `roads_osm` sha256 matches the pre-existing
  `campaigns/ingolstadt_cooked_perception_v1/source/manifest.json` pin
  (`b9e07465...`) — verified by recomputing the digest against the file on
  disk in this worktree; unchanged, just re-referenced under the new
  schema.
- `dem` (`cities/ingolstadt/dem/dem_ing.tif`, the file
  `Settings.DEM_TIF == DEM_DIR/DEM_FILENAME` resolves to) is pinned for the
  first time as part of this fix. Computed directly:
  `sha256sum`-equivalent streaming hash, 1,711,684 bytes.
- `buildings` is deliberately left `status: "pending"`, `path`/`sha256`/`bytes`
  all `null`, with a `note` explaining C7 hasn't landed. **No digest was
  fabricated.** The schema needs no change once C7 lands — populate the
  three fields and flip `status` to `"pinned"`.

**Fail-closed guard**: `ultimate_pipeline/governance/inputs_manifest.py` —
`verify_inputs_manifest(manifest_path, base_dir=...)` raises
`InputsManifestMismatchError` (a build-time ABORT) if any `pinned` entry is
missing on disk, or its byte size or sha256 no longer matches the manifest.
`pending` entries are reported but never digest-checked and never block
verification. Malformed manifests (bad/missing `status`, missing
path/sha256/bytes on a `pinned` entry) raise the base `InputsManifestError`.

Tests: `ultimate_pipeline/tests/unit/test_c11_inputs_manifest_guard.py`
(7 tests) — digest computation correctness, pass-on-match, fail-closed on
tamper (mismatch), fail-closed on missing file, pending entries skipped and
reported separately, manifest load roundtrip, and an integration-flavored
test that runs `verify_inputs_manifest` against the **real, committed**
`INPUTS_MANIFEST.json` and the real repo files (`roads_osm` + `dem` verify;
`buildings` confirmed `pending` with no fabricated digest).

## Step 3 — decouple generation from the manual map

`MainPipeline._write_crs_comparability()` (`ultimate_pipeline/main_pipeline.py`)
previously raised `RuntimeError` whenever `THESIS_STRICT` was set and no
manual reference XODR was present — even though this method runs during
ordinary Phase-1 auto-map generation (stage 02), not the Phase-2
manual-vs-auto comparison step.

Fix:
- New `Settings.REQUIRE_MANUAL_FOR_CRS: bool` (default `False`, env override
  `UP_REQUIRE_MANUAL_FOR_CRS`), declared alongside `THESIS_STRICT` and given
  the same `__post_init__` env-refresh treatment for consistency.
- `_write_crs_comparability` now only raises when **both** `THESIS_STRICT`
  (or `UP_THESIS_STRICT`) **and** `REQUIRE_MANUAL_FOR_CRS` (or
  `UP_REQUIRE_MANUAL_FOR_CRS`) are set and no manual map is present.
- Otherwise, when strict-but-no-manual-and-not-required, it writes
  `crs_comparability.json` with a new top-level `"status": "manual_deferred"`
  field (all other existing fields — `manual.present=False`, `auto`,
  `offsets`, `policy`, `comparability`, `georef_action`/`reason` — unchanged,
  so existing best-effort consumers like the audit-summary reader at
  `MainPipeline._write_audit_summary` are unaffected). Non-strict runs keep
  writing `"status": "ok"`.

Note: `ultimate_pipeline/quality/xodr_strict_validator.py::thesis_strict_checks`
has its own, separate `manual.present` gate for a downstream strict
certification pass. It is currently uncalled anywhere in the codebase and is
a distinct, deliberately-invokable strict gate rather than part of the
generation crash path this step fixes — left untouched per the "do not
re-open C6–C10 concerns" boundary and because the spec scoped this step to
`_write_crs_comparability` specifically.

Tests: `ultimate_pipeline/tests/unit/test_c11_crs_comparability_decoupled.py`
(5 tests) — default flag value, strict+no-manual+default→no raise (produces
`manual_deferred`), strict+no-manual+`REQUIRE_MANUAL_FOR_CRS=True`→raises,
strict+no-manual+env override `UP_REQUIRE_MANUAL_FOR_CRS=1`→raises even when
the settings attribute says `False`, and non-strict+no-manual unaffected
(pre-existing behavior preserved).

## Step 5 — PROJ environment guard

New `ultimate_pipeline/governance/proj_env_guard.py`:
`check_proj_environment(min_layout_minor=6, fail_closed=False)` returns a
`ProjEnvironmentReport` (`ok`, `data_dir`, `proj_db_path`,
`proj_db_layout_version`, `pyproj_version`, `warnings`). Two independent
risks are checked:

1. **Old proj.db layout.** Reads `DATABASE.LAYOUT.VERSION.MINOR` directly
   from `proj.db`'s own `metadata` table (read-only sqlite connection) at
   the data dir pyproj itself resolves (`pyproj.datadir.get_data_dir()`).
2. **Foreign `PROJ_LIB`/`PROJ_DATA`.** If either env var is set and does not
   resolve to the same path as pyproj's own data dir, a warning is raised —
   this is the "from another PROJ installation" risk: some other
   PROJ-consuming component in the same process/environment (a different
   venv's GDAL, a raw libproj binding, etc.) could load a different,
   unvetted `proj.db`.

**Confirmed live in this repo's own pinned venv** (not hypothetical):

```json
{
  "ok": false,
  "data_dir": "...\\carla_-main\\.venv\\Lib\\site-packages\\pyproj\\proj_dir\\share\\proj",
  "proj_db_layout_version": 4.0,
  "pyproj_version": "3.7.2",
  "warnings": [
    "proj.db DATABASE.LAYOUT.VERSION.MINOR=4 ... older than the required minimum (6) ...",
    "PROJ_LIB='...\\pythonProject3\\.venv\\Lib\\site-packages\\pyproj\\proj_dir\\share\\proj' does not match pyproj's own resolved data dir ('...\\carla_-main\\.venv\\...')..."
  ]
}
```

The `PROJ_LIB` env var in this shell environment points at a **sibling
venv** (`pythonProject3/.venv`, not `pythonProject3/carla_-main/.venv` —
the one actually running the interpreter). pyproj happens to ignore it and
resolve its own bundled data dir correctly in this case, but any other
PROJ-consuming library that honors `PROJ_LIB` would not.

**Wiring**: `_check_proj_environment_startup()` is called from
`MainPipeline._validate_global_safety_settings()`, which already runs on
every `MainPipeline.__init__()`. Default behavior is a **loud warning**
(`print("⚠️ [PROJ-ENV] ...")` for each warning), not fail-closed — chosen
because this repo's own pinned venv is *currently* below the recommended
minimum, so a fail-closed default would block every run today. Set
`UP_PROJ_ENV_FAIL_CLOSED=1` to make this hard-fail (`ProjEnvironmentError`)
once the environment has been repaired; recommended for CI/release profiles
after remediation.

**Operator remediation** (not performed by this change — a documented
manual step):
- Refresh pyproj's bundled `proj.db`: reinstall pyproj in this venv, e.g.
  `pip install --force-reinstall --no-cache-dir pyproj` (or upgrade to a
  pyproj/PROJ release whose bundled `proj-data` reports
  `DATABASE.LAYOUT.VERSION.MINOR >= 6`).
- Do not mix a system-wide PROJ install with pyproj's bundled one; if GDAL
  is used anywhere in this environment, ensure it is built/configured
  against the *same* proj.db pyproj resolves (not a separately installed
  system PROJ).
- Unset the stray `PROJ_LIB` env var in this shell profile, or repoint it at
  pyproj's own resolved data dir, so it can't silently redirect some other
  PROJ-consuming component to an unvetted database.

Tests: `ultimate_pipeline/tests/unit/test_c11_proj_env_guard.py` (7 tests) —
report shape, old-layout-version correctly flags `ok=False` with an
actionable warning (assertion is conditional on the live reading, so it
stays meaningful if/when the venv is repaired), fail-closed raises
`ProjEnvironmentError` when not ok, a trivially-low threshold always passes,
foreign `PROJ_LIB` detection via a synthetic tmp_path, and two
`MainPipeline`-level integration tests proving the startup wiring never
blocks a default run but does raise under `UP_PROJ_ENV_FAIL_CLOSED=1` when
the environment is genuinely not ok.

## Step 4 (canonical entrypoint) — explicitly DEFERRED

Not attempted this round per the scope reduction. `scripts/regen_map_of_record.py`
must land after C6 (geometric continuity), C7 (buildings), C8 (perception
dataset), C9 (gate-checker correctness — already merged into this branch's
base at `eb5ddc71`), and C10 (map hygiene) have all merged, so it encodes the
fully-corrected pipeline rather than baking in stale assumptions. This
report's fixes (preanchor default, pinned roads+DEM, decoupled CRS gate,
PROJ guard) are all still directly consumed by whatever `regen_map_of_record.py`
eventually orchestrates — none of this work needs to be redone.

## Boundaries respected

- Did not re-open C6–C10 concerns; `xodr_strict_validator.py`'s separate
  strict-mode CRS gate was identified and deliberately left alone (see
  Step 3 note above).
- Did not touch `ultimate_pipeline/run_full_domain_gap.py`'s own, separate
  `_write_crs_comparability`/`_build_crs_comparability_report` functions —
  out of scope; the spec named `main_pipeline.py`'s method specifically.
- No network fetch performed at build time; the DEM digest was computed
  against the file already committed in this worktree
  (`cities/ingolstadt/dem/dem_ing.tif`). Buildings fetch/pin remains a
  future, C7-dependent operator step.
- `ultimate_pipeline/topology/sumo_repair.py` verified clean
  (`git status --short`) before and after this work — no Phase-0
  reconciliation was needed.

## Full-suite result

```
UP_DISABLE_CARLA=1 ./.venv/Scripts/python.exe -m pytest -q
```

**822 passed, 1 skipped, 0 failed** (baseline before this change: 798
passed, 1 skipped — the +24 are this fix's new tests: 5 + 7 + 5 + 7 across
the four new test modules; the pre-existing 1 skip is unrelated/unchanged).

## Files changed

- `ultimate_pipeline/config/settings.py` — `PREANCHOR_INPUT_XODR` default
  `True`→`False` (both dataclass field declarations + `__post_init__`
  refresh); new `REQUIRE_MANUAL_FOR_CRS` field + `__post_init__` refresh.
- `ultimate_pipeline/main_pipeline.py` — `_write_crs_comparability` gate
  decoupling + `"status"` field; new `_check_proj_environment_startup()`
  wired into `_validate_global_safety_settings()`.
- `ultimate_pipeline/governance/__init__.py` (new)
- `ultimate_pipeline/governance/inputs_manifest.py` (new)
- `ultimate_pipeline/governance/proj_env_guard.py` (new)
- `campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json` (new)
- `ultimate_pipeline/tests/unit/test_c11_preanchor_default.py` (new)
- `ultimate_pipeline/tests/unit/test_c11_inputs_manifest_guard.py` (new)
- `ultimate_pipeline/tests/unit/test_c11_crs_comparability_decoupled.py` (new)
- `ultimate_pipeline/tests/unit/test_c11_proj_env_guard.py` (new)
- `reports/post_audit_hardening/C11_REPRODUCIBILITY.md` (this file, new)
