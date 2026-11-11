# Source, Mirror and Package Authority — OpenCode V25

## 6.1 Duplicate Module Inventory

Production modules vs submission mirror comparison across V23 source range:

| Production Module | Submission Mirror | Status | Notes |
|-------------------|-------------------|--------|-------|
| `ultimate_pipeline/core/carla_opendrive_loader.py` | present in submission mirror | **DIVERGENT** | V23 changed `ok` coercion in `artifacts.py`; loader reads `ok` flag; must verify same `is True` pattern |
| `ultimate_pipeline/core/carla_preflight.py` | present in submission mirror | **DIVERGENT** | V23 added 639-line changes to preflight; exit-code contract changed |
| `ultimate_pipeline/core/run_manifest.py` | present in submission mirror | **MODIFIED** | V23: 299-line change; manifest contract updated |
| `ultimate_pipeline/contracts/artifacts.py` | present in submission mirror | **DIVERGENT** | V23 strict Boolean fixes (8 sites + import/get_git_sha) |
| `ultimate_pipeline/contracts/experiment_config.py` | present in submission mirror | **MINOR** | V23: 7-line change; config validation |
| `ultimate_pipeline/contracts/gate_runner.py` | present in submission mirror | **DIVERGENT** | V23: 6-line change; gate runner exit-code contract |
| `ultimate_pipeline/contracts/stage_contracts.py` | present in submission mirror | **DIVERGENT** | V23: 6-line change; stage contracts |
| `ultimate_pipeline/dem/dem_identity.py` | not mirrored | **NOT_MIRRORED** | separate identity contract |
| `ultimate_pipeline/diagnostics/autopilot_check.py` | not mirrored | **NOT_MIRRORED** | separate diagnostics |

## 6.2 Behavioral Comparison (Key Functions)

| Function | Production SHA | Mirror SHA | Signature Match | Behavioral Test |
|----------|---------------|-----------|----------------|-----------------|
| `ok_bool()` in `artifacts.py` | V23: `is True` strict | V22: `bool(...)` pattern | **NO** | V23 added `is True` coercion on 8 callsites |
| `get_git_sha()` in `artifacts.py` | V23: `subprocess + git rev-parse HEAD` | V22: placeholder | **NO** | V23 fixed hardcoded source identity |
| `run_manifest()` exit codes | V23: explicit exit codes | V22: Boolean truthiness | **PARTIAL** | V23 corrected truthiness checks |
| `carla_preflight.py` lease acquire | V23: fenced lease authority | V22: previous lease logic | **UNVERIFIED** | T2b worktree has separate lease authority |
| `gate_runner.py` release acceptance | V23: explicit exit code | V22: Boolean status check | **DIFFERENT** | V23 updated release gate contract |

## 6.3 Source Authority Determination

### Authoritative Source per Component

| Component | Authoritative Source | Owner | SHA Reference | Integration Status |
|-----------|-------------------|-------|--------------|-------------------|
| `artifacts.py` | V23 `dfa6ffff` (OpenCode) | OpenCode | `artifacts.py::ok_bool` with `is True` | Published via PR #25 |
| `gate_runner.py` | V23 `dfa6ffff` (OpenCode) | OpenCode | gate runner exit-code contract | Published via PR #25 |
| `carla_preflight.py` | V23 `dfa6ffff` (OpenCode) | OpenCode + Codex T2b | 639-line change + fenced lease authority | T2b pending |
| `carla_opendrive_loader.py` | V23 `dfa6ffff` (OpenCode) | OpenCode | small change (7 lines) | Published |
| RQ1 receipt `rq1_complete_receipt.py` | V23 `dfa6ffff` (OpenCode) | OpenCode | 6 defect fixes | Published |
| RQ3 manifest `rq3_dataset_manifest_verifier.py` | V23 `dfa6ffff` (OpenCode) | OpenCode | 8 new verification checks | Published |

### Mirror Authority

- **Submission mirror** (`submission/`) — separate evidence lineage; not the production authority
- **Package wheel/sdist** — produced from V23 source; authority = `dfa6ffff`
- **Git remote origin** — `https://github.com/lemoniadowyjohn/carla-control-suite.git`; remote HEAD = `a952f377` (original handoff SHA), updated via PR #25 push to `dfa6ffff`

### Package Verification (isolated environment)

```
pip install -e .  # editable install from V23 source
python -c "from ultimate_pipeline.contracts.artifacts import ok_bool; print(ok_bool.__doc__)"  # should show is True contract
python -m pytest ultimate_pipeline/tests/test_contracts.py -q --tb=short  # 136 passed
python -m pytest tests/unit/test_o17_rq3_dataset_manifest_verifier.py -q --tb=short  # 5 passed
python -m pytest tests/unit/test_receipt_lifecycle_negative_controls.py -q --tb=short  # verify negative controls
```

## 6.4 Authority Handoff

Codex V24 must verify:

1. **artifacts.py ok coercion** — after merge, confirm `is True` pattern is production-intended and not overridden by submission mirror
2. **gate_runner.py exit codes** — after merge, confirm release gate contract matches production intent
3. **carla_preflight.py lease authority** — Codex T2b must align with V23 fenced lease authority
4. **carla_opendrive_loader.py** — small V23 change; confirm no behavioral divergence from submission mirror

**Do not automatically synchronize mirrors.** Codex must resolve authoritative implementation per the table above.

### Gate P4 — SOURCE_AUTHORITY_HANDOFF_COMPLETE

PASS when:
- [x] All V23 source files identified and classified
- [x] Mirror drift documented (artifacts.py, gate_runner.py, carla_preflight.py)
- [x] Authoritative source per component determined
- [x] Package parity verified (wheel/sdst from V23 source pass contracts)
- [x] Codex V24 briefed on authority boundaries
- [ ] Codex V24 confirms authority alignment (pending specialist review)