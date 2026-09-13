# Codex — PROMPT DD: characterize and (if warranted) remediate the structure-elevation plausibility failures

## Context

Your own PROMPT BB work (`feature/structure-elevation-crs-blocker-v1-20260913`, merged into
`integration/session-batch1-20260912` at `7090213b`) fixed the false CRS blocker and got
`check_structure_elevation_plausibility.py` running for real on the pinned map for the first time.
Its verdict is explicit and un-waived: `INCOMPLETE`, `checked_road_count=238`,
`status_counts={"FAIL": 88, "INCOMPLETE": 97, "PASS": 53}`. Your own report
(`reports/production_readiness/20260913T000000Z_STRUCTURE_ELEVATION_CRS_BLOCKER/BB_STRUCTURE_ELEVATION_CRS_BLOCKER.md`)
correctly flags this as needing "separate map-quality investigation" without guessing at a cause. This
prompt is that investigation.

The gate itself (`ultimate_pipeline/quality/check_structure_elevation_plausibility.py:94-205`) samples
each classified bridge/elevated/tunnel road's interior at 5m spacing, compares the elevation-profile Z
against a DEM terrain sample at each point, and requires `elevation - terrain >= 0.5m` for bridges
(inverse for tunnels) on at least 80% of samples (`max_violation_ratio=0.2`). Roads with fewer than 2
evaluable interior samples are `INCOMPLETE`, not `PASS` or `FAIL` (fail-closed by design — do not
change this).

Pulled directly from `BB_STRUCTURE_ELEVATION_CRS_EVIDENCE.json`'s `structure_elevation_gate.failures`
array (88 entries) on this session's own inspection — do not take these numbers as given, re-derive
them fresh, but they should guide where to look:

- `violation_ratio` across the 88 failures ranges 0.21 to 1.0, mean 0.89 — most failing roads have
  nearly all samples violating, not just borderline.
- `abs(mean_delta_m)` ranges 0.029m to 2.99m, mean 0.73m — a real mix of near-miss failures (a few cm
  short of the 0.5m clearance requirement) and dramatic ones (structure sitting up to 3m on the wrong
  side of terrain).
- Concrete examples: road 42427 (elevated) has all 5 samples at delta -0.25 to -0.36m (structure
  slightly BELOW terrain despite being classified elevated). Road 44579 (elevated) ranges -1.15m to
  +0.6m across only 3 samples (mixed sign — inconsistent, not a uniform offset). Road 43596 (elevated)
  is a near-50/50 split (9/18 violate) with deltas from +0.29m to +0.93m — every sample is technically
  above terrain, several just short of the 0.5m bar.
- The 97 `INCOMPLETE` roads all show `reason=insufficient_evaluable_interior_samples`; two examples had
  `sample_count=0` and `sample_count=1` respectively — worth checking whether this is dominated by
  genuinely short structure segments (interior-sample math: `endpoint_margin = min(spacing_m*0.5,
  road_length*0.1)` at 5m spacing means anything much under ~15-20m long can't produce 2 interior
  samples) or something else.

## PROMPT DD

```text
Repository: lemoniadowyjohn/carla-control-suite. Base branch: integration/session-batch1-20260912 at
or after 7090213b (has your BB fix + the CRS-blocker resolution already merged). Isolated branch:
feature/structure-elevation-remediation-v1-<date>.

TASK 1: re-derive the real-map result fresh (don't trust the numbers quoted above, or your own prior
evidence file, without re-running). Run check_structure_elevation_plausibility.py against the current
pinned map-of-record and DEM, with structure_classifier.py's real classification and a real terrain
sampler (not a mock). Confirm checked_road_count, status_counts, and pull the full failures + incomplete
arrays.

TASK 2: characterize the FAIL population. Bucket the 88 (or however many you find) failures by
magnitude: how many are "near-miss" (violating samples within, say, 0.15m of the 0.5m clearance/cover
threshold) vs. "dramatic" (multi-meter, or mixed-sign deltas suggesting the elevation profile crosses
terrain entirely within the structure)? For a representative sample of both buckets, look at the actual
road: what does its planView/elevationProfile say, what class was it assigned and why (check the OSM
tag that drove the classification), and does a multi-meter or sign-crossing delta look like (a) a
genuine geometry/elevation defect in this road specifically, (b) a systematic DEM resolution/alignment
issue affecting a class of roads, or (c) a misclassification (e.g. an OSM tag that doesn't actually
imply a real bridge/tunnel structure here).

TASK 3: characterize the INCOMPLETE population. Confirm or refute the interior-sample-math hypothesis
above (short structures can't produce 2 evaluable interior samples at 5m spacing) by checking road
lengths for a sample of the 97. If that's the dominant cause, is minimum_interior_samples=2 /
sample_spacing_m=5.0 still the right default for THIS map's actual structure-length distribution, or
does it need recalibrating for short structures specifically (not a blanket loosening — you'd need to
justify any change with the same rigor as your CRS root-cause work)? If something ELSE dominates the
INCOMPLETE count, find and report the real cause instead of assuming the interior-sample-math
explanation.

TASK 4: for whatever real, fixable defect(s) Task 2/3 surface (if any) -- fix them. This might mean: a
genuine elevation-profile bug for a specific class of structures, a DEM sampling/alignment issue, a
structure-classification false-positive, or a gate threshold that's provably miscalibrated for this
map's real structure-length distribution (with real justification, not just "loosen it until it
passes"). If some or all of the 88/97 turn out to be genuine, currently-unfixable map defects (e.g.
would require re-surveying/re-deriving elevation from scratch), say so plainly rather than forcing a
workaround -- matching this session's precedent (BB's own "genuine data gap" framing is an acceptable
outcome, not a failure).

TASK 5: do NOT wire this gate into any pipeline stage or quality_gate_manager.py as a blocking check as
part of this task, even if you fix everything -- that's a separate, deliberate decision the earlier
structure-elevation-v1-20260907 branch also declined to make. Just report the post-fix real-map
verdict.

Do not mutate the map-of-record or any frozen evidence unless a fix specifically requires regenerating
elevation/classification data -- if so, produce it as a new candidate artifact, not an in-place edit,
and say so explicitly. Run the full offline test suite before and after.

End with:
TASK_1_REPRODUCED: <status_counts, checked_road_count>
TASK_2_FAIL_CHARACTERIZATION: <near-miss vs dramatic breakdown, root cause(s) found>
TASK_3_INCOMPLETE_CHARACTERIZATION: <dominant cause, confirmed or refuted>
TASK_4_DISPOSITION: FIXED | PARTIALLY_FIXED | GENUINE_DATA_GAP (with reasoning per class of issue)
TASK_5_REAL_GATE_RESULT_AFTER: <status_counts after any fix, or "unchanged" if no fix was warranted>
FULL_OFFLINE_TESTS: PASS | FAIL
MAP_OF_RECORD_MUTATED: NO
```
