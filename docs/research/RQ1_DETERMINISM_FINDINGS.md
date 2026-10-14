# RQ1 Determinism Matrix — Anomaly Findings and Corrected Result

**Status:** RQ1 determinism is **UNPROVEN**. The previous matrix verdict (`FAIL`) was
not a determinism measurement.
**Branch:** `rq1-determinism-matrix-update`
**Baseline SHA under review:** `024dbb133cc9b934dd4ba09f65b04dd9d1d32f34`
**Date:** 2026-10-01
**Scope:** read-only diagnosis of `RQ1_FULL_DETERMINISM_MATRIX.json` plus tool repairs.
No pipeline stage was modified and no XODR artifact was mutated.

---

## 1. Summary of conclusions

| Question asked | Answer |
|---|---|
| Why do `03_topology` and `05_planview` share one sha256 and one mtime? | **Expected `shutil.copy2` output** from the stage-06 read-only diagnostic path. Not a hash cache, not a stale read, not fabrication. Cause **(b)**. |
| Is `run_count: 6` six usable runs? | **No.** It is 5 receipts from the trial batch (`run_00`–`run_04`) plus 1 unrelated legacy receipt, and **0 of the 6 are admissible** for an end-to-end determinism claim. |
| Does `FAIL` prove the hardening works? | **No.** `FAIL` was produced by three defects in the measurement apparatus, not by the pipeline. See §4. |
| What is the corrected status? | **`INCOMPLETE`.** All five trial runs terminated abnormally; none completed the pipeline. |
| Is there measured nondeterminism? | **Yes, but bounded and fully attributed.** Raw sha256 differs across runs; every difference is attributable to embedded wall-clock timestamps. See §5. |

**Governing contract.** `docs/research/THESIS_RQ_CONTRACT.md` records RQ1 as
*"Structural result authoritative; normalized bytes bounded."* The measured structural
signature is identical across all four comparable runs. The byte differences are
bounded by three enumerated, checkable substitutions. That satisfies the contract's
*structural* side; it does **not** satisfy the replication side, which is why the matrix
is `INCOMPLETE` rather than `PASS`.

---

## 2. The stage-03/05 duplicate: cause (b), verified in code and on disk

### 2.1 Call chain

`ultimate_pipeline/pipeline_stages/stage_05_geometry.py:163-169`

```
163: elev_out = s.stage_path("04_elevation")
164: geo_out   = s.stage_path("05_planview")
165: cont_out  = s.stage_path("06_continuity")
...
169: cont_out = self._step6_planview_continuity(topo_fixed, geo_out, cont_out)
```

Note the first argument is `topo_fixed` — the stage-03 topology artifact — while the
receiving parameter is *named* `elev_out`. At this point in the sequence the stage-05
elevation pass has not run yet (it is invoked later, at
`stage_05_geometry.py:301`), so no `04_elevation` artifact exists to pass.

`ultimate_pipeline/pipeline_stages/stage_06_links.py:423-432`

```
423: if _stage6_governed_containment(s):
424:     return _run_stage6_read_only_diagnostic(self, elev_out, geo_out, cont_out, root, ...)
```

`_run_stage6_read_only_diagnostic` is the governed read-only path. It performs **no**
mutating operation and then writes its outputs by copying:

`ultimate_pipeline/pipeline_stages/stage_06_links.py:296`

```
296:     _copy_artifact(elev_out, geo_out)     # -> 05_planview
305:     _copy_artifact(geo_out, cont_out)     # -> 06_continuity
```

`ultimate_pipeline/pipeline_stages/stage_06_links.py:237-240`

```
237: def _copy_artifact(src: str, dst: str) -> None:
238:     ...
240:     shutil.copy2(src, dst)
```

`shutil.copy2` copies the file *and its metadata*, which is why `05_planview` carries
stage 03's `mtime` rather than a fresh one. Identical bytes **and** identical mtime is
the exact fingerprint of this call.

### 2.2 Why the read-only path is active

`_stage6_governed_containment` (`stage_06_links.py:29-37`) returns `True` whenever
`THESIS_STRICT` is set, before `RELEASE_PROFILE` is even considered. `settings_snapshot.json`
records `"THESIS_STRICT": true` for **all five** trial runs, with
`"RELEASE_PROFILE": "DEVELOPMENT"`. So stage 6 is forced into `READ_ONLY_DIAGNOSTIC`
unconditionally in this configuration. `stage6_containment_runtime.json` for run 01
confirms `"mode": "READ_ONLY_DIAGNOSTIC"` with an empty `xodr_semantic_changes.changed`
list.

Under `THESIS_STRICT`, stage 6 is *supposed* to change nothing. `05_planview` being a
verbatim copy of the stage-03 input is the containment guarantee working as designed.

### 2.3 On-disk confirmation

Measured directly from the artifacts:

| Artifact | sha256 | mtime (UTC ticks, `st_mtime_ns // 100`) |
|---|---|---|
| `03_topology_20261001_042523_540218.xodr` | `612db9bf…0be7f` | `17908245033667294` |
| `05_planview_20261001_042523_540218.xodr` | `612db9bf…0be7f` | `17908245033667294` |

Byte length `138932131` for both. Creation times differ — `03_topology` at
`2026-10-01T04:58:55`, `05_planview` at `2026-10-01T05:20:58` — which is consistent with
a copy rather than a rename or a hardlink.

For contrast, the artifacts that stage 6 *does* write after its containment copy:

| Artifact | bytes | mtime (UTC ticks) |
|---|---|---|
| `06_continuity_20261001_042523_540218.xodr` | `138980429` | `17908268714321862` |
| `06_geometry_frozen_20261001_042523_540218.xodr` | `138980537` | `17908269131036827` |

So hashing is demonstrably live: `06_continuity` is a genuine second-generation copy
(fresh mtime, larger), and the freeze adds a further 108 bytes.

This pair is present in **all four** comparable runs (`run_01`–`run_04`) with a
per-run distinct sha256. It is therefore a property of the code path, not a coincidence
in one run.

### 2.4 What this anomaly is *not*

* **Not (a), a hash cache / stale read.** Every receipt sha256 was recomputed from file
  bytes. `06_continuity` and `06_geometry_frozen` differ from `03_topology` in the same
  run, so hashing is live and sensitive.
* **Not (c), fabricated data.** `06_geometry_frozen` is genuinely different per run
  (`1c73aec0…`, `1cda44bf…`, `0bc456f2…`, `41248f5d…`), so the artifacts are not cloned
  from a single template.

### 2.5 The one place (c) *does* apply

The **legacy** receipt `reports/final_hardening_p11/run_00_receipt.json` — the *first* row
of the superseded matrix — claims:

```
stage 03: sha=b89ec2706fb93dc0…  bytes=138932131  mtime=1790780814.4625652
stage 05: sha=b89ec2706fb93dc0…  bytes=138932131  mtime=1790780814.4625652
stage 06: sha=b89ec2706fb93dc0…  bytes=138932131  mtime=1790780814.4625652
```

* Its `03 == 05` pair is consistent with the verified `copy2` behaviour. **Not** suspect.
* Its `06 == 03` is **not** reproducible by any observed pipeline behaviour. Every real
  run produces `06_geometry_frozen` at `138980537` bytes with a distinct sha256, because
  the freeze step appends `geometryFrozen` / `geometryFreezeHash` attributes. Measured
  directly on run 01: `03_topology` is `138932131` bytes, `06_continuity` is `138980429`,
  `06_geometry_frozen` is `138980537` — three distinct sizes. The legacy receipt's stage
  `06` repeats stage `03`'s `138932131`, which corresponds to no artifact the pipeline
  produces.
* `tools/rq1_trial_run.py` (the driver that produced it) states in its own header that
  its output *"is NOT yet the full rq1_run_receipt/v1 schema tools/rq1_five_run_matrix.py
  expects"* and that *"run_00's real receipt was produced by additional post-processing on
  top of this script's raw run, not by this script alone."* The post-processing step was
  never committed, so the receipt's stage hashes have no reproducible generator.
* It is **orphaned**: `reports/final_hardening_p11/` contains only this receipt, no
  artifacts, no `run_status.json`. Its `config.code_sha` is `8eb80924`, a different code
  revision from the trial batch. Nothing can corroborate or refute it.
* Its `reason` field is internally inconsistent: *"run killed at 60-min session timeout
  during stage 06/07; stages 01-06 complete"* claims stage 06 both complete and in
  progress.
* Its `structural_signature.num_junctions = 3559` is a **different metric** from the
  `22588` reported by the trial receipts (see §4.3).

**Disposition:** row 0 of the superseded matrix is unreliable provenance and is excluded.
The stage-06 value is a copied field. This is a statement about the receipt's
trustworthiness, not an accusation about intent.

---

## 3. `run_count: 6` is not six runs

```
row 0  rq1_run_receipt/v1  run=0  stages=['01','02','03','05','06']  sig.junctions=3559   <- reports/final_hardening_p11/run_00_receipt.json
row 1  rq1_run_receipt/v1  run=0  stages=['1']                        sig.junctions=22589  <- trial run_00
row 2  rq1_run_receipt/v1  run=1  stages=['1','2','3','5','6']        sig.junctions=22588  <- trial run_01
row 3  rq1_run_receipt/v1  run=2  stages=['1','2','3','5','6']        sig.junctions=22588  <- trial run_02
row 4  rq1_run_receipt/v1  run=3  stages=['1','2','3','5','6']        sig.junctions=22588  <- trial run_03
row 5  rq1_run_receipt/v1  run=4  stages=['1','2','3','5','6']        sig.junctions=22588  <- trial run_04
```

The count is **6 rows, 5 distinct run identities, 2 receipts labelled `run: 0`, and 2
mutually incompatible schemas.** `tools/rq1_five_run_matrix.py` accepted
`len(rows) >= 5` and nothing else, so a legacy receipt, a single-stage receipt and four
crashed receipts were pooled into one comparison.

It is **not** intentional design, and it is **not** corruption of the underlying
artifacts. It is an unvalidated aggregation.

---

## 4. Why `FAIL` did not measure determinism

The superseded matrix reported four mismatched fields. Each has a non-determinism cause:

### 4.1 `output_path` — guaranteed mismatch (tool defect)

Every isolated run writes into its own timestamped directory
(`Settings.stage_path`, `ultimate_pipeline/config/settings.py:1599`), so `output_path`
*cannot* match across five genuine runs. It was in the compared-key list at
`rq1_five_run_matrix.py:29`. **Any** correctly executed five-run matrix was guaranteed to
`FAIL` on this field alone. Fixed: excluded as non-determinism-bearing.

### 4.2 `xodr_sha256` — not "6 distinct values", it is 3 populations

| Population | Members | `xodr_sha256` | Meaning |
|---|---|---|---|
| Legacy orphan | row 0 | `null` | never produced |
| Trial `run_00` | row 1 | `370abbbb…` | stage **01** artifact (run died at stage 1) |
| Trial `run_01`–`run_04` | rows 2-5 | 4 distinct values | stage **06** artifacts |

A `null`, a stage-01 file and four stage-06 files are not three measurements of one
quantity. `run_00`'s contribution is a *different stage* of the pipeline. Fixed: the
matrix now requires a common `terminal_stage`.

### 4.3 `structural_signature` / `topology_counts` — two different metrics, two different stages

`3559` vs `22588`/`22589` is a **metric definition** difference, not map drift:

* `3559` = count of `<junction>` elements in the file (matches `xodr_statistics.json`,
  which logs `"junctions": count 3559`).
* `22588` = count of roads carrying a junction reference, which is what
  `xodr_structural_summary.summarize_xodr` returns and what the assembler recorded.

Separately, `run_00`'s signature is sampled from `01_sanitized`
(32267 roads / 22589 / 1489145.575 m) while `run_01`–`run_04` are sampled from
`06_geometry_frozen` (32266 / 22588 / 1487573.690 m). The one-road, one-junction
difference is **SUMO `netconvert` removing a road**, and it only looks like a
determinism failure because the receipt's terminal stage was never recorded. The
receipts did not say which stage their signature came from; the assembler now records
`structural_signature_stage` explicitly.

### 4.4 Nothing was ever compared at equal footing

The builder ignored `status` entirely. Every one of the six receipts reads
`"status": "INCOMPLETE"`, and the trial runs additionally record `status: failed` in
their own `run_status.json`. The builder averaged artifacts from crashed runs into a
determinism statistic.

---

## 5. Measured nondeterminism: real, bounded, fully attributed

`reports/rq1_determinism_attribution.json` — produced by `tools/rq1_determinism_audit.py`
over the real artifacts:

| Stage | runs present | distinct raw sha256 | distinct after declared normalization | attribution |
|---|---|---|---|---|
| `01_sanitized` | 5 | 1 | 1 | identical bytes |
| `02_sumo_fixed` | 4 | 4 | 1 | `opendrive_header_date`, `sumo_provenance_comment` |
| `03_topology` | 4 | 4 | 1 | `opendrive_header_date` |
| `05_planview` | 4 | 4 | 1 | `opendrive_header_date` |
| `06_continuity` | 4 | 4 | 1 | `opendrive_header_date` |
| `06_geometry_frozen` | 4 | 4 | 1 | `opendrive_header_date`, `geometry_freeze_hash` |

Structural signature across `run_01`–`run_04` is identical:
`roads=32266, junctions=22588, total_road_length=1487573.690297`.

### The three substitutions, and why each is run-local

1. **`sumo_provenance_comment`** — `<!-- generated on <timestamp> by Eclipse SUMO netconvert … -->`.
   SUMO embeds its wall-clock start time and the absolute input/output paths it was
   invoked with. Both differ per isolated run by construction.
2. **`opendrive_header_date`** — the `date` attribute of the OpenDRIVE `<header>`.
   Written once by SUMO at stage 02 and carried verbatim through every later stage, so a
   single per-run timestamp propagates to the final artifact.
3. **`geometry_freeze_hash`** — `geometryFreezeHash="…"`. It is a hash *of the
   artifact's own bytes*, which include the header date. It is a **transitive
   consequence** of rule 2, not an independent source of nondeterminism. This is why
   `06_geometry_frozen` needs two rules while `03_topology` needs one.

Each rule is a plain regex in `tools/rq1_determinism_audit.py` and can be checked by hand
against the source files. No geometry, coordinate, road, junction or elevation value
differs across the four comparable runs.

**This does not upgrade the verdict.** `tools/rq1_five_run_matrix.py` applies **no**
normalization; a differing raw sha256 remains a `FAIL` there. The audit exists to
attribute bytes, and it says so in its own `verdict_note`.

---

## 6. Why `INCOMPLETE`, not `PASS` and not `FAIL`

`run_01`–`run_04` all terminate with the identical failure
(`crash_traceback.txt`, 4/4 runs):

```
RuntimeError: F1 CRS contract unresolved: cannot establish the geographic frame of
…\06_geometry_frozen_….xodr (verdict=UNRESOLVED, reason=osm_source_unavailable).
DEM sampling fails closed. Provide the OSM source or a resolvable geoReference.
```

`run_status.json` records `status: failed`, `stage: geometry`. Consequently:

* **No `04_elevation` artifact exists in any run.** The elevation/DEM pass never
  produced output, so stages 05 onward (lanes, hygiene, positional semantics, tiling,
  tile QA, simulation, domain gap) were never exercised.
* `run_00` records `status: running` — the process never wrote a terminal state at all.
  It reached only `01_sanitized`.

Admissible runs under the repaired gate: **0 of 5.** Every trial run either failed or
never terminated, so none can witness end-to-end determinism. Reporting `PASS` from four
runs that all died at stage 05 would be the "reinterpret favorably" failure mode. The
honest result is `INCOMPLETE`.

**Blocking conditions, both real:**

1. RQ1 requires five completed isolated runs; zero completed runs exist.
2. The DEM stage fails closed because `osm_source_unavailable`. `settings_snapshot.json`
   pins `OSM_FILE` to
   `…\cities\ingolstadt\osm\ingolstadt.osm`, and that file **does not exist**. The
   directory contains only `buildings.geojson` (4,040,150 bytes). Until the source is
   restored or the geoReference is made resolvable, no trial run can get past stage 05,
   and re-running would reproduce `INCOMPLETE` rather than a determinism result.

---

## 7. Changes made

| File | Change |
|---|---|
| `tools/rq1_receipt_assembler.py` | **Rewritten to `rq1_run_receipt/v2`.** Keys stages on full `<NN>_<name>` identity; adds `--run-dir`, `--artifacts-external`; records `terminal_stage`, `pipeline_status` (with crash traceback), `structural_signature_stage`, `junction_metric`, `byte_identical_stage_pairs`, `metadata_preserving_copy`, `unattributed_artifacts`. |
| `tools/rq1_five_run_matrix.py` | **Rewritten to `rq1_full_determinism_matrix/v2`.** Adds an admissibility gate (schema, terminal success state, non-empty stages, common `terminal_stage`); removes `output_path`/`out_dir`/`run` from the compared keys; reports `admissible_run_count` and `blocking`. |
| `tools/rq1_determinism_audit.py` | **New.** Per-stage raw and content-normalized sha256 with an enumerated, hand-checkable rule list. Explicitly cannot change the verdict. |
| `tests/unit/test_o15_rq1_five_run_matrix.py` | 4 → 18 tests, each anchored to one of the defects above. |
| `RQ1_FULL_DETERMINISM_MATRIX.json` | Regenerated: `FAIL` → `INCOMPLETE`, with `admissible_run_count: 0` and both blocking conditions. |
| `reports/rq1_determinism_attribution.json` | **New.** Measured attribution evidence over the real artifacts. |
| `reports/rq1_trial_runs/**` | 65 metadata files (80 KB) + 5 regenerated receipts committed. |
| `reports/archive/RQ1_FULL_DETERMINISM_MATRIX.superseded-20261001.json` | The original `FAIL` matrix preserved verbatim as historical evidence. Not deleted, not rewritten. |

### The stage-key collision bug (assembler)

The old assembler mapped artifacts to stages with `re.match(r"^(\d{2})_", fname)` and
then `stage_files[stage] = odir / fname`. Two distinct stages share the `06` prefix —
`06_continuity` and `06_geometry_frozen` — so they collided on key `"6"` and whichever
entry `os.listdir` yielded **last silently won**. A receipt could therefore describe an
artifact the pipeline never produced, decided by filesystem enumeration order. The
committed v1 receipts are keyed `"1"`, `"2"`, `"3"`, `"5"`, `"6"`; the `"6"` slot is
whichever of the two `06_*` files sorted last. Fixed by keying on the full stage name and
by raising on a genuine duplicate identity.

### Artifact provenance

XODR artifacts are 130–150 MB each (2.9 GB for the five-run set) and are governed by the
blanket `*.xodr filter=lfs` rule in `.gitattributes`. They are **not** committed. Each
receipt carries an `artifact_provenance` block declaring `artifacts_committed: false`
with the measured run directory, so no receipt can be mistaken for a self-contained,
reproducible input set.

`stage6_containment_runtime.json` is **732 MB per run** and `continuity_debug.json` is
26 MB; both were deliberately excluded from the committed metadata set.

---

## 8. Reproduction

```powershell
# tests
python -m pytest tests/unit/test_o15_rq1_five_run_matrix.py -q

# receipts, measured in place from the real artifact directories
python tools/rq1_receipt_assembler.py 1 <artifacts>/run_01/20261001_042523_540218 `
    --run-dir <artifacts>/run_01/20261001_042523_540218 `
    --out <worktree>/reports/rq1_trial_runs/run_01/20261001_042523_540218/receipt_run_01.json `
    --artifacts-external

# matrix
python tools/rq1_five_run_matrix.py <worktree>/reports/rq1_trial_runs/*/*/receipt_run_*.json `
    --out RQ1_FULL_DETERMINISM_MATRIX.json

# byte attribution
python tools/rq1_determinism_audit.py <artifacts>/run_00/... <artifacts>/run_01/... `
    <artifacts>/run_02/... <artifacts>/run_03/... <artifacts>/run_04/... `
    --out reports/rq1_determinism_attribution.json
```

**Test results:**

| Command | Result |
|---|---|
| `pytest tests/unit/test_o15_rq1_five_run_matrix.py -q` | **18 passed** |
| `pytest tests/unit -q` | **2507 passed, 1 failed, 5 skipped** (27m16s) |

The single failure is **pre-existing and unrelated**:

```
FAILED tests/unit/test_a1_a2_path_and_frame_resolution.py::
  TestPortablePathResolution::test_no_hardcoded_username_in_production_defaults
AssertionError: cook DEFAULT_OSM2WORLD_HOME embeds dev path: <repo>/OSM2World-latest-bin
```

`scripts/cook_full_grid_tiles.py:101-115` derives `DEFAULT_OSM2WORLD_HOME` from
`REPO_ROOT`, so the assertion fails whenever the checkout path itself contains
`c:\users\admin`. It reproduces identically at the baseline SHA `024dbb13` in the
pristine original checkout, and neither `scripts/cook_full_grid_tiles.py` nor
`ultimate_pipeline/enrichment/osm2world_runner.py` is touched by this change. Not fixed
here: it is outside RQ1 scope and the fix is a portability policy decision, not a
determinism bug.

---

## 9. Open items

1. **Blocking for RQ1.** Restore or pin the OSM source so `osm_source_unavailable`
   clears, then re-run five isolated trials to completion. Until then RQ1 stays
   `INCOMPLETE`.
2. **Blocking for RQ1.** Commit or LFS-track the trial XODR artifacts, or accept that
   receipts are only reproducible against a local artifact store.
3. **Not addressed.** `reports/final_hardening_p11/run_00_receipt.json` is still
   orphaned. It is excluded from the matrix; this change does not repair or delete it.
4. **Not addressed.** The v1 receipt schema is still readable but no longer generated.
   Any other consumer of `rq1_run_receipt/v1` needs a migration check.
