# Integration Dependency Graph — OpenCode V25

## Dependency Graph (P1)

### Nodes (commit-range scope)

| Node | SHA | Source | Owner | Changed Files | Integrated Into |
|------|-----|--------|-------|---------------|-----------------|
| BASE | c69b60d2fe4ac018136ea0fa26e435a09c15dd73 | integration/post-pr16-final-20261102 | integration | — | shared |
| V23 | dfa6ffff07c38d0cc09507c52b3328900ef2d900 | review/v21-consolidation-audit-20261106 | OpenCode | 67 files | PR #25 |
| T2b | varies | E:/wt/prod_68868f76 | Codex | lease authority | PENDING |
| F15b | varies | F:/wt-gap055-base | Codex | artifact certification | PENDING |
| W-F | varies | E:/wt/research-gap070-reversed-stubs-20261104 | Claude/Codex | geometry | REQUIRES_CHANGES |
| W-B | varies | F:/carla-worktrees/rq5-sightb-20261009 | Codex | RQ5 experiment orchestration | PARTIALLY_COMPLETE |
| W-D | 6b9b6fb26e1e853b656a4266828ec61a34bd9e72 | F:/wt/v_29560b52 | Integration owner | acceptance tests | TEST_SELECTION_UNVERIFIED |
| Candidate b | 71e222af05979ec8ab246801d047b52ef29aa1e2 | G:/wt/candidate-approved-20261105 | Operator | separate publication | AUTH_PENDING |

### Dependency Edges

| From | To | Type | Evidence |
|------|----|------|----------|
| BASE | V23 | prerequisite | V23 built on BASE + V22 Boolean fixes |
| V23 | T2b | shared contract | both use `ultimate_pipeline/contracts/artifacts.py` |
| V23 | F15b | shared contract | both use `gate_runner.py`, `stage_contracts.py` |
| V23 | W-F | shared contract | W-F uses geometry contracts from core |
| V23 | W-B | shared contract | RQ5 uses experiment registry |
| T2b | F15b | semantic dependency | terminal lease authority -> artifact certification gate |
| T2b | W-B | semantic dependency | RQ5 uses terminal lease for experiment execution |
| F15b | W-B | semantic dependency | artifact certification feeds RQ5 validation |

### Semantic Conflicts (not line-level)

1. **artifacts.py `ok` coercion** — V23 added `is True` strict coercion on `artifacts.py`. Codex T2b terminal-lease work may read artifact `ok` flags directly.
   - Risk: MEDIUM
   - Action: verify T2b doesn't bypass `is True` pattern

2. **gate_runner.py exit-code semantics** — V23 changed release gate behavior; F15b fail-closed certification may depend on specific exit codes.
   - Risk: HIGH
   - Action: Codex must confirm exit-code contract before merging

3. **carla_opendrive_loader.py mirror drift** — P4 workstream identified duplicate loaders; interface may diverge between production and submission mirrors.
   - Risk: MEDIUM
   - Action: source-authority check before merge

4. **RQ5 experiment orchestrator vs single-writer lock** — W-B writes checkpoints; single-writer lock serializes writers.
   - Risk: MEDIUM
   - Action: verify checkpoint writes honor writer lock

### Integration Recipe (hypothesis, to be verified)

```
BASE
→ V23 changes (verified, PASS)
→ T2b terminal lease (Codex; gated on artifacts.py contract)
→ F15b artifact certification (Codex; gated on gate_runner exit codes)
→ shared contract verification (OpenCode: artifacts.py, gate_runner.py)
→ W-B RQ5 (Codex; after T2b lease)
→ eligible geometry (after W-F REQUIRES_CHANGES resolved)
→ W-D validation (integration owner; after 26-test selection recovered)
```

### Rollback/Abort Guidance

- Each node is independent unless marked with a shared-contract dependency.
- If T2b changes conflict with V23 `artifacts.py`, abort T2b and review contract.
- If F15b exit-code contract diverges from gate_runner.py, abort F15b and re-align.
- Never force-merge specialist-owned branches; resolve semantic conflicts in separate review.
