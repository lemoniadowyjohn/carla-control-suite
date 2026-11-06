# OPENCODE — IA-V27 independent reproduction and regression assurance

## OPERATOR PARALLEL EXECUTION DIRECTIVE

Repository: lemoniadowyjohn/carla-control-suite
Audited baseline: dfa6ffff07c38d0cc09507c52b3328900ef2d900
Published independent report: reports/independent_review/2026-11-07/00_INDEPENDENT_AUDIT.md
Primary implementation owner: Codex V24.2
Operator campaign output: G:/audit/OC_AUTONOMOUS_CONVERGENCE/IA_V27_ADVERSARIAL_ASSURANCE/

## 0. Mission

Execute *in parallel* with Codex as the independent test/evidence owner. Do not modify Codex-owned production paths, lease/certification source, experimental protocol or PR #25. Do not repeat the full V25 report. Your value is direct failing tests, source-bound reproduction, cross-contract test fixtures, and a concise Codex handoff that eliminates investigative ambiguity.

Read AGENTS.md and inspect current ownership/locks/storage first. Use a separate OpenCode-only worktree and test namespace. Work against a fixed, recorded source revision; refresh findings once Codex publishes verified commits. Do not execute a second broad 8k-test suite concurrently with Codex.

## P0 — OA-01: prove RQ1 entrypoint and helper failures

Audit paths:
- tools/rq1_complete_receipt.py
- research/thesis_rq_contract.yaml
- downstream rq1_run_receipt consumers

At published baseline, the script lacks the __main__ guard, references normalized_xodr before initialization and calls absent or misnamed helper functions. Provide read-only source AST/import analysis plus *production entrypoint* reproduction.

Build isolated fixture approach that exercises script execution with map/pipeline external dependencies replaced only at their real boundaries. Assert:
- direct python script invocation starts main and writes expected receipt;
- a no-op invocation is never treated as PASS;
- invalid map input returns nonzero;
- pipeline exception remains nonzero and cannot emit successful scientific receipt;
- run index and source identity are correct;
- changed effective settings alter settings_hash;
- geometry structural signature is not merely identical to input byte hash in all cases;
- missing mandatory stages/digests are rejected according to official contract;
- receipt canonical digest round trips and detects tampering;
- interrupted publication cannot leave a trusted success.

Record all defects as CONFIRMED_SOURCE unless actually reproduced as runtime; distinguish missing production function from mocks/test setup issues. Do not repair Codex-owned receipt generator yourself. Deliver tests and acceptance criteria.

## P0 — OA-02: correct RQ3 contradictory contract with real typed fixtures

Audit paths:
- tools/rq3_dataset_manifest_verifier.py
- tools/rq3_pairing_preflight.py
- configs/rq3_protocol_freeze_v1.json

The published paired manifest verifier requires equal map_identity, while the pairing preflight requires distinct manual and generated worlds. Existing unit fixture sets almost all required fields to "value" and passes.

Construct one authoritative truth table from frozen protocols (no unreviewed protocol change):

- valid distinct manual/generated map IDs + shared rig/route/seed/weather/class-map: expected valid pairing;
- same map arm masquerading as independent: reject;
- changed route, weather, rig, class-map: reject according to exact contract;
- missing map hash or unknown source: reject/incomplete;
- wrong types: string instead of timestamps list, dimensions list, modalities list; reject;
- empty fields, NaNs, duplicate frames, missing timestamps: reject;
- missing/nonexistent/changed capture files and optional digest behavior: correctly classified;
- paired manifests with same map_identity under distinct-identity-required protocol: reject;
- valid paired metadata with actual quality evaluation NOT_RUN: NOT SCIENTIFICALLY ADMITTED.

Add small direct tests calling *both* real validator functions, not just helpers. Preserve the two-arm distinction. Do not rewrite the frozen protocol or supply fabricated capture results.

Publish failing tests in an OpenCode-owned test-only branch only if separately authorized; otherwise preserve local commits and provide Codex integration patches.

## P0 — OA-03: independently classify all 30 CI failures

Reference CI:
https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556

Extract every failing pytest node ID and exact assertion. The V25 blanket conclusion PLATFORM_INCOMPATIBILITY/CARLA unavailable is incorrect.

Classify individually:
- expected failure due to unsupported OS;
- real production logic defect;
- test expectation contradicting approved strict contract;
- cross-platform handling defect;
- mirror/source authority drift;
- synchronization/concurrency bug;
- genuinely external CARLA blocker;
- unverified hypothesis.

Preserve counts and source SHA; verify root cause, not test-name guess.

Priority negative controls:
A. Common Git lock exactly one winner under contention; no PID-only fencing.
B. Live lease cannot be reconciled, stale lease requires explicit reconciliation.
C. Windows mutex and Linux counterpart must either implement safe actual locking or explicitly reject unsupported OS; no fake permissive fallback.
D. Quality gate accepts literal True only if official contract says so; malformed truthy inputs cannot elevate state.
E. Wrong or missing source mirror must not silently be imported; clean installed wheel must resolve authoritative module.
F. Storage reservation handles Linux mounts and Windows drive discovery without false resource PASS.

Avoid editing affected Codex production files. Deliver minimal independent regressions and targeted test commands. Avoid full-suite duplication.

## P1 — OA-04: scientific and provenance test-oracle strengthening

RQ1 analyzer repeatability on identical XML is not repeat independent generation. Tag test scope accordingly; propose full RQ1 experiment acceptance tests that must run later.

RQ2 wrong CRS currently produces equal StructureScanner summaries; document as confirmed scanner limitation. Test authoritative CRS preflight with known disjoint coordinate systems and valid aligned geometry. Require wrong CRS reject rather than silently comparing numbers in incompatible frames.

RQ4 check graph IDs, edge referential integrity, split overlap/data leakage, seed provenance and checkpoint identity with tiny fixtures.

RQ5 check training/validation/test split separation, checkpoint provenance, correct target map, invalid/NaN metrics, missing evaluation and stale result certification. No GPU training, no CARLA launch and no changes to Codex W-B implementation.

Distinguish synthetic negative controls from scientific measurements.

## P1 — OA-05: versioned independent remediation scoreboard

Recheck actual upstream Codex source and PR branch when updated; classify findings:
NOT_FIXED
FIX_IN_PROGRESS
LOCALLY_TESTED
INTEGRATED_TESTED
REMOTE_CI_VERIFIED
BLOCKED_REVIEW
BLOCKED_RUNTIME
NOT_APPLICABLE.

Never automatically mark a bug fixed because a new commit exists. Reproduce positive and negative tests on exact source. Do not make Codex wait for a giant report: deliver small incremental, consumable handoff packets after each high-value confirmed finding.

Review CI governance PRs #22/#23/#24 and issue #18 at read-only scope. Report known dependency/rollout facts; do not modify shared workflows or settings.

## Required artifacts

G:/audit/OC_AUTONOMOUS_CONVERGENCE/IA_V27_ADVERSARIAL_ASSURANCE/
  00_START_HERE.md
  01_RQ1_EXECUTION_NEGATIVE_CONTROLS.md
  02_RQ3_TWO_ARM_CONTRACT_MATRIX.csv
  03_RQ3_TYPED_FIXTURE_TESTS.md
  04_CI_30_FAILURE_RECONCILIATION.csv
  05_LOCKING_PLATFORM_TESTS.md
  06_RQ1_RQ2_SCIENTIFIC_BOUNDARIES.md
  07_RQ4_RQ5_LINEAGE_TESTS.md
  08_CODEX_V24_2_HANDOFF.md
  09_IMPLEMENTATION_STATUS.md
  10_TEST_RECEIPTS.jsonl
  11_FINAL_VERDICT.md
  verification.json
  SHA256SUMS.txt

Include actual test source files under isolated owned test paths, exact command/node IDs, platform, source SHA/tree, exit codes and reproducible fixture hashes. Create no placeholders and no invented original W-D 26-test selection.

## Safety and completion

No production edits in Codex worktrees; no merges, force pushes or branch protection changes; no uncontrolled test state/caches; no live CARLA/model training. Preserve errors and unique evidence. Before writing any new source, verify canonical ownership and explicit permission. Test-only commits are permitted in your isolated owned workspace; public push requires independent operator authorization.

A pass means that source-level claims have independent reproduction/test cases, the 30 CI failures are correctly classified, RQ3 paired test contracts are noncontradictory, and Codex has a clear patch/test acceptance handoff. It does **not** mean RQ1–RQ5 scientific admission or production readiness.

EXECUTE OPENCODE IA-V27 IN PARALLEL WITH CODEX V24.2.
