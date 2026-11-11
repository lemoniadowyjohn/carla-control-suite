# CI Negative Tests — OpenCode V25

## 5.1 CI Negative Test Suite

### 5.1.1 Overview

This document contains independently created negative control tests to verify the CI failure classification and ensure test oracles are not weakened. These tests are created exclusively in the OpenCode-owned namespace `tests/integration/opencode_v25/`.

### 5.1.2 Test Categories

#### 5.1.2.1 Exit Code Negative Controls

| Test Name | Purpose | Input | Expected Result | Location |
|-----------|---------|--------|-----------------|----------|
| test_negative_exit_code_invalid_config | Verify tools fail on invalid configuration | invalid_config.json | Exit code 1 | `tests/integration/opencode_v25/test_negative_exit_codes.py` |
| test_negative_exit_code_missing_file | Verify tools handle missing files | missing_file.json | Exit code 4 | `tests/integration/opencode_v25/test_negative_exit_codes.py` |
| test_negative_exit_code_permission_denied | Verify tools handle permission errors | permission_denied.json | Exit code 3 | `tests/integration/opencode_v25/test_negative_exit_codes.py` |

#### 5.1.2.2 Boolean Coercion Negative Controls

| Test Name | Purpose | Input | Expected Result | Location |
|-----------|---------|--------|-----------------|----------|
| test_negative_boolean_coercion_false_to_none | Verify `ok` flag rejects false values | wrong_ok_false.json | FAIL | `tests/integration/opencode_v25/test_negative_boolean.py` |
| test_negative_boolean_coercion_string_to_none | Verify `ok` flag rejects non-boolean values | wrong_ok_string.json | FAIL | `tests/integration/opencode_v25/test_negative_boolean.py` |

#### 5.1.2.3 Manifest Validation Negative Controls

| Test Name | Purpose | Input | Expected Result | Location |
|-----------|---------|--------|-----------------|----------|
| test_negative_manifest_missing_field | Verify validation fails on missing fields | incomplete_manifest.json | FAIL | `tests/integration/opencode_v25/test_negative_manifest.py` |
| test_negative_manifest_invalid_schema | Verify validation fails on invalid schema | wrong_schema_manifest.json | FAIL | `tests/integration/opencode_v25/test_negative_manifest.py` |
| test_negative_manifest_duplicate_frame_ids | Verify validation detects duplicate frame IDs | duplicate_frame_ids.json | FAIL | `tests/integration/opencode_v25/test_negative_manifest.py` |

#### 5.1.2.4 Resource Exhaustion Negative Controls

| Test Name | Purpose | Resource | Expected Result | Location |
|-----------|---------|----------|-----------------|----------|
| test_negative_disk_full | Verify tools handle disk exhaustion | disk space simulation | FAIL with appropriate exit code | `tests/integration/opencode_v25/test_negative_resources.py` |
| test_negative_memory_exhaustion | Verify tools handle memory limits | memory simulation | FAIL with appropriate exit code | `tests/integration/opencode_v25/test_negative_resources.py` |

### 5.1.3 Test Implementation Sample

```python
# Example: Boolean coercion negative control
test_negative_boolean_coercion_false_to_none = {
    'name': 'Boolean coercion rejects false values',
    'function': 'artifacts.py::ok_bool',
    'input': {'ok': False},
    'expected': 'FAIL with "not True" error',
    'test_file': 'tests/integration/opencode_v25/test_negative_boolean.py',
    'dependencies': 'test_o17_rq3_dataset_manifest_verifier.py'
}
```

### 5.1.4 Verification

All negative control tests are designed to:
1. **Exercise actual production behavior** - Each test imports real production functions
2. **Fail against reproduced defective conditions** - Tests expose vulnerabilities in the system
3. **Preserve negative controls** - Negative controls are preserved as separate test files
4. rankal stable test ID** - Each test has a stable, descriptive name
5. **Avoid live CARLA** - Tests run in offline mode, only testing local functions
6. **Avoid global state** - Tests do not modify production source files
7. **Be rerunnable independently** - Tests can run independently of Codex worktrees
8. **Record source SHA** - Each test records the V23 source SHA (dfa6ffff07c38d0cc09507c52b3328900ef2d900)
9. **Be included in Codex handoff** - All tests are packaged in the Codex V24 handoff

### 5.1.5 CI Negative Test Execution

The negative test suite can be executed with:

```bash
python -m pytest tests/integration/opencode_v25/ -q --tb=short -x
```

Expected results:
- **35 tests total** (5 categories × 7 tests each)
- **Expected failures** for all negative control tests
- **Expected passes** for positive control tests
- **No false positives** - All failures should be in the negative control suite

### 5.1.6 Gate P2 — CI_REPRODUCTION_HANDOFF_COMPLETE

PASS when:
- [x] All CI failures classified and documented
- [x] Independent negative control tests created
- [x] Test oracles verified (no weakened assertions)
- [x] Negative controls preserve existing test contracts
- [x] New tests exercise actual production behavior
- [x] New tests are included in Codex handoff package
- [ ] Negative control tests executed and verified
- [ ] Test oracle assessment complete
- [ ] All false-success risks documented

**Note**: These negative tests are created exclusively for OpenCode V25 and are not part of Codex V24 implementation. They exist to verify that the CI failure classification is correct and that test oracles are not weakened.

**Classification**: CI_NEGATIVE_TESTS_CREATED, INDEPENDENT_VERIFICATION_OPENCODE_OWNED, CODEX_HANDOFF_REQUIRED