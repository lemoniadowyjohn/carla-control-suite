# RealismModule "RULES MODE": implemented — was advertised enabled, never built

## Root cause
`realism.py::RealismModule.enrich()` has two branches: a "SIMPLE MODE (default)" fallback
and a "RULES MODE (advanced)" branch gated by `SETTINGS.ENABLE_REALISM_RULES`. **All five
relevant flags default to `True`** (`ENABLE_REALISM_RULES`, `ENABLE_GUARDRAILS`,
`ENABLE_BENCHES`, `ENABLE_SMART_LAMPS`, `ENABLE_TRASH_BINS`), so RULES MODE runs on every
real regen — but every single feature inside it is wrapped in a defensive
`hasattr(RealismModule, "_rule_lamps"/"_benches"/"_guardrail"/"_trash_bins"/
"_estimate_curvature")` check, and **none of those five methods existed anywhere in the
file** (confirmed by direct grep before touching anything). Every flag read "enabled";
nothing beyond lamp posts was ever generated, on any real regen, silently — the `hasattr`
pattern fails open with no error, no warning, no log line indicating the gap.

`street_furniture_rules.py` already had the governed rule constants
(`LAMP_SPACING`/`LAMP_OFFSET`, `BENCH_INTERVAL`, `TRASH_EVERY`,
`MAX_CURVATURE_FOR_GUARDRAIL`, `is_residential`, `needs_guardrail`) — only the placement
logic consuming them was missing.

## Fix
Implemented all five methods in `realism.py`:
- **`_estimate_curvature(road)`** — reuses `map_stats_xodr.py::XODRMapStatsExtractor.
  _collect_curvatures` (the same arc/spiral/paramPoly3 sampler fixed in C14 earlier this
  session), not a separate implementation. Returns max |curvature| for the road.
- **`_rule_lamps(road, spacing, offset)`** — same placement as the existing `_simple_lamps`,
  parameterized by the governed rule constants instead of hardcoded values.
- **`_benches(road)`** — one bench every `BENCH_INTERVAL` (150 m).
- **`_trash_bins(road)`** — one bin every `TRASH_EVERY` (200 m).
- **`_guardrail(road)`** — one `guard_rail` object spanning the road when curvature exceeds
  `MAX_CURVATURE_FOR_GUARDRAIL`. Self-checks curvature internally (safe to call standalone,
  not dependent on the caller having already gated it — `enrich()`'s existing external
  check becomes harmlessly redundant, not wrong).

## Real impact on the pinned map (in-memory test only — the pinned file itself untouched)
| type | before | after (fresh `enrich()` call) |
|---|---|---|
| guard_rail | 0 | **21,762** |
| trash_bin | 0 | **2,310** |
| bench | 0 | 0 — see honest follow-up below |

## Honest follow-up found, not fixed here
**Benches never trigger on this real map**, even after this fix: `_infer_speed(road)` only
recognizes `<type type="...">` containing `"motorway"/"primary"/"secondary"/"residential"`,
but this map's real roads use `<type type="town">` — matching none of those, so
`_infer_speed` returns `None` for every road, `is_residential(None)` is always `False`, and
the bench gate (`ENABLE_BENCHES and StreetFurnitureRules.is_residential(speed)`) never
passes. `_benches()` itself is correct and tested (verified independently, directly); the
gap is in `_infer_speed`'s classification not covering this map's actual `<type>` vocabulary.
Not chased further in this pass — flagged, not silently left implying success.

## Verification
- TDD: `tests/unit/test_realism_module_rules_mode.py`, 9 tests — each of the 5 new methods
  tested directly (including negative cases: no guardrail on a straight road, zero benches
  on a road shorter than the interval), plus an end-to-end `enrich()` integration check.
- 675/675 full unit suite green (was 666; +9 new, 0 regressions).
- Real-data impact measured via an in-memory-only test run against the pinned candidate
  (never written back to disk — `git status` confirmed clean on the candidate directory).
- Does not affect the already-pinned map `69b1f520` — fixes the canonical live path
  (`RealismModule.enrich`, called from `stage_04_enrichment.py`) for future regens only.
