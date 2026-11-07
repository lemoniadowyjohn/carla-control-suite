# CARLA V24.1 — final-gate recovery dispatch (v2, 2026-11-07)

**Purpose:** operationally resolve V24.1 review, acceptance, capacity, CI and publication blockers without confusing focused source verification with release approval.

## Immutable references and confidence boundaries
- Repo: `lemoniadowyjohn/carla-control-suite`. GitHub PR #25: https://github.com/lemoniadowyjohn/carla-control-suite/pull/25; as of 2026-11-07 open/draft/unmerged at `dfa6ffff07c38d0cc09507c52b3328900ef2d900`. That PR is an **older independent reference**, not the local V24.1 integration candidate.
- Published V27 governance contract: https://github.com/lemoniadowyjohn/carla-control-suite/blob/a862b3ec1d165763e70a5ddd16e8d769e44cec84/agent_handoffs/CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/contracts/OWNERSHIP_AND_GATES.md
- Local W-B HEAD **reported verified by operator**: `f07efe9765232615b5ebc42ade94b3459bc3d52a` with Git tree `2078f556ff51832f7c86005b12e9b50acdcd51d0`; worktree clean. Remote GitHub API could not resolve this commit on the inspected repo; require local `git cat-file` verification.
- W-B seven-file suite **operator-reproduced** at exact commit: `100 passed, 0 failed, 6 warnings`, exit 0, 28.05 s. Raw log `G:/tmp/v241-wb-finalization-repro.log`; warnings: five missing optional worktree-local settings paths, one `torch_geometric.distributed` deprecation. Do not accidentally adopt obsolete earlier 35.95s timing or 2/2/2 warning classification.
- Original V24 convergence audit `G:/audit/CODEX_V24_FINAL_CONVERGENCE/`: operator verified 17 manifest entries, all matching; independent reviewer should rehash bytes.
- Candidate **reported** abbreviated SHA `8fcd8c79`; resolve full 40-hex SHA locally. W-F exact correction commit and W-D original 26 acceptance test nodeids must be discovered from local evidence; do not invent them.
- Main checkout last reportedly `3fd6f0f0` with ~160 status entries; no touching its HEAD, index or working files.
- Disk free: C: ~455 MB, D: ~548 MB. Do not run heavy suites or package builds without measured safe headroom.
- Different-provider-family review of W-B is PENDING. Prior Codex review and interrupted DeepSeek/OpenCode analysis do not count. W-F review PENDING; W-D original suite unrecovered; full suite/wheel/sdist/Linux and hosted exact-SHA CI NOT EXECUTED; AUTH-08 not verified; no publication.

## Dispatch order and concurrency
Read-only work may proceed **in parallel**: (1) Claude independent W-B reviewer `02`, (2) separate Claude W-F geometry reviewer `03`, (3) W-D integration owner recovery `04`, (4) disk/runner census in `06`. All work must use bounded filesystem access with explicit source identity. **Do not** mutate shared Git metadata concurrently; a faulty or absent common lock requires explicit human serial execution.

Only after reviews, acceptance authority, disk headroom and source ownership can Codex coordinator `01` prepare a new, separately authorized candidate; OpenCode `05` independently challenges all gates. `07` is final independent candidate review after source/tree is frozen.

### Operational prompts
- `01_CODEX_INTEGRATION_COORDINATOR.md` — one authoritative read-only plan, conditional code integration and all gates.
- `02_CLAUDE_WB_DIFFERENT_FAMILY_REVIEW.md` — distinct provider family independent exact-commit W-B approval, or REQUIRES_CHANGES.
- `03_CLAUDE_WF_GEOMETRY_REVIEW.md` — independent W-F geometry/source-stage review.
- `04_WD_OWNER_ACCEPTANCE_RECOVERY.md` — authentic original 26 test selection recovery / alternative owner approval.
- `05_OPENCODE_INDEPENDENT_GATE_VERIFIER.md` — verify facts, negative controls and candidate readiness independently.
- `06_CODEX_DISK_CI_PACKAGING.md` — approved resource plan, full suite/packaging/Windows/Linux/remote CI.
- `07_CLAUDE_FINAL_CANDIDATE_REVIEW.md` — final exact-candidate independent veto review.
- `08_EVIDENCE_RECEIPT_TEMPLATE.json`, `09_INITIAL_GATE_MATRIX.csv`, `verify_pack.py`, `SHA256SUMS.txt` — machine-readable templates and pack hash verifier.

## Universal STOP conditions and evidence policy
No `git clean`, `git reset`, main checkout switch, force-push, protected branch merge, candidate publication, destructive disk cleanup, history rewrite, threshold increase, post-hoc final-XODR masking, unauthorized live CARLA/UE operations or model training. No Codex edits in OpenCode-owned tests; no OpenCode production changes. Never infer AUTH-08 from authoring this prompt. Never treat a local reviewer start without complete verdict as approval. Do not overwrite 17-entry historic manifest or earlier run logs.

For every action: record exact full commit/tree SHAs, branch/worktree identity, authorizing grant, argv/cwd/OS/Python, UTC timestamps, real process exit code, test nodeids and counts, raw log/JUnit hashes, warnings, blocked reason and source/evidence file paths. Use new unique evidence directory only on a **measured capacious** volume; otherwise write small text receipts in approved scratch space or return `BLOCKED_ENV_DISK`. Do not invent receipts.

Status taxonomy: `NOT_EXECUTED`, `BLOCKED_ENV_DISK`, `BLOCKED_SOURCE`, `BLOCKED_AUTH`, `PENDING_REVIEW`, `REQUIRES_CHANGES`, `FOCUSED_VERIFIED_LOCAL`, `INDEPENDENT_REVIEW_APPROVED_EXACT_SHA`, `ACCEPTANCE_AUTHORIZED`, `CANDIDATE_INTEGRATED`, `FULL_SUITE_VERIFIED`, `PACKAGING_VERIFIED`, `LINUX_CI_VERIFIED`, `WINDOWS_NATIVE_VERIFIED`, `REMOTE_CI_VERIFIED`, `PUBLICATION_AUTHORIZED`, `RELEASED`. A gate passes only with its own primary evidence. A skipped test is never PASS.

## Hard release dependency
W-B independent approval + W-F independent approval + W-D authentic acceptance authority + safe disk/runner capacity + exact-source-scoped changes + original and new negative controls + full suite + package build + platform-specific tests + exact-SHA hosted CI + independent final review + relevant grants (including AUTH-08 for candidate publication) must each have distinct receipts. Publication and merge require separate authorization and are not authorized by this pack.
