# CARLA V26-A/V26-B and IA-V27 — independently verified handoff

**Created:** 2026-11-07  
**Repository:** `lemoniadowyjohn/carla-control-suite`  
**PR:** https://github.com/lemoniadowyjohn/carla-control-suite/pull/25 (OPEN / DRAFT / UNMERGED at inspection)  
**Exact inspected PR HEAD:** `dfa6ffff07c38d0cc09507c52b3328900ef2d900`  
**Evidence CI:** https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556 (PUSH event, HEAD matched; 30 FAILED; release gate SKIPPED)  
**Role separation:** OpenCode = offline verification / OpenCode-owned tests only; Codex = specialist production changes; independent reviewer = admission verdict only.  
**This ZIP is a dispatch pack, not evidence that any task has been executed.**

## Start here
1. Read `audit/00_INDEPENDENT_AUDIT.md`, `audit/01_CI_30_FAILURE_GROUPS.csv`, `contracts/OWNERSHIP_AND_GATES.md`.
2. OpenCode: execute `prompts/OPENCODE_V27_INDEPENDENT_ASSURANCE.md` on a separately owned worktree. Run `prompts/OPENCODE_V27_CONVERGENCE.md` only after receiving actual Codex receipts.
3. Codex: execute `prompts/CODEX_00_COORDINATOR.md`, then delegate the *isolated* T2b, F15b, W-B, W-F, W-D and RQ1/RQ3/CI work described in their respective prompts. Never send two writers to the same worktree or shared source path.
4. Independent reviewer: `prompts/CLAUDE_INDEPENDENT_REVIEW.md` at the exact final candidate SHA.
5. Use `python tools/verify_pack.py` to verify this package. Use `python tools/validate_receipt.py path/to/receipt.json` to check *structure* of a Codex/OpenCode receipt; it does not execute tests or certify truth.

## Evidence classification
- **DIRECT GITHUB VERIFIED**: PR #25 head, exact-head CI job status, 30-failure log, repository source files specified in audit.
- **USER-REPORTED / NOT INDEPENDENTLY VERIFIED**: V26-A and V26-B artifacts under `G:/audit/...`, IA-V27 test files under `C:/Users/admin/...`, 52 local passes, F:/E: specialist worktree states, AUTH-01–AUTH-10 authorization records.
- **NOT EXECUTED HERE**: local/offline pytest, CARLA RPC, UE4 cooking, XODR geometry changes, training, merge/deploy, source fixes. This pack is not approval for any of those actions.

## Important current discrepancy
The PR description and V22 review documents still cite historical SHAs. **Current actual HEAD is `dfa6ffff07c38d0cc09507c52b3328900ef2d900`**; an earlier report's claim that CI was unavailable for the current SHA is incorrect: exact SHA run `https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556` exists, with failure.

## Distribution
All file hashes except the manifest are in `SHA256SUMS.txt`. Preserve the original ZIP and the root manifest. Do not copy local absolute paths into receipts as if their contents had been inspected.
