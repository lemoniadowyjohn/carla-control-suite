# OpenCode V25 Blockers and Approvals

## 1. W-D 26-Test Acceptance Evidence Gap
- **Status**: RECONSTRUCTED_ACCEPTANCE_CANDIDATE
- **Description**: The original 26-test acceptance selection is not recoverable from prior evidence.
- **Evidence**: 178 files reviewed, no explicit 26-test manifest found.
- **Proposal**: RECONSTRUCTED_ACCEPTANCE_CANDIDATE with 26 invariants (5 map + 5 sensor + 5 capture + 5 route + 6 quality).
- **Action Required**: Integration owner must approve the replacement suite or recover original selection.

## 2. RQ5 - 3 Remaining Commits Pending
- **Status**: PARTIALLY_COMPLETE
- **Location**: Codex W-B worktree (F:/carla-worktrees/rq5-sightb-20261009)
- **Details**: 2/5 commits completed, 3 remaining commits pending.
- **Action Required**: Complete remaining RQ5 commits in Codex worktree.

## 3. Terminal Lease Authority Pending
- **Status**: OPEN_DELEGATED
- **Location**: Codex T2b worktree (E:/wt/prod_68868f76)
- **Details**: Terminal lease authority implementation pending.
- **Action Required**: Complete terminal lease implementation in T2b worktree.

## 4. Artifact Certification Pending
- **Status**: OPEN_DELEGATED
- **Location**: Codex F15b worktree (F:/wt-gap055-base)
- **Details**: Artifact certification implementation pending.
- **Action Required**: Complete artifact certification in F15b worktree.

## 5. Geometry Review Required
- **Status**: REQUIRES_CHANGES
- **Location**: W-F worktree (E:/wt/research-gap070-reversed-stubs-20261104)
- **Details**: Geometry review comments from Claude/Codex need resolution.
- **Action Required**: Resolve geometry review comments before W-D validation.

## 6. Candidate b Publication Pending
- **Status**: AUTH_PENDING
- **Location**: Candidate b worktree (G:/wt/candidate-approved-20261105)
- **Details**: Requires operator authorization (AUTH-08).
- **Action Required**: Operator must authorize Candidate b publication.

## 7. CI Failure Classification
- **Status**: COMPLETE
- **Classification**: All observed CI failures are PLATFORM_INCOMPATIBILITY (CARLA unavailable in Linux CI).
- **Evidence**: 5/6 CI jobs pass; offline tests fail due to CARLA unavailability.
- **No action needed** - this is a platform limitation, not a code defect.

## 8. Source Authority Verification
- **Status**: COMPLETE
- **All V23 source files identified and classified**
- **Mirror drift documented** (artifacts.py, gate_runner.py, carla_preflight.py)
- **Authoritative source per component determined**
- **Package parity verified** (wheel/sdst from V23 source pass contracts)

## 9. RQ1-RQ5 Evidence Status
- **RQ1**: OFFLINE_VERIFIED - Tooling fixed, receipt defects resolved
- **RQ2**: IMPLEMENTED - Tooling complete, measurements pending
- **RQ3**: OFFLINE_VERIFIED - Tooling fixed, manifest gaps resolved
- **RQ4**: OFFLINE_VERIFIED - Tooling complete, no live measurements
- **RQ5**: PARTIALLY_COMPLETE / BLOCKED_EXTERNAL - 3 commits pending, live eval pending

## 10. W-D 26-Test Acceptance
- **Status**: RECONSTRUCTED_ACCEPTANCE_CANDIDATE
- **Evidence**: 26 test invariants documented with independent justification
- **Action Required**: Integration owner approval required before execution