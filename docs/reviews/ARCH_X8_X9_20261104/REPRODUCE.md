# Reproducing the ARCH-X8-X9 / ARCH-002 measurements

## 1. Get the inputs
The stage files of run `20261007_214826_524342` are needed (`PROVENANCE.json` → `stage_files`;
1,063,561,918 bytes in total). **They are not yet published.** Retrieve them from the archive
location in `ARCHIVE_PROPOSAL.md` once the operator approves the upload. Put them in one directory,
`RUN_DIR`, under their original filenames.

## 2. Verify the input bytes
```sh
cd "$RUN_DIR" && sha256sum 0*.xodr
```
Every hash must equal `PROVENANCE.json`. **Stop on any mismatch.** In particular, stage 05 must be
`45c52059ec5b7d8d1e5f2f90a2f814bde465a923e7e77768c5f5e660790c721c` (138,932,131 bytes).

## 3. Check out the code under test
```sh
git clone https://github.com/lemoniadowyjohn/carla-control-suite.git cs && cd cs
git worktree add ../cand 2cee039f235f2cff7c87fa1fce935154cdcf3cd8   # GAP-070 candidate
export CANDIDATE_WT="$(cd ../cand && pwd)"
```
Use `GIT_LFS_SKIP_SMUDGE=1` if you don't need the LFS files; the scripts only need Python sources.

## 4. Environment
- Python 3.12 (3.12.2 was used), `shapely` 2.x (2.1.2 was used), and the standard library.
- No other packages. The scripts import the repository's own `ultimate_pipeline` from `CANDIDATE_WT`.
- Memory: about 3 GB (each script parses one 120–150 MB XODR with ElementTree).
- Missing dependencies: **none known**. Not tested on Linux or macOS (paths are passed through the
  environment, so it should work there).

## 5. Run
```sh
export RUN_DIR=/path/to/run_dir OUT_DIR=/path/to/out
export STUB_INVENTORY=/path/to/stub_inventory.json   # only for x9check.py (branch research/gap070-reversed-stubs-20261104 @06a31ed1)
cd "$CANDIDATE_WT"
python <pkg>/evidence/x7_geom_audit.py                      # -> $OUT_DIR/x7_geom_audit.json
python <pkg>/evidence/x7_crosscheck_kernel.py "$CANDIDATE_WT" "$RUN_DIR/05_planview_20261007_214826_524342.xodr" "$OUT_DIR/x7_crosscheck_kernel.json" 2000
python <pkg>/evidence/x7_displacement.py "$CANDIDATE_WT" "$RUN_DIR/05_planview_20261007_214826_524342.xodr"
python <pkg>/evidence/lane_border_check.py "$CANDIDATE_WT" "$RUN_DIR/05_planview_20261007_214826_524342.xodr" "$CANDIDATE_WT"
python <pkg>/evidence/uturn_count.py 01_sanitized_20261007_214826_524342.xodr 02_sumo_fixed_20261007_214826_524342.xodr 05_planview_20261007_214826_524342.xodr
python <pkg>/evidence/x9check.py
```
`x7_examples.py` (prints 3 example connectors) needs `$OUT_DIR/x7_geom_audit.json` from the first
run.

## 6. Compare
- `x7_geom_audit.json`: compare against `evidence/x7_geom_audit.json`, ignoring `input` and
  `_redaction_note`. Every other field must match exactly. This was verified once on the original
  machine, from the published copy.
- `x7_crosscheck_kernel.json`: must match `evidence/x7_crosscheck_kernel.json` exactly.
- Stdout scripts: compare with the numbers quoted in `../ARCH002_20261104/ARCH002_INDEPENDENT_REVIEW.md` §A and
  §A+, and in `CLAUDE_GEOMETRY_ARCHITECTURE_REVIEW.md` (U-turn counts).
- Possible environmental differences:
  - shapely version (affects `is_simple` only at the margins; see the ±3 sampling note in `ERRATA.md`);
  - float formatting is identical across CPython 3.12 builds; other versions are untested.
