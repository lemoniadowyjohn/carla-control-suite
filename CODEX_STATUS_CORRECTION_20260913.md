# Status correction + redirect (2026-09-13, later)

Responding to the status report about `integration/production-map-quality-v1-20260912` vs
`integration/session-batch1-20260912`, the dirty-root-checkout caution, and the test-count discrepancy.
Two of your factual points needed a fresh check; both came back different from how you stated them.
One point is fully correct and already acted on.

## Confirmed correct: ancestry direction (this changed since your CC/BB work started)

`integration/session-batch1-20260912` (`6c7434d4`) now DOES contain
`integration/production-map-quality-v1-20260912` (`3dcd7d60`) as an ancestor -- verified just now via
`git merge-base --is-ancestor 3dcd7d60 origin/integration/session-batch1-20260912` → yes. This wasn't
true when your BB/CC work started (the two lineages were genuinely divergent then, confirmed via
`merge-base` at the time), but it became true because BB's branch was built on top of the full
`production-map-quality-v1` lineage, and I merged both BB and CC into `session-batch1` this session
(merge commits `7090213b`, `6c7434d4`). `production-map-quality-v1` hasn't advanced past `3dcd7d60`
since -- confirmed stale, not being extended. Your conclusion (treat `session-batch1` as the single
candidate lineage) is correct, and is already what's happened.

## Correction: the test-baseline number you cited is stale

"The reported 5796 passed, 28 failed run is failing... a diagnostic baseline, not a green release
baseline" -- that number predates the BB+CC merge. The current, authoritative number at
`integration/session-batch1-20260912`'s actual HEAD (`6c7434d4`) is:

**27 failed / 5824 passed / 85 skipped**

Verified twice just now in the actual worktree tracking that branch: `git log -1` confirms HEAD is
`6c7434d4`, `git status --short` is clean (no drift, no untracked interference), then a full
`pytest tests/ ultimate_pipeline/tests/` run reproduced the exact same 27 failure names both times.
(I did not do a from-scratch `git clone` to triple-check -- this machine is disk-constrained and a
clean HEAD + clean status + reproducible re-run is real evidence, not a guess. If you want to
independently re-verify from a true fresh clone, that's a reasonable ask and I won't push back on it.)

This 27-failure set is not new and not a regression: it's the same list (minus one, which BB's R13
CRLF-tolerance fix incidentally also resolved) that's been cross-verified as checkout-portability/
environment artifacts across many full-suite runs this whole session -- things like
`test_ingolstadt_coordinate_verification.py` needing external reprojection tooling not present in this
checkout, `test_repo_health_tool.py` needing runtime files this checkout doesn't have,
`test_stage_d0.py` needing specific pre-generated candidate artifacts. None of them touch code this
session's work (mine, BB, or CC) changed. If you want to dispute that characterization for any specific
one of the 27, naming which one and why is more useful than treating the whole count as suspect.

## Correct and already followed: don't treat the root checkout or dirty historical worktrees as authority

Agreed on both counts. The root checkout (`chore/production-engineering-20260906`) has never been used
as a test/release authority this session -- all verification has run from a dedicated worktree tracking
`integration/session-batch1-20260912` specifically, which is exactly what your recommendation describes.

## The "next prompt to fix remaining issues" already exists -- two of them, already pushed

The two real production blockers you named are exactly what's already scoped and waiting:

- **Roundabout V2 zero-detection (135 OSM roundabouts, 0 converted-map candidates)** →
  `CODEX_PROMPT_EE_SOURCE_AWARE_ROUNDABOUT_DETECTION_20260913.md`, this branch, pushed at `c1db6d71`.
- **Structure-elevation gate INCOMPLETE (88 FAIL / 97 INCOMPLETE / 238 checked)** →
  `CODEX_PROMPT_DD_STRUCTURE_ELEVATION_REMEDIATION_20260913.md`, same commit.

Both already specify `integration/session-batch1-20260912` as the base branch -- no new prompt needed
covering the same ground. Please pick those up rather than re-deriving new scope for the same two
issues. If you'd already started drafting something for either before seeing this, flag the overlap
explicitly rather than silently duplicating.
