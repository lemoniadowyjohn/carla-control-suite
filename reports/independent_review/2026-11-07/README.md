# Independent audit and parallel execution handoff — 2026-11-07

## Read order

1. [Independent source and CI audit](00_INDEPENDENT_AUDIT.md) — source-confirmed defects, CI evidence, scientific limits and ownership.
2. [Codex V24.2 implementation directive](01_CODEX_EXECUTION.md) — bounded production remediation, specialist completion, integration and full verification.
3. [OpenCode IA-V27 parallel directive](02_OPENCODE_EXECUTION.md) — independent negative controls and CI/RQ3 contract evidence without overlapping production implementation.

## Fixed source reference

Audited source: dfa6ffff07c38d0cc09507c52b3328900ef2d900
Original draft: https://github.com/lemoniadowyjohn/carla-control-suite/pull/25
Linux test evidence: https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556

The audit branch is **documentation-only**, based on the V23 review commit. Publication does not certify or merge a fix. Do not treat this branch's HEAD as a new implementation candidate; the implementation tree is inherited from the audited source.

## Immediate priority

P0 — Codex: RQ1 CLI cannot run, helper references absent, broken receipt source.
P0 — Codex: finish T2b/F15b, repair critical locking and process identity failures.
P0 — OpenCode: reproduce RQ1 and classify all 30 CI failures independently.
P1 — Codex with independent tests: reconcile contradictory RQ3 manual/generated map identity and typed validation.
P1 — Codex: source/mirror authority, merge conflicts and full package/integration tests.
P1 — Claude/Codex: geometry review W-F; Codex: W-B RQ5; operator/Codex: W-D original 26-test evidence.
P1 — Operator: assess CI governance PRs #22/#23/#24 and branch protection issue #18.
P1 — Research: distinguish engineering verification from actual RQ1–RQ5 measurements and scientific admission.

## Minimum source-bound verification receipt

- source commit and tree SHA
- base commit / ownership / affected files
- exact command and pytest node IDs
- OS, interpreter and dependency environment
- exit code and PASS/FAIL/SKIP counts
- negative and positive controls
- artifact path and SHA256
- remote CI run URL when applicable
- reviewer decision, unresolved conditions

## Rules

- No Codex/OpenCode concurrent edits in shared production files.
- No force push, default-branch merge, or modification of PR #25 by this audit publication.
- No suppression of correct tests, fake locking fallback, or broad CI/CARLA environmental misclassification.
- No scientific-measurement claims from synthetic fixtures or metadata-only tests.
- Recheck against agent local commits before applying any audit fix.
- Keep remote audit snapshot separate from future corrected source.

## Handoff completion

The audit is available when this folder's files are fetchable from GitHub at the published audit branch. Individual agent completion is a separate matter requiring actual implementation, passing tests and explicit review.
