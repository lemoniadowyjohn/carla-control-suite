# OPENCODE EVIDENCE COLLECTION PROMPT — COMPLETE
**Campaign:** CARLA 0.9.16 Closure Audit & RQ3 Gate Fix Verification
**Date:** 2026-10-22
**Scope:** Complete evidence collection from all local worktrees for independent verification

---

## 1. EXACT WORKTREE STATES, COMMIT GRAPHS & TRACKING REFS

### Command Suite — Run on EACH worktree
```bash
# Worktree: E:\wt\repair-map-realism-p0-837a8504 (repair branch)
cd E:\wt\repair-map-realism-p0-837a8504
git status --porcelain=v1 -uall
git log --oneline --graph --all -30
git branch -vv
git remote -v
git worktree list --porcelain
cat .agent_locks/writer.lock
cat .agent_locks/*.lock 2>/dev/null

# Worktree: C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main (integration)
cd C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
git status --porcelain=v1 -uall
git log --oneline --graph --all -30
git branch -vv
git remote -v
git worktree list --porcelain

# Worktree: F:\carla-control-suite-worktrees\session-batch1-full-verify-20260913
cd F:\carla-control-suite-worktrees\session-batch1-full-verify-20260913
git status --porcelain=v1 -uall
git log --oneline --graph --all -30
git branch -vv
```

### Expected Outputs
- Complete `git status --porcelain=v1 -uall` for each worktree
- Full commit graph showing all branches and their relationships
- Tracking refs showing upstream/downstream relationships
- Writer lock states with timestamps and final SHAs

---

## 2. FULL LOCAL RQ3 SOURCE DIFFS & MISSING COMMITS

### Command Suite
```bash
# On repair worktree
cd E:\wt\repair-map-realism-p0-837a8504
git diff 9e777a27..HEAD -- ultimate_pipeline/perception/
git diff 9e777a27..HEAD -- ultimate_pipeline/augmentation/
git diff 9e777a27..HEAD -- ultimate_pipeline/tests/unit/test_rq3_*.py
git diff 9e777a27..HEAD -- configs/rq3_protocol_freeze_v1.json
git diff 9e777a27..HEAD -- ultimate_pipeline/perception/rq3_evidence_gate.py
git diff 9e777a27..HEAD -- ultimate_pipeline/perception/rq3_capture_contract.py
git diff 9e777a27..HEAD -- ultimate_pipeline/perception/experiment_map_pair_authority.py

# Show all commits not on integration
git log --oneline 69c818be..HEAD
git log --oneline 35b3e5d1..HEAD  # vs remote repair branch

# Verify specific commits
git show 67d3b357 --stat
git show 4ee3327c --stat
git show 41526907 --stat
git show 19a48fb0 --stat
git show 61769519 --stat
git show a3773070 --stat
git show 020063d9 --stat
git show 1e902986 --stat
```

### Expected Artifacts
- Complete diff output for all RQ3-related files
- List of all commits on repair branch not on integration
- SHA-256 of each commit's tree

---

## 3. RAW TEST LOGS, ENVIRONMENT FINGERPRINTS & FAILING TEST

### Command Suite
```bash
# On experimental branch
cd E:\wt\repair-map-realism-p0-837a8504
git checkout experimental/verified-fixes-20261022

# Full test run with verbose output
C:\temp\py312_venv\Scripts\python.exe -m pytest \
  ultimate_pipeline/tests/unit/test_rq3_artifact_content_verification.py \
  ultimate_pipeline/tests/unit/test_rq3_builder_false_pass_regression.py \
  ultimate_pipeline/tests/unit/test_rq3_paired_capture_contract.py \
  ultimate_pipeline/tests/unit/test_rq3_frame_set.py \
  -v --tb=long 2>&1 | tee test_full_log_20261022.txt

# Individual test runs
C:\temp\py312_venv\Scripts\python.exe -m pytest \
  ultimate_pipeline/tests/unit/test_rq3_artifact_content_verification.py::test_artifact_integrity_checks \
  -v --tb=long 2>&1 | tee test_failing_20261022.txt

# Environment fingerprint
C:\temp\py312_venv\Scripts\python.exe -c "
import sys, platform, json
print(json.dumps({
    'python_version': sys.version,
    'platform': platform.platform(),
    'executable': sys.executable,
    'pip_freeze': __import__('subprocess').run(['pip', 'freeze'], capture_output=True, text=True).stdout
}, indent=2))
" > env_fingerprint_20261022.json

# CARLA version
C:\temp\py312_venv\Scripts\python.exe -c "
import carla; print('CARLA:', getattr(carla, '__version__', 'no version attr'))
"
```

### Expected Artifacts
- `test_full_log_20261022.txt` — complete verbose test output
- `test_failing_20261022.txt` — detailed failing test traceback
- `env_fingerprint_20261022.json` — Python, platform, pip freeze
- CARLA version confirmation

---

## 4. REVIEW RECEIPTS & DATASET MANIFEST BINDINGS

### Command Suite
```bash
# On repair worktree (has phase5 deliverables)
cd E:\wt\repair-map-realism-p0-837a8504
ls -la reports/phase5_deliverables/

# Verify each receipt
cat reports/phase5_deliverables/RQ3_EVIDENCE_RECEIPT_20261022_9e777a27.json
cat reports/phase5_deliverables/RQ3_INDEPENDENT_REVIEW_REQUEST.md
cat reports/phase5_deliverables/RQ3_PATCH_MANIFEST.json
cat reports/phase5_deliverables/RQ3_HANDOFF_PARTIAL_EXACT_BLOCKERS.md

# Verify G01-G03 bindings in gate code
cat ultimate_pipeline/perception/rq3_evidence_gate.py
cat ultimate_pipeline/perception/rq3_capture_contract.py
```

### Expected Artifacts
- Complete JSON receipts with SHA bindings
- Independent review request document
- Patch manifest with implementation SHAs
- Gate code showing G01-G03 enforcement

---

## 5. ORIGINAL CARLA RUNTIME LOGS

### Command Suite
```bash
# On integration worktree (has runtime logs)
cd C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
ls -la reports/carla_runtime/

# Key runtime evidence
cat reports/carla_runtime/CARLA_BOUNDED_TASK4_20261022.json
cat reports/carla_runtime/CARLA_BOUNDED_TASK4_STAGE_C_RGB.json
cat reports/carla_runtime/GRID0821_BOUNDED_LOAD_EVIDENCE.json
cat reports/carla_runtime/TOWN01_SENSORS_EVIDENCE.json
cat reports/carla_runtime/CARLA_POST_RECOVERY_FINAL_REPORT.md
cat reports/carla_runtime/CARLA_PROBLEM_ROOT_CAUSE_REGISTER.csv
cat reports/carla_runtime/CARLA_FIX_AND_RETEST_MANIFEST.json
cat reports/carla_runtime/post_recovery_server_20261022.log

# Server logs from experimental runs
cat reports/carla_runtime/grid0821_load_20261022T025413Z.log
cat reports/carla_runtime/town01_sensors_20261022T025723Z.log
```

### Expected Artifacts
- All 18 runtime evidence JSON files
- Server stdout/stderr logs
- Problem root cause register
- Fix and retest manifest

---

## 6. GIT LFS POINTER & OBJECT INVENTORY

### Command Suite
```bash
# On repair worktree (has LFS)
cd E:\wt\repair-map-realism-p0-837a8504

# Full LFS inventory
git lfs ls-files | wc -l
git lfs ls-files > lfs_inventory_20261022.txt

# Verify key assets
git lfs ls-files campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr
git lfs ls-files cities/ingolstadt/ingolstadt_osm_auto.xodr

# Check LFS status
git lfs status

# Verify pointer files
git lfs ls-files | head -20
```

### Expected Artifacts
- `lfs_inventory_20261022.txt` — complete list of 62 LFS-tracked files
- Verification of Grid0828 (SHA `5eaece23...`) and auto XODR (SHA `f9744937...`)
- No "missing object" errors

---

## 7. PROTOCOL FREEZE BYTES & SHA-256

### Command Suite
```bash
# On repair worktree
cd E:\wt\repair-map-realism-p0-837a8504
git show HEAD:configs/rq3_protocol_freeze_v1.json | sha256sum
git show 9e777a27:configs/rq3_protocol_freeze_v1.json | sha256sum
git show 67d3b357:configs/rq3_protocol_freeze_v1.json | sha256sum
git show 4ee3327c:configs/rq3_protocol_freeze_v1.json | sha256sum
git show 41526907:configs/rq3_protocol_freeze_v1.json | sha256sum
git show 1e902986:configs/rq3_protocol_freeze_v1.json | sha256sum

# On integration worktree
cd F:\carla-control-suite-worktrees\session-batch1-full-verify-20260913
git show HEAD:configs/rq3_protocol_freeze_v1.json | sha256sum

# On integration main repo
cd C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
git show HEAD:configs/rq3_protocol_freeze_v1.json 2>&1 || echo "MISSING"

# Protocol content
cat E:\wt\repair-map-realism-p0-837a8504\configs\rq3_protocol_freeze_v1.json
```

### Expected Artifacts
- SHA-256 `5aa8ae248b26ed1bcc053ae1b70b5a508e3fd05b5cab4bb68debc495f44b98bd` at all repair commits
- MISSING on integration HEAD `69c818be`
- Present on integration branch `502dda26` at `F:\carla-control-suite-worktrees\session-batch1-full-verify-20260913`
- Full protocol JSON content

---

## 8. WRITER-LOCK & WORKSPACE INVENTORIES

### Command Suite
```bash
# All writer locks
cat C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.agent_locks\writer.lock
cat E:\wt\repair-map-realism-p0-837a8504\.agent_locks\writer.lock
cat C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.agent_locks\*.lock

# Workspace inventories
cd E:\wt\repair-map-realism-p0-837a8504
find . -name "*.lock" -type f
dir .agent_locks /s

cd C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
find . -name "*.lock" -type f
dir .agent_locks /s
```

### Expected Artifacts
- Repair worktree lock: `RQ3_GATE_FIXES_20261022` — status `released`, final SHA `1e902986`
- Integration worktree lock: `TASK01-GUI-INTEGRATION` — status `released`
- No active locks on experimental branch

---

## 9. ALL RELEVANT UNPUBLISHED RECEIPTS

### Required Receipts (Location: `E:\wt\repair-map-realism-p0-837a8504\reports\phase5_deliverables\`)

| Receipt | Purpose |
|---------|---------|
| `RQ3_EVIDENCE_RECEIPT_20261022_9e777a27.json` | Implementation receipt bound to `9e777a27` |
| `RQ3_INDEPENDENT_REVIEW_REQUEST.md` | Review request with SHAs |
| `RQ3_PATCH_MANIFEST.json` | Patch manifest with SHAs |
| `RQ3_HANDOFF_PARTIAL_EXACT_BLOCKERS.md` | Verdict document |
| `RQ3_INDEPENDENT_REVIEW_FINDINGS_20261022.md` | Independent review findings |
| `RQ3_PATCH_MANIFEST.json` | Patch manifest |
| `RQ3_EVIDENCE_RECEIPT_20261022_9e777a27.json` | Evidence receipt |
| `POST_P0_TEST_BASELINE_CLASSIFICATION.json` | Test classification |
| `RQ3_INDEPENDENT_REVIEW_FINDINGS_20261022.md` | Review findings |

### Runtime Receipts (Location: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\carla_runtime\`)

| Receipt | Purpose |
|---------|---------|
| `CARLA_POST_RECOVERY_BASELINE.json` | Baseline |
| `CARLA_BOUNDED_TASK4_20261022.json` | Grid0828 load |
| `CARLA_BOUNDED_TASK4_STAGE_C_RGB.json` | RGB capture |
| `GRID0821_BOUNDED_LOAD_EVIDENCE.json` | Grid0821 load |
| `TOWN01_SENSORS_EVIDENCE.json` | Town01 sensors |
| `CARLA_PROBLEM_ROOT_CAUSE_REGISTER.csv` | Root causes |
| `CARLA_FIX_AND_RETEST_MANIFEST.json` | Fixes |
| `CARLA_POST_RECOVERY_FINAL_REPORT.md` | Final report |

---

## 10. INTEGRATION WORKTREE PRESERVATION

### Files to PRESERVE (DO NOT DELETE)
```bash
# On C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
# Modified tracked files (COMMIT when ready):
- AGENTS.md (modified)
- opencode.json (modified)

# Untracked deliverables (preserve for audit):
- reports/phase5_deliverables/ (entire directory)
- reports/rq1_trial_runs/ (entire directory)
- reports/rq1_trial_runs_x2_verify/ (entire directory)
- reports/rq1b_runs/ (entire directory)
- reports/gap048/ (entire directory)
- reports/gap048/07_lanes_GAP048_AFTER.xodr
- reports/gap048/07_lanes_GAP048_STAGE8_SIM.xodr
- reports/gap048/GAP048_THROUGH_JUNCTION_POPULATION.json
- reports/import_integrity/EXPECTED_VS_ACTUAL_BUILDING_ASSETS_FULL.json
- reports/rq1_trial_runs/... (all subdirectories)
- tools/diagnostics/ (entire directory)
- ultimate_pipeline_out/ (gitignored)
- carla_closure_src/ (if exists)
- All test scripts: grid0821_bounded_load.py, town01_sensors.py, fix_realism_augmentor.py, etc.
```

---

## COMPLETE EXECUTION CHECKLIST

Run each section and save outputs to a timestamped evidence directory:

```bash
# Create evidence directory
mkdir E:\evidence_collection_20261022
cd E:\evidence_collection_20261022

# 1. Worktree states
git -C E:\wt\repair-map-realism-p0-837a8504 status --porcelain=v1 -uall > worktree_repair_status.txt
git -C E:\wt\repair-map-realism-p0-837a8504 log --oneline --graph --all -30 > worktree_repair_graph.txt
git -C C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main status --porcelain=v1 -uall > worktree_integration_status.txt
git -C C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main log --oneline --graph --all -30 > worktree_integration_graph.txt

# 2. Diffs
git -C E:\wt\repair-map-realism-p0-837a8504 diff 9e777a27..HEAD -- ultimate_pipeline/perception/ > diff_rq3_perception.txt
git -C E:\wt\repair-map-realism-p0-837a8504 diff 9e777a27..HEAD -- ultimate_pipeline/augmentation/ > diff_rq3_augmentation.txt
git -C E:\wt\repair-map-realism-p0-837a8504 diff 9e777a27..HEAD -- ultimate_pipeline/tests/unit/test_rq3_*.py > diff_rq3_tests.txt

# 3. Test logs
cd E:\wt\repair-map-realism-p0-837a8504
git checkout experimental/verified-fixes-20261022
C:\temp\py312_venv\Scripts\python.exe -m pytest ... -v --tb=long > test_full_log.txt 2>&1

# 4. Receipts
cp -r E:\wt\repair-map-realism-p0-837a8504\reports\phase5_deliverables\* receipts_phase5\
cp C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\carla_runtime\* receipts_runtime\

# 5. Runtime logs
cp C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\carla_runtime\* receipts_runtime\

# 5. LFS inventory
cd E:\wt\repair-map-realism-p0-837a8504
git lfs ls-files > lfs_inventory.txt

# 6. Protocol freeze
git -C E:\wt\repair-map-realism-p0-837a8504 show HEAD:configs/rq3_protocol_freeze_v1.json | sha256sum > protocol_sha.txt
git -C F:\carla-control-suite-worktrees\session-batch1-full-verify-20260913 show HEAD:configs/rq3_protocol_freeze_v1.json | sha256sum >> protocol_sha.txt

# 6. Writer locks
cat C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.agent_locks\writer.lock > lock_integration.json
cat E:\wt\repair-map-realism-p0-837a8504\.agent_locks\writer.lock > lock_repair.json

# 7. Writer lock on integration worktree
cat F:\carla-control-suite-worktrees\session-batch1-full-verify-20260913\.agent_locks\writer.lock 2>&1 > lock_integration_wt.json

# 8. Receipts
cp -r E:\wt\repair-map-realism-p0-837a8504\reports\phase5_deliverables\ receipts_all\

# 9. Untracked files inventory
cd C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
git status --porcelain=v1 -uall > untracked_inventory.txt
```

---

## DELIVERABLE: EVIDENCE PACKAGE

Create `E:\evidence_collection_20261022.zip` containing:
```
evidence_collection_20261022/
├── worktree_states/
│   ├── worktree_repair_status.txt
│   ├── worktree_repair_graph.txt
│   ├── worktree_integration_status.txt
│   ├── worktree_integration_graph.txt
├── diffs/
│   ├── diff_rq3_perception.txt
│   ├── diff_rq3_augmentation.txt
│   ├── diff_rq3_tests.txt
├── test_logs/
│   ├── test_full_log.txt
│   ├── test_failing_detail.txt
│   ├── env_fingerprint.json
├── receipts/
│   ├── phase5/ (all 40+ files)
│   ├── runtime/ (all 18 files)
├── lfs/
│   └── lfs_inventory.txt
├── protocol/
│   └── protocol_sha.txt
├── locks/
│   ├── lock_repair.json
│   ├── lock_integration.json
│   └── lock_integration_wt.json
├── untracked/
│   └── untracked_inventory.txt
└── metadata/
    └── collection_manifest.json
```

---

## VERIFICATION COMMANDS FOR CHATGPT

```bash
# Verify experimental branch
git clone https://github.com/lemoniadowyjohn/carla-control-suite.git
cd carla-control-suite
git checkout experimental/verified-fixes-20261022

# 1. Tests
python -m pytest ultimate_pipeline/tests/unit/test_rq3_builder_false_pass_regression.py \
  ultimate_pipeline/tests/unit/test_rq3_paired_capture_contract.py \
  ultimate_pipeline/tests/unit/test_rq3_frame_set.py -q
# → 70 passed, 1 failed

# 2. Protocol freeze
git show HEAD:configs/rq3_protocol_freeze_v1.json | sha256sum
# → 5aa8ae248b26ed1bcc053ae1b70b5a508e3fd05b5cab4bb68debc495f44b98bd

# 3. Augmentor
python -c "from ultimate_pipeline.augmentation.realism_augmentor import RealismAugmentor, AugmentationConfig; print('OK')"

# 6. Gate fixes
grep -n "terminal_status == \"COMPLETED\"" ultimate_pipeline/perception/rq3_evidence_gate.py
grep -n "review_receipt_sha256" ultimate_pipeline/perception/rq3_evidence_gate.py
grep -n "expected_counts" ultimate_pipeline/perception/rq3_capture_contract.py
grep -n "RQ3_APPROVED_ROOT_ENV" ultimate_pipeline/perception/rq3_evidence_gate.py
```

---

**This prompt captures all evidence required for complete independent verification. Execute each section, save outputs, and package into `E:\evidence_collection_20261022.zip` for transfer.**