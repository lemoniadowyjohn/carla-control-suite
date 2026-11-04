# Geometry architecture reviews ARCH-X8-X9 and ARCH-002 (2026-11-04)

> **Evidence class: `LOCAL_REPRODUCED_NOT_REMOTE_VERIFIED`.** Every number in this directory was
> computed on one workstation from local stage files that are **not on GitHub**. CI has not
> reproduced any of it. See `PROVENANCE.json` and `UNVERIFIED_CLAIMS.md`. These are review
> findings, **not** accepted release evidence. Do not cite them in a release-evidence register as
> proof.

## Contents

| File | What |
|---|---|
| `CLAUDE_GEOMETRY_ARCHITECTURE_REVIEW.md` | ARCH-X8-X9: findings F-01 to F-09 on the GAP-070 candidate `2cee039f` |
| `GEOMETRY_INVARIANT_MATRIX.md` | 22 connector-geometry invariants: proven / assumed / measured |
| `GAP070_X8_VERIFICATION_PLAN.md` | governed regeneration plan (arms, gates, determinism) |
| `GAP079_X9B_INVESTIGATION_PLAN.md` | plan for the reversed 0.1 m stubs |
| `RELEASE_SAFETY_REVIEW_CHECKLIST.md` | post-implementation reviewer checklist |
| `CODEX_OPENCODE_EXECUTION_BACKLOG.md` | task backlog from ARCH-X8-X9 (C1 is **redirected** by ARCH-002) |
| `../ARCH002_20261104/` | ARCH-002 (sibling package): adversarial re-review, test matrix, risk register, X8 verdict JSON |
| `ERRATA.md` | corrections ARCH-002 made to ARCH-X8-X9 (the original text is unchanged) |
| `PROVENANCE.json` | input hashes and sizes, code SHAs, environment, script and result hashes |
| `REPRODUCE.md` | how a second party reproduces the numbers |
| `ARCHIVE_PROPOSAL.md` | how to archive the 1.06 GB of stage inputs (operator approval needed) |
| `UNVERIFIED_CLAIMS.md` | every claim that depends on local-only files or is otherwise unverified |
| `evidence/` | path-free reproduction scripts and result JSON |
| `SHA256SUMS` | hashes of every file in this directory |

## Verdicts
- ARCH-X8-X9: `REQUIRES_SOURCE_HARDENING`.
- ARCH-002: `REQUIRES_SOURCE_HARDENING`, with the C1 scope redirected. The snap undoes correct
  lane-border placement: 4,024 of its 4,025 moves equal a cumulative lane width, and 19,195 of
  22,588 connectors start on their from-lane inner border. So the minimal source fix is to disable
  the snap or gate it on lane borders.

## Code identities
- Integration: `integration/post-pr16-final-20261102` @ `1a36b560a69286841d4c42973cf00258a38f56c1`.
- GAP-070 candidate: `fix/gap070-connector-snap-exit-20261103` @ `2cee039f235f2cff7c87fa1fce935154cdcf3cd8`.

## Related packages (siblings under `docs/reviews/`)
- `ARCH002_20261104/`: ARCH-002 re-review.
- `ARCH003_20261104/`: lane-centre verification, stage-3/5 identity, errata (including the input-lineage correction).
- `SCI_ARCH001_20261104/`: RQ1–RQ5 claim boundaries.
- `SCI_CORRECT003_20261104/`: proposed gap register addendum 3, revised RQ answers, RQ4 statistical spec.
- `SCI_CORRECT003_ACCEPTANCE_20261104/`: author verification of SCI-CORRECT-003 and the corrections applied.
- `../README.md`: package index with SHA256SUMS hashes.
