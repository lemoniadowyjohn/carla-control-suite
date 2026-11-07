# CODEX — V24.1 integration coordinator, authority and dependency gate (no automatic merge)

Read `00_START_HERE.md`, the published V27 ownership/gates contract, and all specialist verdicts. Do not use the missing earlier `CODEX_V24_1_WB_FINALIZATION.md` as a prerequisite: this pack is self-contained. You are **not** the independent W-B reviewer, and cannot self-approve a final candidate.

## Phase 0: read-only forensic baseline
1. On each known **specialist** worktree, record full `git rev-parse HEAD`, `git rev-parse HEAD^{tree}`, `git status --porcelain=v1 -uall`, `git show -s --format=fuller`, `git worktree list --porcelain`, `git rev-parse --git-common-dir`, remotes, branch and unmerged/conflict states. Document process and common-Git lock owner, including machine/process creation time. Never mutate dirty main checkout at reportedly `3fd6f0f0` / ~160 entries.
2. W-B: `git cat-file -t f07efe9765232615b5ebc42ade94b3459bc3d52a` must be commit; `git rev-parse f07efe9765232615b5ebc42ade94b3459bc3d52a^{tree}` must equal `2078f556ff51832f7c86005b12e9b50acdcd51d0`. Record actual 7-file test selection and original log at `G:/tmp/v241-wb-finalization-repro.log`; no need to rerun 100 passing tests on low disk unless independent reviewer requests a safe bounded repro.
3. Resolve candidate `8fcd8c79` to exact 40 hex in local repo and check exact ancestry of W-B, W-F, W-D, T2b `5532424a`, F15b `90badffa`, and any newer RQ1/RQ3 candidate fixes. Distinguish cherry-picked commits, patch identity and source module overlap. If source is not accessible, STOP with `BLOCKED_SOURCE`.
4. Read `G:/audit/CODEX_V24_FINAL_CONVERGENCE/` manifest (17 entries) without modification; validate authentic review and test receipt IDs. Check free bytes on C:/D: and any proposed alternate volume with bounded operations.

## Workstream routing — parallel READ ONLY
- W-B: send `02_CLAUDE_WB_DIFFERENT_FAMILY_REVIEW.md` to an actual **different provider family from Codex**. The earlier incomplete `deepseek-v4.1-flash-free` scan is *not* a verdict. Required reviewer identity, provider family and exact W-B commit/tree in returned artifact; no source writes.
- W-F: send `03_CLAUDE_WF_GEOMETRY_REVIEW.md`; review a **resolved exact** W-F source-generation commit. A final XODR diff alone is insufficient.
- W-D: send `04_WD_OWNER_ACCEPTANCE_RECOVERY.md` to the authentic acceptance/integration owner. No invented original 26 nodeids. Document explicitly approved alternative as a **replacement**, not equivalent to the original.
- Capacity and CI: send `06_CODEX_DISK_CI_PACKAGING.md` to a different nonconflicting runner owner. Read-only size census first; no automatic deletion.
- Independent assurance: OpenCode `05_OPENCODE_INDEPENDENT_GATE_VERIFIER.md` owns only OpenCode test namespaces and new evidence; Codex production work stays separate.

## Integration decision algorithm
A. STOP if missing W-B exact-SHA independent family approval or W-F exact-SHA independent approval. Keep W-B and W-F source isolated.
B. STOP if W-D cannot recover the original 26 test selection and owner has not explicitly approved a named replacement. `RECONSTRUCTED_ACCEPTANCE_CANDIDATE` is not an original suite.
C. STOP if source tree/ancestor or lock ownership ambiguous; do not alter the main checkout or perform an optimistic cherry-pick.
D. STOP if no safe disk/runner or authorization for Git metadata writes. The pack does not authorize a branch push.
E. Only after A-D and explicit scoped integration-owner authorization, create an **owned** integration worktree/branch with an immutable base full SHA and serial Git-metadata lock, apply independently approved commits in documented deterministic order, resolve conflicts without hiding semantic changes, and record resulting new full candidate SHA/tree. Source fixes not yet independently accepted (RQ1 output containment/final-XODR SHA; RQ3 paired map identity contract; T2b and F15b) must remain separate blockers until source/test evidence is admitted.
F. Execute bounded per-workstream RED/GREEN controls first, then original W-D selection or owner-approved replacement, then full-platform and packaging gates through `06`. OpenCode independently verifies final candidate in `05`; Claude reviews final frozen candidate in `07`.
G. No release without exact SHA, no unclassified CI failures, authentic independent verdicts, explicit relevant grants and valid AUTH-08 for candidate publication. Do not force-push/merge/deploy automatically.

## Output
Create new files `V241_COORDINATOR_INVENTORY.json`, `V241_COMMIT_ANCESTRY.md`, `V241_INTEGRATION_DEPENDENCY_MATRIX.csv`, `V241_INTEGRATION_PLAN.md`, `V241_FINAL_GATE_VERDICT.json`, `SHA256SUMS.txt` under a **unique** approved evidence root. All statuses must identify exact owner, origin, proof, blocked cause and next permissible operation. Provide a patch/rollback plan and URLs only after actually existing.

### Mandatory verdict
Until W-B + W-F reviews, W-D authority, safe capacity, full tests, packaging, platform/remote CI, candidate-final review and AUTH grants are satisfied: `PARTIAL_WITH_EXACT_BLOCKERS`; no candidate publication.
