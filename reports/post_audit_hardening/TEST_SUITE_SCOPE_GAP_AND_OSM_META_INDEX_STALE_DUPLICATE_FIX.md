# Test-suite scope gap found + stale duplicate OSM meta-index tests fixed

## What was found
`pytest.ini` configures `testpaths = ultimate_pipeline/tests tests/unit` — two directories.
Every "full suite green" claim made earlier in this session's work (and, per git blame on
this file's neighbors, in prior sessions too) ran `pytest tests/unit -q`, which only covers
one of the two configured testpaths. `ultimate_pipeline/tests/` contains 47 files / ~488
additional tests that were never included in any of those runs: **1163 tests collected when
run with no path args (respecting `pytest.ini`) vs. 675 under the narrower `tests/unit`-only
invocation.** No CI workflow or pytest marker config justifies the narrower scope — it looks
like an unintentional habit, not a deliberate split (e.g. slow/integration tests are not
marker-excluded by default; `addopts` has no `-m` filter).

## What broke, once run
Running the actual configured suite (`pytest -q`, no path args) surfaced 8 real failures, all
in `ultimate_pipeline/tests/unit/test_osm_meta_index.py`:
```
FAILED ...test_extracts_maxspeed
FAILED ...test_extracts_turn_lanes_colon_variant
FAILED ...test_extracts_turn_lanes_underscore_variant
FAILED ...test_extracts_traffic_sign
FAILED ...test_multiple_ways
FAILED ...test_speed_limit_applied_to_matching_road
FAILED ...test_turn_lane_marking_inserted
FAILED ...test_regulatory_sign_inserted
=========== 8 failed, 1155 passed ===========
```

## Root cause
This file is a **stale duplicate** of the OSM-meta-index test surface, living in the second
testpath (`ultimate_pipeline/tests/unit/`) rather than the primary one (`tests/unit/`). It
encoded the OLD assumption that `osm_meta_index` keys its dict by **numeric road/way id** —
the exact assumption this session already found FALSE and fixed earlier (0.0000% real match
rate; commit `0231a0af`, `osm_meta_index.py` now keys by street **name**). The corrected
sibling tests (`tests/unit/test_osm_meta_index_name_matching.py`,
`tests/unit/test_osm_enrichment_writers_name_match.py`) were created at fix time — but this
duplicate file, in the other testpath, was never touched, because the fix's own verification
run (`pytest tests/unit -q`) could not see it.

## Fix
Updated `ultimate_pipeline/tests/unit/test_osm_meta_index.py` in place to match the current,
correct name-keyed contract:
- `_xodr_with_roads` helper extended to accept `(id, name)` tuples so writer-integration
  fixtures can set a real `name` attribute (previously: id-only, which can never match under
  the current name-based lookup).
- 8 fixtures updated to tag both the OSM way and the XODR road with a matching street name.
- **`test_duplicate_speed_not_inserted_twice` was silently degraded, not failing**: its OSM
  index had no `name` tag, so `build_osm_meta_index` returned an empty dict, so
  `apply_speed_limits` short-circuited to 0 on *both* calls — the assertion `n2 == 0` passed
  for a reason unrelated to the dedup logic it claimed to test. Fixed by giving it a real
  match and adding `assert n1 == 1` as a sanity check that the first call actually inserted
  something before checking the second call doesn't duplicate it.
- Two tests were intentionally left untouched (`test_speed_limit_skipped_for_unmatched_road`,
  `test_all_writers_noop_on_empty_index`): both already exercise a genuinely empty/unmatched
  index by design, unaffected by the id→name change, still correct.

## Verification
- `ultimate_pipeline/tests/unit/test_osm_meta_index.py` alone: 24/24 passed.
- Full suite respecting `pytest.ini`'s actual `testpaths` (`pytest -q`, no path override):
  **1163/1163 passed**, 0 regressions.
- No production code changed — this is a test-only fix, correcting stale fixtures to match
  behavior that was already correct in `osm_meta_index.py`/`speed_limit_writer.py`/
  `turn_lanes_writer.py`/`regulatory_sign_writer.py`.

## Follow-up recommendation, not applied here
Future "full suite" verification in this repo should invoke plain `pytest -q` (or otherwise
target both configured testpaths), not `pytest tests/unit -q`, to avoid silently excluding
`ultimate_pipeline/tests/` again.
