# CARLA IA-V27 — GitHub agent dispatch

**Handoff pack:** [CARLA V26/V27 independently audited handoff](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/README.md)  
**Repository:** `lemoniadowyjohn/carla-control-suite`  
**Inspected PR:** [#25](https://github.com/lemoniadowyjohn/carla-control-suite/pull/25)  
**Source baseline SHA:** `dfa6ffff07c38d0cc09507c52b3328900ef2d900`  
**Evidence CI:** [run 42292278556](https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556) (failed; 30 failed, 7911 passed; release gate skipped).

This branch publishes **only documentation, verification contracts, and local receipt validator tools**. It does not implement CARLA changes or certify local V26 claims, scientific readiness, runtime success, CI repairs or authorization grants.

## OpenCode — first execution
1. Read [pack README](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/README.md), [independent audit](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/audit/00_INDEPENDENT_AUDIT.md), [ownership/gates](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/contracts/OWNERSHIP_AND_GATES.md), and [adversarial negative controls](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/contracts/NEGATIVE_CONTROLS.md).
2. Execute **[OPENCODE_V27_INDEPENDENT_ASSURANCE](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/prompts/OPENCODE_V27_INDEPENDENT_ASSURANCE.md)** in an isolated agent-owned worktree and test namespaces. Must verify actual current SHA and reported local artifact bytes first.
3. Output exact RED results, node IDs, environment, authorization and hashes; no production changes, no scientific PASS extrapolation.
4. After Codex has returned verified correction commits and receipts, execute [OPENCODE_V27_CONVERGENCE](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/prompts/OPENCODE_V27_CONVERGENCE.md).

## Codex — subsequent/owned source corrections
1. Execute **[CODEX_00_COORDINATOR](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/prompts/CODEX_00_COORDINATOR.md)**. Freeze current repository/worktrees and verify single writer and operator authorization.
2. Delegate only disjoint changes as indicated in [Codex's task-specific prompts](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/prompts/).
3. Prioritize RQ1/RQ3 executable defects, T2b writer safety, F15b certification, then W-F/W-B and W-D dependency-gated integration. Maintain no-merge/no-force-push/no-live-CARLA/no-threshold-change rules.
4. Return isolated commits and exact test receipts. Do not edit OpenCode test namespaces or assert independent approval.

## Independence and package verification
From repository root:
```bash
python agent_handoffs/CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/tools/verify_pack.py
python agent_handoffs/CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/tools/validate_receipt.py agent_handoffs/CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/contracts/receipt_template.json
```
The manifest covers 22 files (everything inside the pack except SHA256SUMS itself). These checks prove file integrity/schema only. No CARLA tests are run by this publication.

**Mandatory final gate:** independent Claude/human [architectural review](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/prompts/CLAUDE_INDEPENDENT_REVIEW.md) of the exact final implementation SHA before any release consideration. PR #25 remains draft and untouched.
