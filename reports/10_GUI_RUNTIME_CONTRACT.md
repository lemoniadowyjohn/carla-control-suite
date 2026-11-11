# GUI and Runtime Interface Contracts — OpenCode V25

## 6.1 GUI-to-Backend Contract Matrix

| GUI Action | Backend Service | Expected Response | Failure Mode | Validation Point | Owner |
|------------|-----------------|-------------------|--------------|-----------------|-------|
| Start RQ1 receipt generation | `run_manifest.py` | Exit code 0 + receipt JSON | Non-zero exit code | Exit code verification | OpenCode |
| Cancel RQ1 receipt | `run_manifest.py` with `--cancel` | Exit code 0 + cancellation confirmation | Resource leak / partial receipt | File existence check + size validation | OpenCode |
| View RQ3 manifest status | `rq3_dataset_manifest_verifier.py` | JSON status with PASS/FAIL | Missing file / invalid JSON | File existence + JSON schema validation | OpenCode |
| View RQ1 receipt | `rq1_complete_receipt.py` | JSON with receipt data + SHA256 | Missing receipt / corrupted file | File existence + hash validation | OpenCode |
| View RQ5 experiment status | `run_generalization_experiments.py` | JSON with experiment status | Missing experiment / invalid config | Config validation + file existence | OpenCode |
| View GUI progress | GUI frontend | Progress percentage + status | Stale progress / missing update | Progress calculation + time delta check | OpenCode |
| View terminal receipt | GUI terminal | Text receipt + SHA256 | Truncated / missing receipt | Text length validation + hash verification | OpenCode |

## 6.2 Key Contract Points

1. **Exit Code Contract**: All backend tools must return specific exit codes:
   - `0`: Success
   - `1`: Invalid input/configuration
   - `2`: Resource failure (disk, memory, lock)
   - `3`: Authorization failure
   - `4`: File not found
   - `40`: Manifest validation error

2. **Receipt Contract**: RQ1 receipts must include:
   - Git commit SHA
   - Effective seed
   - Map hash
   - Dataset hash
   - Timestamp
   - SHA256 digest of all artifacts
   - `is True` Boolean validation for critical fields

3. **Manifest Contract**: RQ3 manifest must include:
   - Frame ID sequence validation
   - Timestamp consistency checks
   - Dimension consistency
   - Modality completeness
   - Capture file existence
   - Quality evaluation metrics
   - Map identity verification
   - Sensor transform validation

4. **Resource Contract**: All tools must:
   - Honor single-writer lock (`repo_lock`)
   - Validate input files before processing
   - Clean up temporary files
   - Log execution context (SHA, seed, config)
   - Preserve original input files

## 6.3 Independently Executable Tests

### 6.3.1 GUI-to-Backend Contract Tests (OpenCode-owned)

Create tests in `tests/integration/opencode_v25/gui_contract/`:

1. **Test exit code handling**:
   - Verify `run_manifest.py --help` returns 0
   - Verify `run_manifest.py invalid_config.json` returns 1
   - Verify `run_manifest.py --cancel` returns 0 on valid cancellation

2. **Test receipt generation**:
   - Run `rq1_complete_receipt.py` with valid inputs
   - Verify receipt contains all required fields
   - Verify SHA256 matches expected value
   - Verify `is True` coercion works for `ok` flags

3. **Test manifest verification**:
   - Run `rq3_dataset_manifest_verifier.py` on valid manifest
   - Verify all validation checks pass
   - Verify error handling for missing fields
   - Verify type-safe list checks work

4. **Test negative controls**:
   - Verify tools fail appropriately when:
     - Missing required input files
     - Invalid JSON structure
     - Incorrect exit codes
     - Resource constraints (disk full, memory limit)

### 6.3.2 Runtime Interface Tests

1. **Process lifecycle**:
   - Start backend service
   - Send valid command
   - Verify process exits with expected code
   - Verify cleanup of temporary files

2. **Contract validation**:
   - Test that all required fields are present in outputs
   - Verify data types match specifications
   - Validate hash formats (SHA256)

3. **Resource safety**:
   - Test file locking mechanism
   - Verify temporary file cleanup
   - Test error handling for resource exhaustion

## 6.4 Verification Requirements

- All tests must exercise actual production behavior
- Tests must fail against reproduced defective conditions
- Tests must pass against corrected conditions
- Negative controls must be preserved
- Tests must be rerunnable independently
- Source SHA must be recorded for each test run
- Tests must be included in Codex handoff package

## 6.5 Gate P6 — GUI_CONTRACT_VERIFICATION_READY

PASS when:
- [x] All V23 source files identified and classified
- [x] Mirror drift documented (artifacts.py, gate_runner.py, carla_preflight.py)
- [x] Authoritative source per component determined
- [x] Package parity verified (wheel/sdst from V23 source pass contracts)
- [x] Codex V24 briefed on authority boundaries
- [ ] Codex V24 confirms authority alignment (pending specialist review)
- [ ] GUI contract tests built and executable in OpenCode-owned namespace
- [ ] Runtime interface tests built and executable
- [ ] Negative controls implemented for all critical paths

**Note**: This workstream focuses on contract verification, not implementation. Do not modify backend tools - only validate their behavior through independent tests.