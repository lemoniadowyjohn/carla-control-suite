# CODEX — V24.2 independent-audit remediation and verified integration

## OPERATOR EXECUTION DIRECTIVE

Repository: lemoniadowyjohn/carla-control-suite
Primary review PR: https://github.com/lemoniadowyjohn/carla-control-suite/pull/25
Audited baseline: dfa6ffff07c38d0cc09507c52b3328900ef2d900
Published source audit: reports/independent_review/2026-11-07/00_INDEPENDENT_AUDIT.md
Concurrent verifier: OpenCode IA-V27 in separate test-only worktree
Scope: continue existing Codex V24/V24.1 work; do not restart completed tasks.

## 0. Governing principles

Read AGENTS.md and the audit, verify the live Git HEAD and all active worktree owners, then use the audit to create a current source-bound defect matrix. The published audit is evidence tied to an earlier SHA; reproduce against current local changes before fixing. Preserve all unique dirty worktree changes and the V25 test/report package. Do not reimplement an already-corrected function or duplicate OpenCode tests.

Allowed: Codex-owned source edits, tests and logical commits in owned worktrees, isolated integration preview, validated non-force push to a separate Codex review branch under existing operator authorization.
Not allowed: force push; direct merge to main/research; modifications to OpenCode's test-only worktree; rewriting PR #25; deleting worktrees, changing branch protection or using live CARLA/paid model runs without separate approval.

## 1. P0: restore executable RQ1 receipt generator (IA-001)

Path: tools/rq1_complete_receipt.py

In the audited revision the script contains no CLI invocation guard; helper definitions _sha256, _hash_dict, _compute_feature_counts, _compute_topology_counts, _compute_tileset_digest and _compute_map_acceptance_digest were deleted but calls remain. normalized_xodr is accessed before assignment. _git_commit_hash is defined but the caller invokes git_commit_hash.

Treat as a direct source-level failure. Do not accept the earlier V23 "6 defects fixed" completion claim without verifying production path.

Required:
A. Restore coherent helper definitions/imports from authoritative version or implement bounded, tested replacements.
B. Initialize normalized_xodr deterministically; distinguish produced file from fallback path.
C. Restore executable if __name__ == "__main__": raise SystemExit(main()).
D. Validate all helper references with a static AST/compile check as supplementary evidence.
E. Run a direct subprocess invocation against a small mocked/pinned fixture; assert the script actually executes, outputs a receipt, and returns the correct exit code. Use injected test doubles only at actual external map/pipeline boundaries, not the receipt-writing logic.
F. Test failure paths: missing map, failed MainPipeline, invalid/sanitizer failure, missing required outputs, invalid source identity and corrupt receipt.
G. Ensure failures cannot emit a success receipt.
H. Preserve failure details while not exposing secrets.

Acceptance: real CLI entrypoint test + real main-function tests + negative controls all green on the exact modified SHA.

## 2. P0/P1: fix RQ1 receipt scientific provenance (IA-002)

Verify schema rq1_run_receipt/v1 against all consumers before changing its fields.

- Hash effective settings actually passed to MainPipeline, not global SETTINGS.
- Do not conflate input-file SHA with structural geometry signature.
- Preserve map/source hashes and correct run_index.
- Define mandatory versus optional per-stage digests, output artifact digests and stage results.
- Reject unknown Git identity if source authority is required; if diagnostic mode permits unknown, status must be INCOMPLETE/UNVERIFIED, not scientific PASS.
- Canonicalize digest computation with documented exclusion of the digest field itself; verify round-trip independently.
- Use crash-safe atomic receipt publication if required by canonical artifact authority.
- Avoid duplicating T2b/F15b terminal state logic; integrate with it through the existing contract.

Tests: different run indices; changed effective settings; same geometry with different XML serialization; changed geometry; missing/modified output; interrupted write; wrong source SHA; replayed receipt; empty metrics. Explicitly show which experiments remain NOT_RUN.

Acceptance: scientifically meaningful receipt schema, no false-success negative controls, no fabricated measurements.

## 3. P0: finish T2b and F15b with safe ownership (IA-009)

T2b worktree: E:/wt/prod_68868f76
F15b worktree: F:/wt-gap055-base

First preserve all existing uncommitted changes; record branch, HEAD, tree and dirty state.
T2b: exclusive single writer, stable process identity (PID plus creation time where required), creation/reuse, fencing token, stale and live lease, renewal, crash recovery, handoff and terminal publication authority.
F15b: literal PASS only, required evidence, content-hash verification, source/run/candidate identity, stale artifact rejection, safe publication, no PASS after lease loss, cancellation or failed stage.
Run independent negative controls for each, commit logically, then test combined T2b/F15b behavior in an isolated integration tree. Never let a producer's success override a certification failure.

## 4. P0: all 30 broad CI failures (IA-005)

Reference run: https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556
Audit counts: 7,911 passed / 30 failed / 73 skipped / 3 xfailed.

Enumerate all failed node IDs from current logs. Do not attribute all failures to missing CARLA. Group root causes and address:
- true Boolean quality-gate normalization versus an obsolete truthy-pass test;
- core/carla_opendrive_loader.py source/submission mirror drift;
- Windows C: assumption in storage test/implementation on Linux;
- common Git lock race with two concurrent winners;
- PID and process-creation-time identity;
- live lease reconciliation improperly accepted;
- Windows CreateMutexW invoked with no Windows backend on Linux, plus cross-platform arbitration;
- any remaining failures or cascades.

For each: reproduction, source-level root cause, approved invariant, failing regression, correction, positive/negative test and platform. Do not solve by blanket skip, xfail, mocks that always succeed, or weakened security assertions.

If Windows-specific testing is only valid on Windows, separate Windows acceptance from Linux behavior; an unsupported-platform verdict must be explicit and must not masquerade as verified Windows arbitration.

Acceptance: full set of failing node IDs accounted for, mandatory broad suite green on corrected final candidate, and Windows-only safety behaviors verified on Windows.

## 5. P1: unify RQ3 contracts and typed input admission (IA-003 and IA-004)

Paths: tools/rq3_dataset_manifest_verifier.py and tools/rq3_pairing_preflight.py.

The published manifest verifier rejects different paired map_identity while the preflight requires distinct manual/auto world identities. Reconcile with frozen RQ3 experimental protocol; distinguish map-specific identity (must differ for two arms) from shared rig/route/weather/seed/class map (must match as applicable). Do not silently equate distinct maps.

Replace string "value" fixtures with realistic typed two-arm manifests. Reject wrong types and empty required fields for frame IDs, timestamps, modalities, dimensions, map identity, transforms, route, weather and seeds. Verify missing capture files and claimed checksums according to the actual contract. Model-quality evaluation must stay NOT_RUN until measured. Do not treat manifest PASS as perception quality PASS.

Tests: valid distinct worlds; same-arm invalid; mismatched rig/route/weather/class map; malformed types; null/empty values; duplicate frames; timestamp mismatch; nonexistent or modified capture; different sensor resolutions where not allowed. Preserve versioned schema and compatibility where justified.

## 6. P1: source parity, merge conflicts and package integrity (IA-006)

PR #25 is draft, mergeable=false (dirty), with 67 changed files at audited SHA. Determine actual merge base and conflict files. Identify authoritative modules and mirrors, including core/carla_opendrive_loader.py. Establish production module resolution under source, editable and clean-wheel environments.

Construct isolated integration worktree from correct research base; reconcile verified V23, T2b/F15b and eligible W-B/W-F/W-D changes by actual source identity and dependency ordering. Document semantic conflicts, not only textual conflicts.

Do not rewrite PR #25 or merge into shared integration/main. Run tests on combined tree after each high-risk integration. Rebuild clean wheel/sdist and verify CLI imports/entrypoints and no shadowed modules.

## 7. P1: W-B, W-F and W-D (IA-009)

W-B: F:/carla-worktrees/rq5-sightb-20261009 — recover actual required remaining commits and implement only approved scope; validate dataset/checkpoint/source provenance, no train/eval leakage, correct failure status. No expensive training without operator approval.

W-F: E:/wt/research-gap070-reversed-stubs-20261104 — recover actual REQUIRES_CHANGES review comments; reproduce junction/lane connector issues; make bounded fixes only when design authority is clear; retain Claude independent design review requirement.

W-D: F:/wt/v_29560b52 — recover exact historical 26-test acceptance manifest; if unavailable, label TEST_SELECTION_UNVERIFIED and propose reviewed replacement rather than fabricating original 26 tests; execute the actual source-bound suite when recovered.

Candidate b remains an independent publication/integration decision. Do not silently incorporate it.

## 8. P1: scientific claim boundaries (IA-008/009)

Read research/thesis_rq_contract.yaml and applicable frozen protocols.

- RQ1: analyzing identical XML twice is analyzer repeatability, not independently regenerated-map determinism. Require repeated full runs before scientific repeatability claims.
- RQ2: StructureScanner's CRS-blind test documents a gap; add or integrate authoritative CRS comparability preflight, synthetic known SE(2)/known-coordinate tests and actual result attribution.
- RQ3: typed paired-manifest validity is not perception-quality evaluation.
- RQ4: graph/data split/latent metrics and leakage must be validated; no invented training evidence.
- RQ5: generated-to-manual accuracy and real-world transfer require actual evaluation data, not manifest-only approval.

Publish a RQ1–RQ5 claim matrix with IMPLEMENTED, OFFLINE_VERIFIED, RUNTIME_READY, MEASURED, SCIENTIFICALLY_ADMITTED, NOT_RUN and BLOCKED_EXTERNAL. No thresholds changed for expedience.

## 9. P1: governance and CI rollout (IA-007)

PRs: #22 lockfile trigger, #23 investigator incomplete diagnostic, #24 Actions SHA pins. Open issues #18–#21. Verify their current status, base, checks and dependency order; do not duplicate existing fixes or merge them without authorization.

Main and research branch protection was disabled at audit. Produce an operator-ready protection policy (review count, required checks, restricted force-push, status requirements); do not change repository settings without separate explicit approval.

## 10. Integration acceptance and independent review

Mandatory source-bound gates:
G0 source/worktree authority
G1 executable RQ1 CLI and receipt integrity
G2 T2b lease/fencing authority
G3 F15b artifact certification
G4 combined terminal-artifact authority
G5 RQ3 schema/pairing contracts
G6 CI failures disposition and Linux/Windows matrix
G7 source/mirror/package parity
G8 W-B/W-F/W-D verified or individually blocked
G9 RQ1–RQ5 scientific evidence accurately classified
G10 full applicable offline suite
G11 clean wheel/sdist/CLI test
G12 reviewed draft integration candidate
G13 remote CI on exact published SHA

Record PASS/FAIL/BLOCKED/NOT_RUN per gate. PASS requires actual command, test IDs, exit code, platform, full SHA and tree, evidence file and checksum. Do not use an older test receipt to certify a newer tree.

## 11. Deliverable package

In G:/audit/CODEX_V24_FINAL_CONVERGENCE/INDEPENDENT_AUDIT_CLOSURE/ create:
00_START_HERE.md
01_SOURCE_AND_OWNERSHIP.md
02_RQ1_EXECUTION_REPAIR.md
03_RQ1_RECEIPT_CONTRACT.md
04_T2B_LEASE_VERIFICATION.md
05_F15B_CERTIFICATION.md
06_RQ3_CROSS_CONTRACT_MATRIX.md
07_ALL_30_CI_FAILURES.csv
08_CI_REPRODUCTIONS.md
09_MODULE_PARITY_AND_MERGE.md
10_WB_WF_WD.md
11_RQ1_RQ5_CLAIM_MATRIX.csv
12_GOVERNANCE_HANDOFF.md
13_COMBINED_TEST_RECEIPTS.jsonl
14_GITHUB_REVIEW_STATUS.md
15_FINAL_VERDICT.md
verification.json
SHA256SUMS.txt

Preserve V24/V25 history. When ready and separately permitted by your existing V24 operator scope, publish only a clean, security-scanned new Codex review branch, verify remote HEAD, open draft PR and record exact URLs. Do not overwrite audit/independent-source-20261107 or PR #25.

## FINAL EXECUTION PRIORITY

1. Reconcile current SHA/ownership and read audit.
2. Fix executable RQ1 source breakage first.
3. Finish T2b/F15b and combined authority.
4. Reproduce and fix 30 CI failures (including concurrency).
5. Resolve RQ3 map identity/schema in coordination with independent OpenCode tests.
6. Correct source/mirror/package drift and integrate in isolated branch.
7. W-B/W-F/W-D and scientific acceptance.
8. Run full applicable tests, package smoke, remote CI.
9. Deliver independent review candidate with explicit remaining blockers.

Status must be REQUIRES_CHANGES until applicable gates genuinely PASS. No invented successes, no broad skip/xfail shortcuts, no live science claims from synthetic tests.

EXECUTE CODEX V24.2 AS THE ACTIVE IMPLEMENTATION OWNER.
