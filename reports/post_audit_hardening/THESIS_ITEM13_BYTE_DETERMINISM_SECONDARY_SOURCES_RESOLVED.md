# Thesis future-work #13 resolved — no secondary byte-determinism sources found

## What the thesis left open
Chapter 9, future-work item 13 (`submission/thesis_source/Chapter9/chap9.tex`): the 5-run
determinism audit found topological stability (`CV=0.0` for road/junction counts) but
byte-level XODR hash divergence. The confirmed cause was a wall-clock timestamp Osm2Odr
writes into `<header date="...">`, fixed by stripping it in the Stage 1 sanitizer.
**"Secondary sources (floating-point bounding-box accumulation... potential XML element
order variation...) have not been isolated and remain as future work."**

## What was checked
`reports/post_audit_hardening/C15_RQ4_DR/determinism/run_00{0,1,2}.xodr` — 3 real, already-
produced repeated Osm2Odr conversions of the same pinned OSM input (83,433,072 bytes each,
generated 2026-08-20 within ~90 seconds of each other), with an existing `report.json`
recording distinct sha256/md5 per run but **identical** structural signatures
(`num_roads=32920`, `num_junctions=3717`, `total_road_length=1498527.5916156755` — the float
sum matches to full precision across all 3).

Direct line-level diff of every pair (000↔001, 001↔002, 000↔002) shows **exactly two changed
lines in each comparison, always the same two**:
1. The leading XML comment: `<!-- generated on <timestamp> by ... -->`
2. `<header ... date="<timestamp>" ... north="..." south="..." east="..." west="...">` — and
   critically, the `north`/`south`/`east`/`west` bbox values themselves are byte-identical
   across all 3 runs.

No other line differs. File sizes are identical across all 3 runs (83,433,072 bytes each) —
inconsistent with any XML element reordering, which would change surrounding whitespace/line
structure.

## Verification
Normalizing only those two known timestamp locations (regex over the comment text and the
`date="..."` attribute — nothing else touched) and re-hashing all 3 real files:
```
run_000 (raw sha256 differs) -> normalized sha256: 68b9dfe4a6e5d49b317360f71718ba636347486d7f1f291fb8183d9f1a4523a3
run_001 (raw sha256 differs) -> normalized sha256: 68b9dfe4a6e5d49b317360f71718ba636347486d7f1f291fb8183d9f1a4523a3
run_002 (raw sha256 differs) -> normalized sha256: 68b9dfe4a6e5d49b317360f71718ba636347486d7f1f291fb8183d9f1a4523a3
```
All 3 collapse to a single hash. **This is a direct, empirical answer to the thesis's open
question**: at the Osm2Odr conversion stage, there is no bbox floating-point accumulation
drift and no XML element order variation across repeated runs — the timestamp is the only
source of byte-level nondeterminism.

## What was built
`ultimate_pipeline/experiments/thesis/exp_osm_to_xodr_determinism.py` — added
`_normalize_timestamps()` / `_sha256_normalized_text()` and a `stable_normalized` field
alongside the existing `stable` (raw) field in the report output. Previously this script
could only ever report `stable=False` on any repeated run (since the timestamp always
differs), giving no signal on whether that was the *only* source of divergence or whether a
real, unexplained secondary source was also present. Now `stable=False` +
`stable_normalized=True` means exactly what this investigation found: only the known,
already-explained timestamp differs. `stable_normalized=False` would mean a genuine new
secondary source has appeared and needs investigating — turning a one-time manual finding
into a standing, automatic regression check for every future determinism run.

## Verification
- TDD: `tests/unit/test_exp_osm_to_xodr_determinism_normalized.py`, 5 tests — normalization
  correctness (strips both known locations, doesn't mask a real bbox difference), and an
  integration test running directly against the real C15 artifacts on disk (asserts 3
  distinct raw hashes but exactly 1 normalized hash — the same result reported above,
  re-derived independently through the new code path rather than the ad-hoc script used for
  initial investigation). RED confirmed first (functions didn't exist), then GREEN.
- Full unit suite: see commit for exact pass count, 0 regressions expected.

## Scope / honest limitation
This is verified at the Osm2Odr raw-seed-conversion stage using 3 already-produced real
runs — it was not re-verified against a fresh full-pipeline (post-enrichment) multi-run,
which would require an expensive new regen cycle. Given the only per-run variation Osm2Odr
itself introduces is the timestamp (proven above), and every downstream enrichment stage
operates deterministically on that same structural input, there's no mechanism by which a
new secondary source would appear later in the pipeline that isn't already present at this
stage — but that inference is not independently re-verified end-to-end in this pass.
