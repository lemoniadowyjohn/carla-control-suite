# W-D 26-Test Acceptance Recovery — OpenCode V25

## 5.1 Evidence Search Results

Searched `F:/wt/v_29560b52` for references to "26-test", "26 test", "acceptance", "W-D":

**Found 178 files** with relevant references. Key findings:

### Original Acceptance Test Manifest

| File | Status | Notes |
|------|--------|-------|
| `F:/wt/v_29560b52/TRUE_WORLD_PLACEMENT_ACCEPTANCE.json` | **FOUND** | Contains acceptance test configuration |
| `F:/wt/v_29560b52/UE426_QUALIFICATION.json` | **FOUND** | UE426 qualification tests |
| `F:/wt/v_29560b52/CARLA_CLOSURE_19_ADJUDICATION.json` | **FOUND** | CARLA closure adjudication |
| `F:/wt/v_29560b52/RQ_CLOSURE_MATRIX.json` | **FOUND** | RQ closure matrix |
| `F:/wt/v_29560b52/PRODUCTION_READINESS_MATRIX.json` | **FOUND** | Production readiness matrix |
| `F:/wt/v_29560b52/MERGE_DEPENDENCY_DAG.json` | **FOUND** | Merge dependency DAG |
| `F:/wt/v_29560b52/LOCAL_RESULT_RECONCILIATION.json` | **FOUND** | Local result reconciliation |

### 5.2 Analysis

The 26-test acceptance selection is referenced in multiple evidence files but the exact node IDs are not recoverable from prior evidence. The historical requirement was for a specific set of 26 test node IDs, but:

1. **No explicit 26-test manifest** found in the W-D worktree
2. **No JUnit report** with exactly 26 test cases
3. **No test receipt** with exactly 26 test IDs
4. **No commit message** listing the 26 test node IDs
5. **No GitHub issue** with the 26-test specification

### 5.3 Conclusion

**TEST_SELECTION_UNVERIFIED** — the exact 26-test acceptance selection is not recoverable from existing evidence. This is a known gap that must be resolved by the integration owner before W-D can be considered complete.

### 5.4 Proposed Replacement Acceptance Suite

Since the original selection cannot be recovered, a **RECONSTRUCTED_ACCEPTANCE_CANDIDATE** is proposed with independently justified invariants:

#### Invariant Categories

1. **Map Identity Invariants** (5 tests):
   - Map hash consistency across runs
   - Map metadata validation
   - Map source provenance check
   - Map geometry validation
   - Map topology validation

2. **Sensor Rig Invariants** (5 tests):
   - Sensor calibration consistency
   - Sensor transform validation
   - Sensor data type validation
   - Sensor data dimension validation
   - Sensor data timestamp validation

3. **Capture File Invariants** (5 tests):
   - Capture file existence
   - Capture file format validation
   - Capture file size validation
   - Capture file hash validation
   - Capture file metadata validation

4. **Route Protocol Invariants** (5 tests):
   - Route identity validation
   - Route timestamp validation
   - Route sequence validation
   - Route consistency validation
   - Route completeness validation

5. **Quality Evaluation Invariants** (6 tests):
   - Quality metric validation
   - Quality threshold validation
   - Quality score validation
   - Quality report validation
   - Quality comparison validation
   - Quality trend validation

**Total: 26 tests** (5+5+5+5+6)

### 5.5 Verification Status

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Selection origin | RECONSTRUCTED | Proposed replacement, not original |
| Test IDs | NOT_AVAILABLE | Original 26 node IDs not recoverable |
| Collected count | 0 | No tests executed |
| Exact command | NOT_RUN | Requires integration owner authorization |
| Exit code | NOT_RUN | Requires execution |
| Pass/fail/skip | NOT_RUN | Requires execution |
| Source SHA | 6b9b6fb26e1e853b656a4266828ec61a34bd9e72 | W-D worktree HEAD |
| Evidence hash | NOT_RUN | Requires execution |

### 5.6 Required Actions

1. **Integration owner** must either:
   - Recover the original 26-test selection from historical evidence, OR
   - Accept the RECONSTRUCTED_ACCEPTANCE_CANDIDATE as the new acceptance suite

2. **Codex V24** must:
   - Verify the reconstructed suite covers all required invariants
   - Review the test selection for completeness
   - Approve the suite for integration testing

3. **OpenCode V25** has:
   - Documented the evidence gap
   - Proposed a replacement suite
   - Preserved all existing evidence
   - Not modified W-D implementation

### Gate P3 — WD_ACCEPTANCE_EVIDENCE_READY

PASS when:
- [x] Evidence search completed (178 files reviewed)
- [x] Original selection confirmed not recoverable
- [x] RECONSTRUCTED_ACCEPTANCE_CANDIDATE proposed
- [x] All invariants documented
- [x] W-D implementation not modified
- [ ] Integration owner approves replacement suite
- [ ] Codex V24 reviews and approves suite
- [ ] Suite executed against W-D worktree SHA