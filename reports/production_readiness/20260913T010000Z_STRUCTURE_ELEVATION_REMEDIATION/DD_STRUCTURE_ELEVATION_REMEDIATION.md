# DD Structure-Elevation Remediation Disposition

## Scope

DD re-derived the structure-elevation plausibility result against the governed
Ingolstadt map, authoritative OSM, and DEM. It added only read-only
diagnostics that share the gate's exact interior-sample, elevation-polynomial,
and terrain-sampler semantics. It did not modify the map-of-record, adjust a
quality threshold, enable a pipeline stage, or start CARLA.

## Inputs

| Input | SHA-256 |
| --- | --- |
| XODR map-of-record | `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798` |
| OSM source | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` |
| DEM | `3cfa665dde3782a015502beaf457854db2f639d01008a386c925d171e41f4ff8` |

## Reproduction

The current gate exactly reproduced the BB evidence: 238 checked roads, 88
`FAIL`, 97 `INCOMPLETE`, and 53 `PASS`. The complete failure and incomplete
arrays are byte-identical to the pre-refactor gate summary. The gate remains
`INCOMPLETE` by design.

## Failure Characterisation

The 88 failures are not primarily near-threshold noise. Only two failures have
all violating samples within 0.15 m of the required clearance or cover. The
remaining primary buckets are 62 material, 21 mixed-sign terrain crossings,
and three with at least one absolute elevation-terrain delta of 2 m or more.
Across the full failure population, 53 have a maximum shortfall of at least
1 m, 17 bridge/elevated roads lie entirely at or below terrain, and 38 tunnel
roads lie entirely at or above terrain. Every failure has an OSM source match
for its assigned class; seven have overlapping structure sources and remain
explicitly ambiguous rather than silently reclassified.

Representative failures show distinct map-elevation defects: road `42427` is
an OSM `bridge=yes`, `layer=1` trunk segment whose five samples are 0.25-0.36
m below terrain; road `44579` is a similarly sourced bridge with a -1.15 to
+0.61 m terrain crossing; road `52656` is an elevated track 2.16 m below
terrain at both evaluable samples; and road `71665` is an OSM tunnel 1.33 m
above terrain. These are incompatible with a globally misaligned DEM because
the same real sampler also yields 53 passes across the same structure classes.

## Incomplete Characterisation

All 97 incomplete records have `insufficient_evaluable_interior_samples`, not
missing terrain or elevation data. Fifty have zero eligible samples and 47 have
one. Their lengths are 0.10-9.05 m (median 3.36 m; 75th percentile 7.99 m),
so none can satisfy the existing requirement for two interior samples at 5 m
spacing. Lowering the evidence requirement would convert micro-segment
uncertainty into a false pass/fail result; it is not warranted by this data.

## Disposition

No numerical threshold was changed. The 88 failures require a governed
candidate map whose bridge deck/tunnel floor elevation is re-derived and then
validated against the same sampler. The 97 short structure segments remain
`INCOMPLETE` until a separately reviewed short-segment evidence policy exists.
The gate is intentionally not wired as a production-blocking stage by DD.

## Verification

Pre-change full pytest: 5,912 passed, 82 skipped, 0 failed in 406.95 s.
Post-change full pytest: 5,915 passed, 82 skipped, 0 failed in 407.94 s.
The three-test increase covers the shared evaluator and diagnosis categories.

TASK_1_REPRODUCED: `{"FAIL": 88, "INCOMPLETE": 97, "PASS": 53}`, 238 checked

TASK_2_FAIL_CHARACTERIZATION: 2 near-miss, 62 material, 21 mixed-sign, 3 multi-meter primary buckets; elevation-profile/map-data defects are the dominant cause

TASK_3_INCOMPLETE_CHARACTERIZATION: confirmed short-segment evidence limit; all 97 have zero or one interior sample and length at most 9.05 m

TASK_4_DISPOSITION: `GENUINE_DATA_GAP`; map regeneration is required for the failing elevations, and no threshold relaxation is justified

TASK_5_REAL_GATE_RESULT_AFTER: unchanged, `{"FAIL": 88, "INCOMPLETE": 97, "PASS": 53}`

FULL_OFFLINE_TESTS: `PASS`

MAP_OF_RECORD_MUTATED: `NO`
