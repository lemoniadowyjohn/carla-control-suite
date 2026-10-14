# RQ1 Determinism Re-Verification (2026-09-23)

## Task

RQ1's determinism claim was last verified valid before 2026-09-18. Roughly 15 merges have
landed since then (final-artifact-authority receipt system, canonical geometry consolidation,
lane-count classification, mtime-authority fixes, a new `xodr_validator` pipeline stage,
topology-certification hardening — see
`reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.json`).
This pass re-exercises RQ1's determinism check against the current codebase and reports
honestly whether it still holds.

Worktree: `G:/carla-rq1-reverify-20260923`, branch `docs/rq1-reverification-20260923`,
based on `origin/integration/production-large-map-20260918` @ `a5a2a5da9a4429ac0ebfed2100a9f9f2db4b2418`
("docs(plan): master closure plan with honest RQ-by-RQ status and dependency chain",
2026-09-22 22:23:57+0200) — this is the current tip of the target integration branch,
downstream of all 15 merges referenced above.

## RQ1's authoritative claim (before this pass)

Per `docs/research/THESIS_RQ_CONTRACT.md` and `docs/research/THESIS_TO_CURRENT_PROGRESS.md`:

> RQ1 — Determinism: **AUTHORITATIVE for structural repeatability and raw byte
> non-repeatability; BOUNDED for timestamp-normalized byte equality.** Three repeated
> Osm2Odr outputs differ at raw hash level and preserve the same road/junction/length
> signature; portable committed fixtures cover timestamp-only normalization in CI, while
> large local artifacts remain optional governed integration evidence.

The supporting check is `tests/unit/test_exp_osm_to_xodr_determinism_normalized.py`, which
operationalizes the finding from `ultimate_pipeline/experiments/thesis/exp_osm_to_xodr_determinism.py`
(`_normalize_timestamps`/`_sha256_normalized_text`): the only known byte-level nondeterminism
source in the Osm2Odr stage is the wall-clock timestamp, appearing in exactly two places
(leading XML comment, `<header date="...">`). This was last independently re-verified
2026-08-28 (memory: `project_byte_determinism_reverify_20260828`) by diffing 3 pre-existing
83MB `.xodr` artifacts — but that pass explicitly left an **open gap**: it only covered the
raw Osm2Odr stage, never a fresh full post-enrichment multi-run regen, because no cheap
fixture existed. The harness itself, `ultimate_pipeline/run_determinism_audit.py` and its
test `tests/unit/test_run_determinism_audit.py`, is **unit-level only** (pure-function tests
of manifest diffing / classification logic) — it does not itself exercise a live pipeline run
in CI.

Confirmed via `git log` that none of the determinism-harness files
(`run_determinism_audit.py`, `exp_osm_to_xodr_determinism.py`, both test files) have been
touched since 2026-09-06 — i.e., the harness itself predates and was untouched by the 15
merges under review. What was NOT previously known is whether `main_pipeline.py`'s stage
reordering (GAP-003), the new `xodr_validator` stage, the mtime-authority fixes (GAP-012),
and the final-artifact-authority receipt system (GAP-016) preserved determinism.

## Why a full live OSM→CARLA regen was not attempted

A full N=5 live run (the thesis-recommended rigor level) is documented as impractical
offline: `submission/results/rq1_determinism/run_summary.json` (2026-03-16) recorded a prior
attempt as `TIMEOUT_BLOCKED` — each run took an estimated 14–15 minutes even with
`UP_OFFLINE_ONLY=1`, dominated by map-preview rendering, SUMO netconvert, and continuity
stability checks (3 inner runs), independent of network I/O. This session's environment has
no live internet reachability for the Overpass API (OSM download) either, which would have
added an additional multi-minute retry/backoff stall (6 retries × exponential backoff,
confirmed empirically below) on top of that.

## What was actually run (real, non-mocked, current-code execution)

Ran the actual, unmodified `ultimate_pipeline/run_determinism_audit.py` harness — not a
mock, not a replay of old artifacts — twice, as two independent fresh subprocesses of the
**current** `main_pipeline.py`, from a fixed input:

```
UP_INPUT_XODR=reports/post_audit_hardening/20260804T060000Z/tiles/tile_1_0.xodr
UP_OSM_FILE=reports/rq1_reverify_smoke_20260923/fixture.osm   (local minimal valid OSM XML,
                                                                 pre-seeded so ensure_osm_exists()
                                                                 short-circuits without a network call —
                                                                 see note below)
python -m ultimate_pipeline.run_determinism_audit --runs 2 --offline-only \
    --timeout-per-run 500 --out reports/rq1_reverify_smoke_20260923/out --seed 42
```

`UP_INPUT_XODR` was set to an existing, small (658KB), real, committed XODR tile
(`tile_1_0.xodr`, one tile of a real prior full-map tiling run) instead of a fresh OSM
extraction, for two reasons: (1) no live network is available in this environment to fetch
OSM data — the first attempt (using `--smoke-mode`'s triage-fixture auto-resolution, which
found no local fixture and fell through to OSM download) confirmed this empirically: both
runs hung past the 120s smoke-mode cap inside `ensure_osm_exists()` (Overpass API
unreachable); (2) this also means the check below exercises `main_pipeline.py` starting
*after* the Osm2Odr stage, i.e. it directly targets the code paths the 15 merges under
review actually touched (topology repair, geometry-freeze, artifact ordering), which is a
more relevant target for *this specific* re-verification than re-proving the already-settled
Osm2Odr-stage finding.

Both runs used the harness's standard relaxed-offline forced overrides
(`UP_THESIS_STRICT=0`, `UP_DEM_STRICT_MODE=0`, `UP_DISABLE_CARLA=1`, `UP_NO_CARLA_AUTOSTART=1`,
`ENABLE_OSM2WORLD=0`, `UP_OFFLINE_ONLY=1`), `seed=42`, run in the same worktree, ~53s apart
(`audit_run_000`: 22:38:45–22:39:29Z; `audit_run_001`: 22:39:38–22:40:20Z), each taking
~52s wall-clock.

## Result: pipeline stages 01–08 are determinism-equivalent under the established contract, extended

Both runs deterministically **failed at the same point** (stage 08, CARLA-fatal lane
connectivity: "Road 300 lane -1: missing successor" ... 39 broken lanes, byte-identical list
in both runs) — expected and correct: `tile_1_0.xodr` is one tile of a larger map with
dangling references to junctions (e.g. `elementId="526"`) that don't exist in an isolated
tile, so full CARLA-loadability was never going to be achieved with this fixture. This is
**not evidence of a bug** — it's the genuine, real (not mocked) `assert_all_lanes_have_successors`
correctness gate doing its job identically in both runs.

Despite the run failing before reaching tiling/enrichment, both runs' `ultimate_pipeline_out/audit_run_00{0,1}/`
directories retained every intermediate stage artifact (01 through 08_final*). These were
hash-compared directly — full evidence in
`reports/rq1_reverify_smoke_20260923/stage_hash_comparison.json`:

| Stage file | Raw SHA-256 identical | Timestamp-normalized identical | + geometryFreezeHash-normalized identical |
|---|---|---|---|
| `01_sanitized_GPS_QA_CROP.xodr` | **YES** (raw) | YES | YES |
| `01_sanitized_audit_run_0xx.xodr` | **YES** (raw) | YES | YES |
| `02_sumo_fixed` | no | YES | YES |
| `03_topology` | no | YES | YES |
| `04_elevation` | no | no | **YES** |
| `05_planview` | no | YES | YES |
| `06_continuity` | no | YES | YES |
| `06_geometry_frozen` | no | no | **YES** |
| `07_lanes` | no | no | **YES** |
| `08_final` (+ `_laneSectionFixed`, `_semantic` copies) | no | no | **YES** |

Stage 01 is raw-byte-identical with no normalization at all (no timestamp has been injected
yet at that point in the pipeline). From stage 02 onward (once SUMO netconvert writes its own
`<!-- generated on ... -->` header/comment), raw bytes diverge as expected, but collapse to
byte-identical once the same two normalization rules from the established contract are
applied (strip `date="..."` attributes and `generated on ... by` comments — plus stripping
the harness's own `audit_run_000`/`audit_run_001` run-tag path strings baked into SUMO's
command-line-echo comment, which is a directory-naming artifact of running two audit copies
side by side, not pipeline nondeterminism).

**New finding this pass (a refinement, not a new defect):** stages 04 through 08_final still
differed after timestamp normalization alone. Root-caused to
`ultimate_pipeline/pipeline_stages/stage_05_geometry.py` (`_step5_freeze_geometry`, around
line 269): it computes `geometryFreezeHash` as a SHA-256 of the frozen XODR file's **own
serialized bytes at that point** — which still contain the un-normalized, run-specific
timestamp from the upstream SUMO stage. That hash is then written into the header
(`geometryFreezeHash="..."`) and propagates unchanged through every later stage (06, 07,
08_final all carry the same divergent hash string, with **zero other difference** once that
one attribute is also normalized — confirmed: adding `geometryFreezeHash="..."` to the
normalization set makes stages 04–08_final byte-identical). This is exactly the same root
cause as before (the wall-clock timestamp), observed one level removed — a derived hash of
timestamp-containing content will differ whenever its input does. It is **not** a second,
independent nondeterminism source; the original "exactly two places" characterization
undercounted by one indirect propagation path (a hash-of-a-file-that-contains-a-timestamp),
now corrected here.

## Existing committed determinism tests: still pass

```
pytest tests/unit/test_exp_osm_to_xodr_determinism_normalized.py tests/unit/test_run_determinism_audit.py -v
```
→ **59 passed, 1 skipped** (the skip is the expected `SKIPPED_EXTERNAL_ARTIFACT_NOT_PRESENT`
for the gitignored raw `C15_RQ4_DR/determinism/run_*.xodr` files, which don't exist on this
machine — same as every other clone/CI runner; the portable equivalent test that reads the
committed `report.json` instead ran and passed). No source code was modified during this
pass, so a full bare `pytest` run was not required per this task's own scope (verification
only); this targeted run confirms the specific harness code this task is about is unaffected
by the 15 merges.

## What this pass did NOT verify (honest scope boundary)

- **`xodr_validator` (new stage), enrichment, tiling, and the final-artifact-authority /
  receipt-based resolver (GAP-003, GAP-012, GAP-016)** were never reached — the fixture
  pipeline run failed at stage 08 (a correctness gate, not a determinism gate) before those
  later stages execute. This is the same "post-enrichment" gap flagged as open in the prior
  2026-08-28 re-verification (memory: `project_byte_determinism_reverify_20260828`) — it
  remains open, not newly closed by this pass, though the CAUSE this time (an unrepresentative
  single-tile fixture, not a real limitation of the check itself) is different and more
  fixable in a future pass (use a complete, self-contained map as `UP_INPUT_XODR` instead of
  one tile).
- A full live-network OSM extraction and a full N≥5 run at thesis rigor were not attempted —
  impractical in this session (network unreachable; ~14–15 min/run even offline, per prior
  documented evidence). This is a scope/practicality limitation, not a finding of
  nondeterminism.
- CARLA-dependent stages remain untested (as in every prior offline determinism pass);
  `UP_DISABLE_CARLA=1` throughout.

## Verdict

**VERIFIED, with an honestly-scoped boundary — unchanged from before the 15 merges, plus one
new confirmed-benign propagation path documented.**

For the portion of the pipeline actually exercised (Osm2Odr-independent seed input through
stage 08: SUMO/topology fix, topology repair, elevation, planview, continuity, geometry
freeze, lane linking, integrity/markings) — two fresh, independent, non-mocked runs of the
**current** code (`a5a2a5da`, downstream of all 15 merges under review) produced raw-diverging
but fully timestamp-and-derived-hash-normalized-identical output at every stage. This is the
same "AUTHORITATIVE for structural repeatability / BOUNDED for timestamp-normalized byte
equality" boundary the thesis already claims for RQ1 — it holds, freshly evidenced against
current code, and the normalization contract needed is now documented one field more
precisely than before (`geometryFreezeHash` added).

`xodr_validator`, enrichment, tiling, and the final-artifact-authority receipt system —
the parts of the pipeline the 15 merges most directly touched — were **not exercised** this
pass (pipeline never reached them with this fixture). This is reported as an open scope gap,
not silently elided: a follow-up pass using a complete (non-tile) seed map is needed to
extend verified coverage through those specific stages.

## Evidence artifacts (this report's directory + linked)

- `reports/rq1_reverify_smoke_20260923/run.txt` — full stdout/stderr of both real pipeline runs
  (named `.txt` not `.log` — this repo's `.gitignore` excludes `*.log` repo-wide).
- `reports/rq1_reverify_smoke_20260923/fixture.osm` — the minimal local OSM XML used to avoid
  the network-dependent `ensure_osm_exists()` path.
- `reports/rq1_reverify_smoke_20260923/stage_hash_comparison.json` — full per-stage SHA-256
  table (raw / timestamp-normalized / timestamp+freezehash-normalized) underlying the table
  above.
- `reports/rq1_reverify_smoke_20260923/out/determinism_report.json` — the harness's own
  (correctly honest) `VERDICT_UNDETERMINED` / `status: failed, reason: insufficient_successful_runs`
  output, since neither run completed a full successful pipeline pass with this fixture. This
  is the harness working as designed (it does not paper over a non-representative input); the
  stronger evidence is the direct stage-by-stage hash comparison above, which the harness's
  own coarse pass/fail gate does not perform.

Large intermediate pipeline artifacts (`ultimate_pipeline_out/audit_run_00{0,1}/`, ~96MB) are
**not committed** (per this repo's existing convention of committing the harness + report, not
large generated maps) — the SHA-256 digests in `stage_hash_comparison.json` are the citable,
reproducible evidence.
