# OSM meta-index enrichment: fixed a 100% silent failure across 4 consumers

## Root cause
`osm_meta_index.py::build_osm_meta_index` (introduced 2026-04-07, commit `0bc2768c`) keyed
its output by **OSM way id**, on the explicit, stated assumption "the XODR road id
produced by osm2xodr / netconvert equals the OSM way id." **Verified false** against the
real pinned pair (2026-08-26): XODR road ids are Osm2Odr/netconvert-assigned sequence
numbers (e.g. `"42330"`), OSM way ids are the original OSM entity ids (e.g. `"4058127"`)
— disjoint numbering schemes.

**Quantified severity:** 11,885 OSM ways carry real enrichment data (maxspeed, turn:lanes,
traffic_sign, lane-width metadata), but **0 of 32,297 real XODR roads matched any of them
by direct id lookup — a 0.0000% match rate.** All four downstream consumers fail *open*
(no exception, no warning), so this ran silently on every real regen since the feature was
merged, reporting "0 speed limits / 0 turn markings / 0 signs" and inserting nothing.

## The four affected consumers (all shared the identical `road.get("id")` lookup bug)
| Consumer | Purpose | Before fix | After fix (real pinned map) |
|---|---|---|---|
| `speed_limit_writer.py::apply_speed_limits` | `<speed>` elements per driving lane | 0 | 2 |
| `turn_lanes_writer.py::apply_turn_lanes` | turn-marking userData | 0 | 1,101 |
| `regulatory_sign_writer.py::apply_regulatory_signs` | `<object>` sign elements | 0 | 0* |
| `lane_width_policy.py::road_lane_width_metadata` | OSM-informed lane width | 0 roads matched | 8,869 roads matched |

`*` signs remain 0 — a **separate, unrelated gap**: `SIGN_TABLE`'s vocabulary likely
doesn't cover the real OSM `traffic_sign` tag value formats present in this dataset.
Not chased in this pass; flagged as an honest follow-up, not silently left implying success.

## Fix
`build_osm_meta_index` now keys by **street name** (the OSM way's `name` tag), verified
90.3% viable (969/1,073 distinct enrichment-tagged OSM way names match a real XODR road
name on the pinned pair). All four consumers updated to look up by
`road.get("name", "").strip()` instead of `road.get("id", "")`. Ways without a `name` tag
are correctly excluded from the index (cannot be matched by any real consumer), not
silently indexed under an empty-string key.

**Honest caveat, documented in the code, not hidden:** this is a many-to-many
correspondence at the *street* level — one street is commonly several OSM ways (their
tags are merged) *and* several XODR road segments after netconvert splits it at
intersections (all matching segments receive the same entry). Appropriate for a
street-level attribute like `maxspeed`. For position-specific tags (`turn:lanes`,
`traffic_sign`), a value that originally described one specific way/intersection-approach
may now be applied to every XODR segment sharing that street name — reported as
approximate, not exact, in each writer's docstring.

## Verification
- TDD throughout: `test_osm_meta_index_name_matching.py` (4 tests, incl. a real-pinned-data
  regression guard) + `test_osm_enrichment_writers_name_match.py` (4 tests).
- One pre-existing test (`test_lane_width_policy.py::test_osm_meta_index_includes_lane_width_inputs`)
  encoded the same false way-id-keying assumption (its synthetic way had no `name` tag,
  coincidentally matching only because the test's expected key happened to equal the way
  id) — updated to a named way, matching the corrected, real contract.
- Real end-to-end verification against the pinned map for all 4 consumers (table above).
- 656/656 full unit suite green.

## Not in scope for this fix
- `regulatory_sign_writer`'s `SIGN_TABLE` vocabulary gap (0 signs matched even with correct
  name-based lookup) — a separate investigation.
- No re-regen of the pinned map `69b1f520` — this fixes the canonical pipeline path for
  *future* regens; the already-shipped pin was generated before this feature existed at all
  (`0bc2768c` postdates the pin), so the pin is unaffected either way.
