# Stage-3 / Stage-5 byte identity (risk R-13): investigation

**Conclusion: EXPECTED BEHAVIOUR, not a defect.** R-13 is closed as "explained". Evidence class:
LOCAL_REPRODUCED. The run outputs are local; the code at the run's commit is GITHUB-reachable.

## Observation
In run `20261007_214826_524342`, `03_topology_…xodr` and `05_planview_…xodr` are byte-identical:
sha256 `45c52059ec5b7d8d1e5f2f90a2f814bde465a923e7e77768c5f5e660790c721c`, 138,932,131 bytes each.

## Causal chain (code at the run's producing commit `22cf39ab`)
1. `pipeline_stages/stage_05_geometry.py` (at `22cf39ab`, lines ~155-170):
   - the stage docstring says "Step 6 establishes horizontal (planView) geometry **first**, then
     freeze, then Step 5 applies DEM elevation";
   - `geo_out = stage_path("05_planview")`;
   - `cont_out = self._step6_planview_continuity(topo_fixed, geo_out, cont_out)`, where `topo_fixed`
     is the 03 output.
2. `pipeline_stages/stage_06_links.py` (at `22cf39ab`):
   - `_stage6_governed_containment()` (line 29) returns True under `THESIS_STRICT` or a release
     profile;
   - Stage 6 then runs `_run_stage6_read_only_diagnostic`, which prints "READ_ONLY_DIAGNOSTIC
     containment active; Stage 6 will not mutate XODR";
   - all 5 planView smoothers run **observe-only**;
   - then `_copy_artifact(elev_out, geo_out)` (line ~296) copies its input to `05_planview`.
     Here the `elev_out` parameter is the 03 path passed in step 1.
3. `_copy_artifact` (lines 237-240) is `shutil.copy2`, a byte copy that preserves the mtime.
4. **Run receipt** `stage6_containment_runtime.json`:
   - `"mode": "READ_ONLY_DIAGNOSTIC"`;
   - `"input_xodr": …03_topology…`;
   - `"planview_output": …05_planview…`;
   - `observe_only_operations`: 5; `operations_disabled`: 7.
5. **Timestamps agree:** `03` and `05` both have mtime 22:22:20, as `copy2` produces.
   The execution order by mtime is:
   - 03 (22:22:20) → 05 (copy) → 06_continuity (23:17:49) → 06_geometry_frozen (23:24:59)
     → **04_elevation (23:28:21)** → 07_lanes (23:31:27).

## Implications
- **The file numbers are not execution order.** `04_elevation` is produced after `06`. Anyone
  bisecting stages (X4, X8) must order by the code, or by receipts and mtimes, not by the numeric
  prefix.
- **GAP-070 measurements "on 05_planview" are measurements on the 03 topology output.** That is
  correct: it is the snap's actual input.
- **Ruled out:**
  - cache reuse (no cache path is involved);
  - stale output (fresh copy, and the receipt names this run's input);
  - an accidental overwrite (the copy is intentional and recorded).
- **Residual (P3, documentation):** the naming invites misreading. Recommend that X8 receipts record
  each stage's execution index and input path, as this run's stage-6 receipt already does.
