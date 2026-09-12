# Codex — PROMPT Z: generalize phase_g8's regression-gate logic into a reusable, wired tool

## Context

Triaged 11 dormant `phase_e/f/g/i/m` tools this session. 10 are confirmed one-time construction
scaffolding (hardcoded RUN_IDs from August 2026, fully superseded by live code). One,
`ultimate_pipeline/tools/phase_g8_acceptance.py`, is different: it's ALSO hardcoded to two specific
historical evidence files (`G0_EVIDENCE`/`G7_EVIDENCE` point at `reports/post_audit_hardening/
20260803T190000Z/` and `.../20260804T030000Z/`, from the original one-time Phase-G freeze) so it
cannot run against the current map-of-record as-is -- but it contains TWO ideas that are genuinely
NOT duplicated anywhere in the live pipeline:

1. **Protected-domain identity-hash regression check**: `compute_identity_hashes()` (from
   `phase_g0_handoff.py`) produces 7 hashes (planview, road_length, elevation_profile, road_link,
   junction_structure, connector_geometry, contactpoint) and G8 asserts they're byte-identical between
   a candidate and a named baseline. Checked `ultimate_pipeline/quality/map_acceptance.py` (the live,
   official acceptance gate) directly -- it has no equivalent "did any protected geometric domain
   silently drift versus the prior accepted candidate" check.
2. **Loadability error-signature regression check**: G8 runs `preflight_xodr_loadability.run_preflight`
   on both the candidate and baseline, and fails if the candidate introduces a NEW error class or
   exceeds a prior error count for an existing class (not just "loadability status == ok" in
   isolation).

This session has been asking Codex to manually report a "MAP_OF_RECORD_ACCEPTANCE_DELTA" in nearly
every prompt (W, X, Y) as an ad-hoc, per-task diff. A generalized version of G8's two checks would
replace that ad-hoc pattern with one reusable, wired regression gate any future candidate could run
against the current map-of-record automatically.

## PROMPT Z

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/candidate-regression-gate-v1-<date>.

Do NOT modify phase_g8_acceptance.py's hardcoded historical evidence-file paths or its RUN_ID -- it is
a frozen historical record of the original Phase-G construction freeze and must stay reproducible
exactly as committed.

TASK 1: extract the two genuinely reusable ideas from phase_g8_acceptance.py into a new, general-purpose
module (e.g. ultimate_pipeline/quality/candidate_regression_gate.py) with a signature like
`compare_candidate_to_baseline(baseline_xodr_path, candidate_xodr_path) -> dict` that any two XODR
files can be passed to -- no hardcoded paths, no hardcoded RUN_ID. It should report:
  - per-protected-domain hash match (reuse phase_g0_handoff.compute_identity_hashes, don't reimplement)
  - new-or-exceeded loadability error-class signatures (reuse preflight_xodr_loadability.run_preflight
    and phase_g8's own _error_signature comparison logic, don't reimplement)
  - an overall verdict distinguishing REGRESSION_CLEAN from REGRESSION_DETECTED, with the specific
    domain(s)/error-class(es) that changed.

TASK 2 (investigate before wiring): determine whether this should be wired into the live promotion
workflow (wherever the map-of-record gets promoted/pinned -- check map_registry.py and whatever script
performs a promotion) as an advisory report generated alongside every promotion, comparing the new
candidate against the map it supersedes. Advisory-first: do not make it a blocking gate in this pass
-- this map's promotion history has never had this check, so surfacing it for the first time should
not silently start blocking releases. If wiring turns out to be risky or ambiguous given how promotion
currently works, stop and report why instead of forcing it in.

TASK 3 (prove it works): run your new compare_candidate_to_baseline against two REAL, already-known
map-of-record versions from this campaign's history (e.g. the current pinned map-of-record vs its own
immediate predecessor in campaigns/ingolstadt_cooked_perception_v1/candidate/ -- check
map_registry.PINNED_MAP_REGISTRY's supersedes_path chain for a real pair) and report the actual
comparison result. This is the functional proof the tool works on real data, not just synthetic
fixtures.

End with:
TASK_1_MODULE_BUILT: PASS | FAIL -- <path>
TASK_2_WIRING_DECISION: WIRED_ADVISORY | NOT_WIRED (why)
TASK_3_REAL_PAIR_COMPARISON: <baseline path> vs <candidate path> -> <verdict + any differences found>
FULL_OFFLINE_TESTS: PASS | FAIL
```
