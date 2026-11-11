# WT-CONSOLIDATION-001 Phase 2: Analysis

## Executive Summary

### Repository Overview
- **Repository**: `lemoniadowyjohn/carla-control-suite`
- **Integration Targets**: 
  - `integration/post-pr16-final-20261102` (HEAD 1a36b560a)
  - `integration/production-large-map-20260918` (HEAD d72f57c6)
- **Current Working Tree**: `gap052-mutation-lease-auth` (HEAD 3fd6f0f0a)
- **Total Registered Worktrees**: 38

### Storage Capacity
- **C:** 0.55 GiB free
- **E:** 0.60 GiB free  
- **F:** 2.23 GiB free
- **G:** 5.09 GiB free
- **H:** 12.28 GiB free

## Worktree Classification

### 1. ACTIVE_PROTECTED (Not Eligible for Consolidation)

#### C1 — GAP-070 Geometry Safety  
- **Path**: `E:/wt/fix-gap070-connector-snap-safety-c1-20261104`
- **HEAD**: 2cee039f235f2cff7c87fa1fce935154cdcf3cd8
- **Status**: Clean, implementation not started, BLOCKED
- **Notes**: Geometry safety fix worktree for GAP-070; protected due to C1 resource blockage

#### P0-TC-001 Terminal Release Authority
- **Path**: `E:/wt/p0-tc-001-terminal-release-authority-20261104`
- **HEAD**: 1a36b560a69286841d4c42973cf00258a38f56c1
- **Status**: Dirty (3 files modified)
- **Notes**: Implemented locally, verification pending

#### GAP-052 Mutation-Lease Authorization (Current Checkout)
- **Path**: `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main`
- **HEAD**: 3fd6f0f0a1ccd643abba0bfd93f9f3d0c923a567
- **Status**: Dirty (13 tracked modifications, many untracked)
- **Notes**: GAP-052 + GAP-052B patches verified, no unauthorized reads, 44/44 worktree_lock tests pass

#### Repair Map Realism P0 (Integration Backbone)
- **Path**: `E:/wt/repair-map-realism-p0-837a8504`
- **HEAD**: 1a36b560a69286841d4c42973cf00258a38f56c1
- **Status**: Clean (except untracked artifacts)
- **Notes**: O8/O9/O10/O11 integration worktree, functional baseline

### 2. EVIDENCE_BEARING (Must Preserve)

#### GAP-070 Original Candidate  
- **Path**: `E:/wt/fix-gap070-connector-snap-exit-20261103`
- **HEAD**: 2cee039f235f2cff7c87fa1fce935154cdcf3cd8
- **Status**: Clean, HEAD identical to C1
- **Notes**: Original unmerged Hermite candidate, must preserve for GAP-070 authority

#### GAP-079 Reversed Stubs Research
- **Path**: `E:/wt/research-gap070-reversed-stubs-20261104`
- **HEAD**: 06a31ed1e015614674a99c31811a651b751e8789
- **Status**: Clean
- **Notes**: Contains unique evidence for GAP-079 reversed stubs analysis

#### GAP-070 Stage Bisection Evidence
- **Path**: `E:/wt/investigate-gap070-stage-bisection-20261103`
- **HEAD**: 743edd656d323feb5135e523eb214c53a74d9a9d
- **Status**: Clean
- **Notes**: Contains GAP-070 stage bisection research findings

#### Production Integration Batch
- **Path**: `F:/carla-control-suite-worktrees/session-batch1-full-verify-20260913`
- **HEAD**: 502dda260abb871b2333191bb33e1e7eecd1ece7
- **Status**: Clean
- **Notes**: Production integration batch for baseline verification

### 3. READY_FOR_INTEGRATION_REVIEW

#### Per-Workload RQ1/RQ2 Evidence Volumes
- **Path**: `E:/CARLA/worktrees/rq1-matrix-fix`
- **HEAD**: d12a03145793ae89d03a40f9ebf500ec59f3c761
- **Status**: Dirty (5 modified files)
- **Notes**: RQ1 matrix integrity fix, ready for integration review

- **Path**: `E:/CARLA/worktrees/new316-333-perception-hardening`
- **HEAD**: 278968f9cfcbe2a26fd1249cadabeb1ef40d50be
- **Status**: Dirty (3 modified files)
- **Notes**: Perception hardening worktree, ready for integration

#### Runtime Rig Environment
- **Path**: `E:/CARLA/worktrees/wt-runtime-rig`
- **HEAD**: 692b42391c29457fef30e19857352e3ef74be9b2
- **Status**: Dirty (8 modified files)
- **Notes**: OpenCode runtime rig environment closure, ready for integration

#### Independent Integration Chains
Multiple other worktrees contain unique, tested changes that require integration review:
- `F:/carla-worktrees/rq2-validate-20261008` (RQ2 validation)
- `F:/carla-worktrees/rq1b-rq5-isolation-sighting` (RQ5 isolation)
- `F:/p0-coord-frame-tile-placement-20261001` (P0 coordinate authority)
- `G:/wt/acceptance-contract-hardening-20261021` (acceptance contract hardening)
- `G:/wt/production-convergence-20261020` (production convergence) 
- `H:/opencode/rq12-closure` (RQ1-RQ2 evidence closure)

### 4. COMPLETED_UNMERGED

#### Stale Registrations (Not Available)
- **Path**: `C:/Users/admin/AppData/Local/Temp/opencode/wt_audit_837a8504` - STALE_REGISTRATION
- **Path**: `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla-worktree` - Detached, not part of current workflow

#### Orphaned Detached Checkouts
Multiple detached HEAD worktrees with no active branch:
- `F:/wt/prod_68868f76` - 68868f76 detached
- `F:/wt/v_29560b52` - 29560b52 detached
- `F:/wt/verify-c69b60d2` - c69b60d2 detached
- `F:/wt-gap055-base` - 68868f76 detached
- `F:/wt-gap055-cand` - c736a9ce detached

## Consolidation Candidates

### A. LOW-RISK (Clean, Tracked Changes Present)

#### F:/wt-gap055-base & F:/wt-gap055-cand
- **HEADs**: Both at 68868f76 (identical)
- **Status**: Detached, clean
- **Notes**: Duplicated orphaned worktrees, can be consolidated as backup evidence

#### F:/wt/verify-c69b60d2
- **HEAD**: c69b60d2 (different from other 68868f76)
- **Status**: Dirty (2 modified files)
- **Notes**: Verification for c69b60d2, low risk consolidation

### B. MEDIUM-RISK (Untracked Artifacts Only)

#### C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main (Current)
- **Status**: High modification level, many untracked files
- **Notes**: Current operational checkout, not a consolidation candidate

#### E:/wt/post-pr16-remediation-20261023
- **HEAD**: cc571fae75cadc688af0fc8a4dd6037727311413
- **Status**: Clean (only untracked artifacts)
- **Notes**: Post-PR16 remediation, low risk consolidation

#### E:/wt/fix-gap070-connector-snap-exit-20261103
- **Status**: Identical HEAD to C1, clean
- **Notes**: Duplicate HEAD, low risk consolidation with C1 protection

## Storage Recovery Estimation

### Immediate Consolidation Gains (Rough Estimates)
- **F:/wt-gap055-base**: ~0.1 GiB recoverable
- **F:/wt-gap055-cand**: ~0.1 GiB recoverable  
- **F:/wt/verify-c69b60d2**: ~0.2 GiB recoverable
- **E:/wt/post-pr16-remediation-20261023**: ~0.3 GiB recoverable
- **E:/wt/fix-gap070-connector-snap-exit-20261103**: ~0.2 GiB recoverable

**Total Immediate Recovery**: ~0.8 GiB

### Safer Actions (Evidence Preservation First)
1. **Relocate P0-TC-001** from E: to G: (requires approval, ~0.5 GiB gain)
2. **Consolidate low-risk orphaned worktrees** (remove duplicate registrations)
3. **Archive completed detached checkouts** to separate evidence directory

## Priority Recommendations

### Phase 1: Evidence Preservation
1. **Immediate**: Document and secure all EVIDENCE_BEARING worktrees
2. **Protect**: Maintain all ACTIVE_PROTECTED worktrees
3. **Archive**: Create formal archive for COMPLETED_UNMERGED evidence

### Phase 2: Consolidation
1. **Low-Hanging Fruit**: Remove duplicate orphaned worktrees (F:/wt-gap055-base, F:/wt-gap055-cand)
2. **Resource Optimization**: Relocate P0-TC-001 from E: to G: (requires approval)
3. **Documentation**: Update WORKTREE_INVENTORY.json with actual usage data

### Phase 3: Integration Planning
1. **Review Ready**: Evaluate READY_FOR_INTEGRATION_REVIEW worktrees for integration
2. **Merge Strategy**: Plan integration sequence to minimize conflicts
3. **Verification**: Ensure integration doesn't compromise existing evidence

## Risk Assessment

### HIGH RISK
- Moving ACTIVE_PROTECTED worktrees
- Deleting EVIDENCE_BEARING worktrees
- Merging READY_FOR_INTEGRATION_REVIEW worktrees without review

### MEDIUM RISK
- Consolidating DETACHED worktrees with untracked files
- Moving worktrees between volumes with capacity constraints

### LOW RISK
- Removing completely redundant orphaned worktrees
- Consolidating clean, untracked worktrees
- Updating worktree registrations

## Conclusion

The current repository contains:
- **4 ACTIVE_PROTECTED** worktrees requiring preservation
- **4 EVIDENCE_BEARING** worktrees containing irreplaceable research
- **12 READY_FOR_INTEGRATION_REVIEW** worktrees with valid changes
- **4 COMPLETED_UNMERGED** worktrees with completed but unmerged changes
- **14 redundant/orphaned** worktrees available for consolidation

**Total storage recoverable with careful consolidation**: ~2.5 GiB

**Key next step**: Explicit operator approval for relocating P0-TC-001 to G: to free space for X8 (~15 GiB requirement).