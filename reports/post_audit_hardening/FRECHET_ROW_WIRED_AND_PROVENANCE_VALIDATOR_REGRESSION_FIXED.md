# Fréchet row wired into rq_tables.json + a real regression found and fixed along the way

## Part 1 — Fréchet distance wired into the authoritative RQ1 evidence
`THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md` computed the Fréchet distance but left it a
standalone report. Completed the loop:
- Generated the real evidence artifact:
  `reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/frechet_distance_local.json`
  (via a new CLI on `frechet_gap.py`), against the same auto path C14's own evidence already
  cites, for exact provenance consistency.
- `tools/export_thesis_tables.py::_rq1_rows` now reads it and appends a BOUNDED
  `local_frechet_distance_median_m` row when present (mean/p90/matched-pair-count folded into
  the note, matching the existing one-scalar-per-row convention), gracefully omitted (not
  forced to MISSING) when the evidence file is absent — matching how `local_building_density_gap`
  already degrades.
- Regenerated `rq_tables.json`: 18 → 19 rows, `BOUNDED` 10 → 11.
- TDD: 2 new tests in `tests/unit/test_export_thesis_tables.py` (row present when evidence
  exists and cites mean/matched-pair-count; row absent and other RQ1 rows unaffected when it
  doesn't). Caught and fixed a real bug during this step: a stray trailing comma turned the
  `note=` argument into a 1-tuple instead of a string (`"...",)` — RED confirmed the bug
  immediately (`AssertionError: assert '895' in ('...',)`), fixed by removing the comma.

## Part 2 — a real regression found while sanity-checking, not caused by this session's newest work
Running `tools/validate_thesis_claim_provenance.py` (the honesty gate that independently
re-verifies every RQ claim's cited artifact against the actual file on disk) to confirm the
new Fréchet row wired in cleanly surfaced `ok=False` — but on **all ten pre-existing RQ1
rows**, not just the new one:
```
claim RQ1/local_lane_width_gap: cited artifact '...ingolstadt_perception_map_of_record_20260819_160350.xodr...'
  (sha 69b1f52016eb...) not found on disk
[... 9 more identical failures across every RQ1 metric ...]
```

### Root cause
This session's earlier C29 pin promotion (commit `81193ef9`) updated
`PINNED_MAP_REGISTRY["auto_map_of_record"]` to point at the building-frame-patched file
(sha `744757f3...`), which is correct and intentional. But `C14_RQ1_STRUCTURAL_GAP.json` (and
therefore every RQ1 row derived from it) still cites the pre-promotion sha
(`69b1f520...`) — correctly, since that's genuinely what was measured, and per this
session's own established discipline (`C29_PIN_PROMOTION_20260826.md`), historical provenance
records are not retroactively rewritten just because the live pin moved on.

`validate_thesis_claim_provenance.py`'s claim-checking logic, however, only had two paths:
(1) the cited sha matches the CURRENT live `PINNED_MAP_REGISTRY` entry, or (2) fall back to
treating the row's `artifact` field as a literal resolvable file path. RQ1's `artifact` field
is a human-readable `"<auto path> vs <manual path>"` description string, never meant to be
resolved as a path — path (1) was the only one that ever actually worked for RQ1 rows, and it
silently stopped working the instant the registry's live pointer moved away from the sha
those rows cite. **This broke the moment the C29 promotion commit landed** and was invisible
to every "full suite green" check since, because — like the `ultimate_pipeline/tests/`
scope gap found earlier this session — nothing exercised
`_verify_rq_table_claims` against the real `rq_tables.json`; the existing integration test
(`test_against_real_repo_pinned_maps_and_inputs_verify`) only checked `pinned_maps` and
`inputs_manifest`, never `rq_table_claims`.

### Fix
- `PINNED_MAP_REGISTRY["auto_map_of_record"]` already carried `supersedes_sha256` from the
  original promotion (added anticipating exactly this need) — added the matching
  `supersedes_path` alongside it, in both the live module and its
  `submission/infrastructure/` mirror (kept in sync, confirmed identical before/after).
- `validate_thesis_claim_provenance.py::_verify_rq_table_claims` now checks each registry
  entry's `supersedes_sha256`/`supersedes_path` before falling through to the generic
  (RQ1-incompatible) artifact-path search: if a cited sha matches a documented supersession,
  the superseded file is hash-verified directly and reported `PASS` with
  `via="superseded_pin:<key>"` — a real, working provenance verification, not a bypass. A
  drifted/missing superseded file still correctly fails (covered by a negative-control test).
- **Closed the real test-coverage gap**: `test_against_real_repo_pinned_maps_and_inputs_verify`
  now also asserts `result["rq_table_claims"]["ok"] is True` against the actual repo state, so
  this class of regression can't land silently again.

## Verification
- TDD: 2 new tests in `tests/unit/test_validate_thesis_claim_provenance.py` (a superseded-sha
  claim passes via the new path; a superseded-sha claim whose old file has genuinely drifted
  still fails) — RED confirmed first (both new assertions failed exactly as the real bug did),
  then GREEN.
- `tools/validate_thesis_claim_provenance.py` run directly against the real repo:
  `ok=True` (was `ok=False` with 10 failures).
- Full unit suite: see commit for exact pass count, 0 regressions expected.

## What this means going forward
Any future pin promotion that updates `PINNED_MAP_REGISTRY` should also set
`supersedes_sha256`/`supersedes_path` on the new entry (as C29's promotion already started
doing) — this fix makes that documented convention actually load-bearing rather than inert
metadata, and the new real-repo test assertion means a promotion that forgets it, or breaks
it, will be caught by the unit suite instead of only surfacing when someone happens to run the
governance script by hand.
