# Independent CARLA Control Suite audit — 2026-11-07

## Audit authority and limits

Repository: https://github.com/lemoniadowyjohn/carla-control-suite
Audited published revision: dfa6ffff07c38d0cc09507c52b3328900ef2d900
Draft review PR: https://github.com/lemoniadowyjohn/carla-control-suite/pull/25
Remote Linux CI: https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556

This is an independent **read-only GitHub source/CI audit**. It does not imply local test execution, inspection of unpublished Codex/OpenCode worktrees, live CARLA runtime, or scientific admission. Reconfirm source fingerprints before applying fixes, because other agents may have newer local commits.

## Executive verdict

**REQUIRES_CHANGES.** Substantial development and verification progress is real, but the published V23 RQ1 receipt implementation contains clear source defects; RQ3 has contradictory pairing semantics; broad CI fails on locking, source authority, platform assumptions and quality-gate tests; draft PR #25 has unresolved conflicts; scientific RQ1–RQ5 qualification remains incomplete. The blanket V25 finding that all CI failures are from unavailable CARLA is unsupported.

## Verified achievements

- V12–V15, V22 strict-status and V23 RQ1/RQ3 changes appear in the published commit chain (not just summaries).
- A comprehensive draft PR (#25) exists with 67 changed files and approximately 8,582 additions and 5,558 deletions.
- At audited SHA, broad Linux pytest reported **7,911 passed, 30 failed, 73 skipped, 3 xfailed**. Five other jobs (evidence, provenance, package/wheel, thesis contract, governance) succeeded; offline release gate skipped.
- Draft PRs #22 and #23 provide separate CI investigator improvements with relevant green checks; PR #24 supplies Actions pinning but has failing CI.

## Findings / accountable remediation

### IA-001 | P0 | Broken RQ1 executable entrypoint and helpers | Codex

Path: tools/rq1_complete_receipt.py
Commit introducing reported V23 repair: dc0fc811a919c3499a7861110ff95d919eb6d708

- The published file lacks the if __name__ == "__main__" invocation, so executing the script does not call main().
- The source calls missing helpers: _hash_dict, _sha256, _compute_feature_counts, _compute_topology_counts, _compute_tileset_digest and _compute_map_acceptance_digest.
- normalized_xodr is referenced before assignment.
- _git_commit_hash is defined but git_commit_hash is called.
- Main path cannot produce a complete receipt as claimed.

Acceptance: after restoring valid helper authority and entrypoint, run a direct subprocess CLI against a bounded fixture; verify exit code, full required receipt content and failure behavior. Do not mark RQ1_RECEIPT_VERIFIED based on imports or neighboring tests.

### IA-002 | P1 | RQ1 scientific-provenance defects | Codex / research reviewer

- settings_hash is generated from SETTINGS rather than the effective settings object passed to MainPipeline.
- structural_signature is populated with input-file SHA rather than structural geometry signature; byte hash and structural signature are distinct metrics.
- per_stage_hashes is empty; Git identity may become unknown.
- Structural output measurements and missing artifact semantics require explicit schema decisions.

Acceptance: source-bound complete receipt with canonical effective-settings hash, correct structural signature and mandatory digest policy; corrupted/missing source/artifacts fail closed. Keep actual repeated generation (RQ1) NOT_RUN until performed.

### IA-003 | P1 | RQ3 map-identity contradiction | Codex + OpenCode test-only + scientific reviewer

Paths:
- tools/rq3_dataset_manifest_verifier.py
- tools/rq3_pairing_preflight.py

Manifest verifier currently rejects differing paired map_identity, while pairing preflight requires distinct manual and auto expected_map_identity. Define whether fields denote map-specific identity or shared experiment identity; align both consumers with one versioned schema.

Acceptance: valid manual/auto pair with distinct map identity and common rig/route/weather/seed PASSes both validators. Same-arm, wrong route, wrong rig, wrong class map and unknown map must fail. Do not weaken scientific comparability.

### IA-004 | P1 | RQ3 typed validation and weak unit fixture | OpenCode tests, Codex contract integration

Existing test fixture populates most REQUIRED fields with the string "value", and paired identical fixtures PASS. Type checks only activate when input is already list/dict. Malformed sensor_timestamps, modalities, image_dimensions and partial capture metadata can pass validation. capture_files path presence alone is not file existence/content certification.

Acceptance: authoritative typed manifest schema; realistic two-arm fixtures; missing/invalid/empty fields fail; capture file paths/hashes validated according to protocol; quality comparison remains NOT_RUN until metrics actually executed.

### IA-005 | P0/P1 | Broad CI fails, not solely due to CARLA absence | Codex, OpenCode independent reproduction

At SHA dfa6ffff, broad CI reported 30 failures, including:
- quality-gate contract test expecting legacy truthiness;
- duplicate module drift in core/carla_opendrive_loader.py;
- Windows drive C: expectation on Linux;
- common Git lock test reporting two simultaneous winners;
- process creation-time and live/stale lease identity failures;
- Windows CreateMutexW invocation on Linux and failed single-writer concurrency cases.

Acceptance: enumerate all 30 failed pytest node IDs; classify independently by actual root cause; preserve security-sensitive invariants; repair production or test contract with direct negative controls; run actual Linux suite and genuine Windows coverage for Windows-only claims. No broad CI PASS until exact candidate's required checks succeed.

### IA-006 | P1 | Source authority, mirror parity, incomplete integration | Codex

PR #25 has draft merge conflicts; source/submission mirror drift is explicitly detected in CI. Do not resolve by copying files without establishing authoritative source and runtime package inclusion. Compare semantic overlaps across V23, T2b, F15b, W-B, W-D and W-F. Use isolated integration preview, not direct merge into main or research.

Acceptance: one source authority for each module, correct packaged imports, actual zero-conflict or reviewed conflict resolution on integrated tree, broad integration regressions, source-bound receipts.

### IA-007 | P1 | Branch/CI governance | Operator + CI owner

At audit, main and integration/post-pr16-final-20261102 reported protected=false. Issue #18 remains open. Draft PRs #22/#23 address issue #19/#21 in the investigator; PR #24 addresses part of #20 but had failed CI.

Acceptance: no blind merges or protection bypass; review dependency order of #22/#23 into #17, fix CI of #24, set owner-approved required branch protections and checks. Governance is incomplete until actually enforced.

### IA-008 | P1 | RQ1/RQ2 tests overstate scientific scope | Codex + research reviewer

RQ1 negative-control test performs structural analysis twice on one literal XODR fixture, not two independently generated maps. RQ2 wrong-CRS test explicitly documents that StructureScanner produces identical structural reports for differing CRS. These are useful bounded unit observations, not full pipeline repeatability or CRS safety.

Acceptance: label unit-test scope accurately; add true CRS preflight that rejects invalid comparability; perform independent generation and correct RQ2 metric admission under the frozen protocol before scientific claims.

### IA-009 | P1 | Remaining delegated engineering | Codex/Claude/Operator

- T2b: terminal single-writer lease authority and fencing.
- F15b: artifact certification and fail-closed final receipts.
- W-F: geometry REQUIRES_CHANGES, obtain actual review findings.
- W-B: complete actual remaining RQ5 implementation commits.
- W-D: recover/approve actual 26-test selection and run.
- Candidate b: separate publication and review gate; never silently merge into V23.
- RQ1–RQ5: distinct tooling, runtime measurement and scientific-admission states.

Acceptance: every blocker has owner, source SHA, signed-off implementation/test evidence and explicit NOT_RUN/BLOCKED where applicable.

## Recommended ownership and order

1. Codex: IA-001 and IA-002 first; repair RQ1 operational entrypoint before making additional science claims.
2. Codex: finish T2b/F15b and restore correct CI locking semantics.
3. OpenCode (test-only): IA-003/IA-004 typed paired-manifest adversarial fixture + CI negative-control harness; no production overlap.
4. Codex: integrate RQ3 contract, source/mirror parity, W-B/W-F/W-D as evidence permits.
5. Operator/reviewer: branch-protection policy, review PR #22/#23/#24, independent review, and separate scientific experiments.

## Acceptance / reporting standard

Every "fixed" assertion must identify production file/function, parent and result SHA, exact test node IDs, positive and negative controls, command, platform, exit code, source tree hash, and CI run on that SHA. Distinguish SOURCE_CONFIRMED from LOCALLY_REPRODUCED and REMOTE_CI_VERIFIED. Do not merge, force-push, overwrite protected worktrees or claim runtime/scientific qualification from synthetic tests.

## Evidence limitations

The above findings are tied to the published SHA shown at top; unpublished local Codex/OpenCode work may already contain fixes. Do not claim those are absent until examined. No live CARLA or full repository tests were run by the independent auditor. Original standalone audit file exists separately in the user's ChatGPT conversation; this GitHub version is the authoritative cross-agent handoff as published on the independent audit branch.
