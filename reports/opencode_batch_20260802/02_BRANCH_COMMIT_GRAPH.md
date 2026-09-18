# 02_BRANCH_COMMIT_GRAPH.md

**Generated:** 2026-08-02
**Coordinator:** Prompt 01 — Campaign Coordinator

## Linear history of the integration branch (latest 20)

```
e9ff5986 (HEAD, integration/governed-map-quality-20260729)  Phase A: audit normalization (registry 232 IDs, strict status logic, per-profile release effects, manifest verification)
572f25e9  Phase A2: Correct status logic - A2.1
dac6930a (origin/integration/governed-map-quality-20260729) docs(governance): DSV14 cleanup — CRS tag, carla_osm2odr_version stays UNKNOWN_UNSOURCED
f6448fc7 docs(reports): DSV13 B4 provisioning runbook (WSL2 -> UE4.26 -> CARLA 0.9.16 -> cook smoke test)
2fdc8e50 docs(governance): DSV12 bind converter_profile, carla_osm2odr_version, crs_contract_hash in campaign manifests
953ae945 docs(governance): DSV11 AG07 re-verification #2 -> BLOCKED_TOOLCHAIN, C55V01b authorized
ac43fe23 docs(governance): DSV09 ledger refresh + DSV07/08/10 verification reports
7506128d docs(reports): DSV03-06 read-only verification sweep (LFS integrity, hygiene, XODR summary, B4 preflight)
64139d3b chore(lfs): track ingolstadt_cooked_perception_v1 XODR/OSM candidates via LFS
d6cd4e0b docs(governance): stage C55V01a CRS candidates
c264e0c8 docs(governance): record C55V01a donor decisions
f94b2195 docs(tools): document enter_carla.ps1 bootstrap
6a5ab3ca feat(governance): add C44V01 coordinate-contract verifier
a7919117 docs(vxr): coordinator R0 + visual/XODR campaign delegation (READY_TO_RUN_LOW_COST_DISCOVERY)
02bdc100 docs(architecture_gate): re-verify P4 gate @ d4b0fe14
d4b0fe14 docs(governance): align published tip references
1884d9d0 docs(governance): bind ledger and prompt status to current base
867811c4 feat(governance): finalize canonical writer-lock contract
b6c09340 docs(hooks): add P2 fresh-hook verification evidence (FCH01 PASS)
59c36ce6 docs(hooks): add P2 fresh-hook verification runbook
```

## Anchor commits

| Anchor | SHA | Role |
|---|---|---|
| Audited commit | `dac6930a` | LOW_COST_MODEL_AUDIT_20260801 assessment target |
| Phase A2 | `572f25e9` | status-logic sample (superseded by e9ff5986) |
| Phase A complete | `e9ff5986` | **current build base** |
| Prior hardening worktree | `b07e2db7` (branch fix/post-audit-production-hardening-20260801) | reference artifacts at reports/post_audit_hardening/20260801T231300Z |
| origin tip | `dac6930a` | integration branch ahead 2 (both Phase A commits, unpushed) |

## Notable other branches (provenance)

- `audit/gemini31pro-audit` @ d202ad22 — full repo audit with issue register
- `fix/deepseek-observability-integration-verification` @ deb261bf — governance observability
- `fix/claude-hooks-lock-governance-20260730` @ ee8871c8 — active hooks
- `verification/map-quality-hardening-20260729` @ 687a69a0 — full-fix evidence reports
- `backup/fv-baseline-20260729-ff00099` @ ff00099d — G01 cross-compare evaluator baseline

## Unmerged/not-in-integration state

- Prior hardening branch `fix/post-audit-hardening-20260730` sits at `dac6930a` (no commits); its worktree contains a Phase A/B evidence set that is NOT in git (untracked) — reviewed, superseded by this batch's Phase A (committed).
- No unmerged production commits exist outside the integration branch for this batch's scope.
