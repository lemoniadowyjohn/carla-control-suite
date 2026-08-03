# F5 — bounded elevation offsets at road links

- run_id: `20260803T160000Z`
- verdict: **F5_BOUNDED_OFFSETS_PASS**

## Solver

- per-road vertical offsets applied: 32647
- connected components: 4
- max abs offset: 7.864 m (bound 50.0 m)

## Seams (road-to-road contact points)

| stage | seams checked | max delta | over threshold |
|---|---|---|---|
| before | 45632 | 5.129 m | 1 |
| after  | 45632 | 3.036 m | 0 |

## Slope preservation (only `a` shifted)

- b/c/d identical across all segments: True
- segment counts preserved: True

## Checks

- f4_candidate_untouched: PASS
- solver_ok: PASS
- max_offset_within_bound: PASS
- slope_coeffs_preserved_bcd: PASS
- segment_counts_preserved: PASS
- seam_reduced_or_bounded: PASS
- seams_within_tolerance: PASS

The solver only shifts each segment's constant `a` (vertical offset), leaving slopes (b/c/d) and segment structure untouched.  All road/links geometry and topology in the F4 candidate is byte-untouched; a new F5 candidate file is produced.