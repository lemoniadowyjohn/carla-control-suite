# Map Of Record

The current automatic map of record is:

`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr`

- SHA256: `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`
- Size: `149799632` bytes
- Promoted 2026-09-17: regenerated after two pipeline bug fixes since the prior pin
  (2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798, 2026-09-05) --
  946228f9 (hardener no longer strips road-level `<link>` from junction connectors)
  and a13efd91 (`GeometryValidator._validate_road()` repairs a degenerate `<planView>`
  in place instead of leaving it empty). Verified: well-formed XML, 32267 roads /
  3561 junctions, all 5 previously-crashing roads (54601, 57919, 64775, 67658, 67798)
  now carry a valid non-empty `<planView>`, 0 roads anywhere with an empty/missing
  `<planView>`. Pipeline acceptance: `valid_for_experiments=true`,
  `hard_fail_reasons=[]`; 2 soft-only warnings (`lane_count_changes`
  unexplained=3007, `component_reachability` 3 isolated lane components,
  largest_fraction=0.99793). `component_reachability` is within precedent already
  accepted for this map lineage (27 isolated components, 2026-09-04);
  `lane_count_changes` has no prior baseline -- its gate (`8a02e0f1`, 2026-09-09)
  postdates the previous pin, so 3007 is its first-ever measurement here.
  The original `lane_count_changes` metric is preserved for historical
  reproducibility, but the later production classifier resolved all 3,007/3,007
  findings against real topology evidence: 175 source-proven lane changes and
  2,832 junction transitions (1,406 declared-connection cases with laneLink
  counts independently consistent with the connecting road, plus 1,426
  connector-adjacent cases). It found 0
  `suspicious_unexplained_discontinuity` and 0 unresolved-link cases, and two
  systematic cross-checks found no mismatches. The residual caveat is therefore
  measurement/provenance design (OSM `lane_count_source` coverage is only
  about 0.4%), not 3,007 known map defects. See GAP-005 in the live production
  gap register for the exact evidence and regression test.
- Manual reference: `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr`
- Manual SHA256: `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`
- Pinned OSM SHA256: `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`

Verify the registry before use with `verify_pinned_map('auto_map_of_record')`.
