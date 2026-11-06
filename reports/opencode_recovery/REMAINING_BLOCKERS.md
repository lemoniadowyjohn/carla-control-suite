# Remaining Blockers — 2026-10-21

## Blocked by Storage Admission Gate (External Dependency)
- **Need**: ≥20 GiB free on generation volume (C: 4.90, E: 4.16, F: 2.22, G: 9.11, H: 15.70 — none meet gate).
- **Action required**: External disk expansion, worktree consolidation (30 worktrees protected — cannot remove automatically), or archive relocation.
- **Status**: Not executable by agent.

## Blocked by No Complete Candidate
- **Need**: Full pipeline regeneration through stage 08_final with current source fixes (`f0c83285`) and admitted conditions.
- **Dependency**: Storage admission gate + no active competing pipeline.
- **Status**: Pipeline `20261021_171332_417792` (run4) complete but stale; `20261021_175215_009531` (run7) crashed at stage 2 (matplotlib); no 08_final with current fixes.

## Blocked by Independent Review-A
- **Need**: Auditor agent must independently verify P0-A/B/C/E gates and certify `STATIC_MAP_REMEDIATION_PASS`.
- **Dependency**: Complete 08_final candidate.
- **Status**: Not certified (agent must not self-certify).

## Blocked by Review-B / Import-Ready / Cook-Ready / Load-Ready / Drive-Ready
- **Need**: UE build, CARLA runtime, native capture rigs.
- **Dependency**: Review-A passed.
- **Status**: Not started.

## Blocked by GitHub Convergence (PR + Merge)
- **Need**: Push `repair/map-realism-p0-837a8504` (commit `f0c83285`) to remote and open PR against `integration/production-large-map-20260918`.
- **Dependency**: Review-A + Review-B passed + CI green.
- **Status**: Not pushed (authorization pending); remote `repair/map-realism-p0-837a8504` remains at `35b3e5d1`.

## Blocked by RQ3 / RQ5 Launch
- **Policy**: Not authorized (`AGENTS.md` explicitly: "Do not start RQ3/RQ5").
- **Status**: Blocked by instruction.

## Blocked by Full Semantic Provenance Ledger Materialization
- **Need**: Consolidated provenance ledger (not scattered artifacts) + building identity roundtrip tests.
- **Dependency**: Pipeline produces semantic artifacts (traffic_sign objects, building objects) with source IDs preserved.
- **Status**: Source code fixed (`stage_04/09` pass `positioned_ways`); pipeline must run with fix first to generate provenance evidence.

## Blocked by Negative-Control P0-A / P0-B Gate Verification
- **Need**: `tools/validate_candidate.py` does not exist as standalone; gates enforced by stage-capability contract (`stage_capabilities.py`) + `repo_health.validate_candidate_manifest()`.
- **Status**: Contract validated at pipeline start (`STAGE-CONTRACT` passes); full gate verification requires complete final XODR.
