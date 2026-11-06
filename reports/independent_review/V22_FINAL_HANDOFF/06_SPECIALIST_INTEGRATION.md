# V22 SPECIALIST INTEGRATION

## B1 — T2B (Terminal Authority)

**Owner**: Codex
**Worktree**: `E:/wt/prod_68868f76`
**HEAD**: `9c1489fb0ab9b55efb78d68043ce826803932269`
**Dirty**: `ultimate_pipeline/governance/single_writer/worktree_lock.py`, `tests/unit/test_worktree_lease_race.py`
**Status**: **OPEN_DELEGATED**

**Overlap Assessment with V21 source**:
- V21 `main_pipeline.py` already contained V15-B fencing logic
- T2b extends with lease race and terminal authority boundaries
- No direct conflict identified in V22 audit; dirty state must be committed before integration

**Integration Requirements**:
1. Commit T2b dirty changes to specialist branch
2. Verify lease + terminal authority tests pass
3. Run stale-owner negative controls
4. Reconcile with V21 artifact/terminal authority

---

## B2 — F15B (Artifact Certification)

**Owner**: Codex
**Worktree**: `F:/wt-gap055-base`
**HEAD**: `f94e085a535249e630df66b6509354f5872d2013`
**Dirty**: 4 files (85 insertions, 5 deletions)
**Status**: **OPEN_DELEGATED**

**Overlap Assessment with V21 source**:
- V21 F15b already includes artifact authority changes
- V22 fix to `extract_elevation_stats.py` overlaps with F15b dem QC paths
- Changes to `bool()` → `is True` are semantically stricter and should be reviewed for consistency with F15b fail-closed design

**Integration Requirements**:
1. Commit F15b dirty changes
2. Verify mandatory negative controls pass
3. Verify V17 compatibility
4. Confirm release/artifact authority consistency

---

## W-F GEOMETRY REVIEW

**Owner**: Claude / Codex
**Worktree**: `E:/wt/research-gap070-reversed-stubs-20261104`
**HEAD**: `48d86d763fb03c297320f6a03a3935c212aa7d4c`
**Status**: **REQUIRES_CHANGES** (historical verdict)

**Integration Requirements**:
1. Locate historical review comments on geometry findings
2. Address reversed connector, lane-link direction, stub issues
3. Add regression tests for: lane-link direction, connector reversal, missing/duplicate connectors, junction connectivity, lane geometry consistency
4. Obtain independent review verdict allowing integration

---

## W-B RQ5 REMAINING COMMITS

**Owner**: Codex
**Worktree**: `F:/carla-worktrees/rq5-sightb-20261009`
**HEAD**: `345a422e71ca9e50cf5b1138a3bd489e10d63b5d`
**Status**: **PARTIALLY_COMPLETE**

**Integration Requirements**:
1. Complete remaining 3 implementation commits
2. Add lightweight RQ5 acceptance tests (16 scenarios listed in B7)
3. Run source-bound tests

---

## W-D INTEGRATION VERIFICATION

**Owner**: OpenCode (verify) / Operator (merge)
**Worktree**: `F:/wt/v_29560b52`
**HEAD**: `6b9b6fb26e1e853b656a4266828ec61a34bd9e72`
**Status**: **PENDING** — 26-test acceptance suite not yet executed

**Integration Path**:
1. Execute documented 26-test selection on `F:/wt/v_29560b52`
2. Create isolated disposable integration-preview worktree
3. Apply approved source changes in dependency order
4. Run affected regressions + 26-test selection
5. Verify source identity

---

## Candidate b — PR Publication

**Owner**: Operator
**Worktree**: `G:/wt/candidate-approved-20261105`
**HEAD**: `71e222af05979ec8ab246801d047b52ef29aa1e2`
**Status**: **READY** (pending authorization)

**Integration Requirements**:
1. Verify candidate b branch state
2. Obtain explicit push authorization
3. Publish separate draft PR
4. Do not publish candidate b via V22 review-branch workflow

---

## Integration Dependency Graph

```
V21 Base (3fd6f0f0) → V12-V15 fixes → Boolean fixes (V22) → T2b/F15b → W-F → W-B → W-D → Candidate b → Publication
```

---

## Source Overlap Assessments

| Pair | Overlap | Assessment |
|------|---------|------------|
| T2b / V21 | Governance fencing | Need conflict resolution |
| F15b / V21 | Artifact authority | Need V17 compatibility check |
| W-F / V21 | Map quality | REQUIRES_CHANGES pending fixes |
| W-B / V21 | RQ5 evidence | PARTIALLY_COMPLETE |
| W-D / V21 | Acceptance tests | Integration preview pending |