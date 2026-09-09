# C34 - Heading smoothing with the paramPoly3 guard: still unsafe

Date: 2026-09-09

This is a controlled successor to C31 and C33. It re-runs the explicit,
offline-only heading-smoothing plus geometry-start-recompute experiment after
the 2026-09-04 `paramPoly3` guard was added to
`recompute_geometry_starts_chained_inplace`.

## Scope and controls

- Base: `f195ba0b5d6df3f085573c5e996ff9d0f11a975f`.
- Branch: `feature/gap-024-heading-smoothing-20260909`.
- Seed SHA-256: `c32d136a939f9522065f582e79f622a146239cd39a1af987781e2c7df2124e44`.
- Harness: `scripts/regen_experimental_heading_smoothing_v2_with_recompute.py`.
- Profile: `EXPERIMENTAL_UNSAFE`; only its explicit experimental planview,
  heading-smoothing, and geometry-start-recompute flags were enabled.
- `UP_DISABLE_CARLA=1` was set. CARLA was not started, contacted, or used.
- The map-of-record was read only and remains
  `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`.

The initial sparse-worktree attempt is retained as infrastructure provenance,
but is not used as result evidence: it reached the substantive planview stage
and then failed final integrity because the sparse checkout omitted the root
`tools` package. The corrected run included that package and completed with
pipeline exit code zero.

## Guard under test

Commit `21cc64308` (2026-09-04) causes
`recompute_geometry_starts_chained_inplace` to skip chaining when the previous
geometry is `paramPoly3` with `pRange="arcLength"`. Its rationale is valid: a
declared OpenDRIVE length can disagree with the true parameter endpoint, so
blindly chaining from that evaluated endpoint can create a new seam. This
experiment tests the governed behavior of that guard; it does not alter it.

## Results

The final experimental candidate is:

`campaigns/ingolstadt_cooked_perception_v1/candidate/EXPERIMENTAL_heading_smoothing_v2_recompute_20260909_111658.xodr`

SHA-256: `fb920f84a8c6572dbca5d8272970a40b45d3c761ff8f62482de16f2bd282365c`.
It is explicitly experimental and was not promoted.

`check_planview_internal_seams` was independently run twice against both the
candidate and the pinned map-of-record using the same checker thresholds
(`eps_xy_m=0.2`, `eps_hdg_only_deg=5.0`). Each repeated result was identical.

| Metric | Map-of-record | C31 smoothing only | C33 smoothing + recompute | C34 guarded final candidate |
|---|---:|---:|---:|---:|
| `ok` | True | False | False | False |
| real position seams | 0 | 6,024 | 410 | 2,434 |
| maximum seam (m) | 0.0 | not recorded here | 88.9 | 100.988081 |
| heading-only discontinuities | 82 | 1,334 | 0 | 0 |
| roads checked | 6,807 | not recorded here | not recorded here | 7,208 |

The C34 stage-six report is independently useful but is not substituted for
the final-candidate measurement: it reported 2,461 seams over 7,228 roads,
maximum 100.988081 m, and zero heading-only discontinuities. Its guarded
recompute recorded `updated_geometry_starts=0`; the guard did not repair the
observed seams. Later experimental pipeline stages changed the count to 2,434
in the emitted candidate, but did not restore continuity.

C33 predates the paramPoly3 guard and ran against an earlier code state, so
its 410-seam result is historical context rather than a like-for-like quality
comparison. C34 is the authoritative re-verification for the current guarded
implementation.

## Independent static checks and discrepancy

The clean `regen_map_of_record.py --verify-only` command completed with exit
code zero and no unsafe flags. It reported `valid_for_experiments=True`, with
a warning for 110 isolated lane components. The in-pipeline final acceptance
report instead recorded `valid_for_experiments=False` because its pre-rebase
artifact failed `origin_sanity`, and it recorded 132 isolated lane components.
Both are preserved because the emitted candidate is rebased from global to
local coordinates before clean verification.

More importantly, both generic acceptance paths report their own geometric
continuity gate as passing while the direct internal-planview checker finds
2,434 position seams. This is a coverage discrepancy between validators, not
a pass for heading smoothing. The direct checker is the regression metric used
by C31/C33/C34, and its failure remains fail-closed for this experiment.

## Verdict

**GAP-024: FAIL.** The companion recompute retains the desired elimination of
heading-only discontinuities (82 to 0), but with the paramPoly3 guard it leaves
2,434 real internal position seams, including a 100.988081 m maximum seam.
Neither heading smoothing nor geometry-start recompute may be enabled in a
governed profile on the basis of this result.

## Verification and limits

- Focused offline geometry/gate regression: 104 passed.
- Full offline suite: NOT_RUN. This evidence-only branch uses a sparse
  worktree and the full suite was not required to establish the negative
  experimental result; no code changed in this pass.
- Live CARLA: NOT_RUN.
- No map-of-record, release profile, or frozen evidence mutation occurred.

Raw run artifacts are git-ignored under
`campaigns/ingolstadt_cooked_perception_v1/regen/20260909T102116Z_EXPERIMENTAL_heading_smoothing_v2_recompute/`.
The machine-readable companion is
`C34_HEADING_SMOOTHING_V3_PARAMPOLY3_GUARD_REVERIFICATION.json`.
