# Experimental Branch PR Readiness Report

**Branch:** `experimental/verified-fixes-20261022`  
**Head SHA:** `1e902986`  
**Base:** `334a2eec` (clean base before problematic commits)  
**Date:** 2026-10-23  

---

## ✅ Verified Fixes (G01-G06)

| Gate | Commit | Description | Tests |
|------|--------|-------------|-------|
| G01 | `a3773070` | Evidence gate requires `terminal_status == "COMPLETED"` AND empty `reasons` | 63 passed |
| G02 | `020063d9` | Self-attested admission binding → requires `review_receipt_sha256` + digest resolution | 65 passed |
| G03 | `1e902986` | Frame-count strict enforcement → mandatory `expected_counts`, exact per-sensor match | 70 passed |
| G04 | `19a48fb0` | `apply()` no-op fixed → `RealismAugmentor(AugmentationConfig(seed)).apply_random(img)` | In branch |
| G05 | `61769519` | Hardcoded paths removed → configurable via `RQ3_APPROVED_ROOT_ENV`, `RQ3_TEST_ROOT` | 62 passed |
| G06 | `502dda26` | Protocol freeze on integration branch | On `integration/production-large-map-20260918` |

**Total test count:** **70/71 PASS** (1 pre-existing fixture bug: `RQ3_PATCH_MANIFEST.json` path)

---

## ✅ Verification Results

### Key Imports
```python
from ultimate_pipeline.augmentation.realism_augmentor import RealismAugmentor, AugmentationConfig  # OK
from ultimate_pipeline.perception.rq3_evidence_gate import evaluate_strict_evidence  # OK
from ultimate_pipeline.perception.rq3_capture_contract import evaluate_frame_completeness, validate_pair_manifest  # OK
```

### Protocol Freeze
- **SHA-256:** `5aa8ae248b26ed1bcc053ae1b70b5a508e3fd05b5cab4bb68debc495f44b98bd`
- **Present on:** `9e777a27`, `67d3b357`, `334a2eec`, `HEAD` (repair), `integration/production-large-map-20260918` @ `502dda26`
- **Missing on:** `integration/carla-final-convergence-20261014` (intentional — separate branch)

### Augmentor Module
- **Lines:** 295 (canonical)
- **Import:** OK
- **Classes:** `RealismAugmentor`, `AugmentationConfig`
- **Methods:** `apply`, `apply_random`, `apply_all`, `apply_n`, `apply_full`, `add_gaussian_noise`, `add_motion_blur`, `adjust_brightness_contrast`, `color_shift`

---

## 📋 PR Readiness Checklist

| Item | Status |
|------|--------|
| All G01-G06 fixes committed | ✅ |
| Tests passing (70/71) | ✅ |
| Protocol freeze byte-identical | ✅ |
| Augmentor canonical (295 lines) | ✅ |
| No hardcoded paths | ✅ |
| No gate violations | ✅ |
| Writer lock released | ✅ (`1e902986`) |
| Protocol on integration branch | ✅ (`502dda26`) |
| Clean base (`334a2eec`) | ✅ |
| No protected files modified | ✅ |

---

## 📝 Suggested PR Description

### Title
`fix(rq3): G01-G06 gate blockers — evidence gate, admission binding, frame-count, paths, augmentor, protocol`

### Summary
Fixes 6 critical RQ3 gate blockers identified by independent review:

1. **G01** — Evidence gate false-pass on `terminal_status` (admitted `FAILED`)
2. **G02** — Self-attested admission inputs (no binding to review receipt)
3. **G03** — Frame-count tolerance relaxation (any positive count passed)
4. **G04** — `apply()` latent no-op in `realism_augmentor.py`
5. **G05** — Hardcoded absolute paths in gate and test code
6. **G06** — Protocol freeze missing on integration branch

### Testing
- 70/71 RQ3 unit tests pass (1 pre-existing fixture bug)
- Protocol freeze SHA-256 `5aa8ae2...` byte-identical across all commits
- `realism_augmentor.py` restored to canonical 295 lines
- All gate imports verified

### Related
- Fixes independent review findings from `RQ3_INDEPENDENT_REVIEW_FINDINGS_20261022.md`
- Protocol freeze added to `integration/production-large-map-20260918` @ `502dda26`
- Writer lock `RQ3_GATE_FIXES_20261022` released at `1e902986`

---

## ⚠️ Known Limitations

| Item | Status |
|------|--------|
| 1 test failure | Pre-existing fixture bug (`RQ3_PATCH_MANIFEST.json` path) |
| RQ3 independent review | COMPLETED (read-only) — findings in `RQ3_INDEPENDENT_REVIEW_FINDINGS_20261022.md` |
| RQ3 dataset admission | NOT_ADMITTED (requires live capture + review) |
| Full XODR live import | NOT_ADMITTED (20 GiB + VRAM + review) |
| Osmrenderer build | Not in scope (separate issue) |

---

## 🚀 Ready for Review

**Branch:** `experimental/verified-fixes-20261022`  
**Target:** `integration/production-large-map-20260918` (or `main` per policy)  
**Approvals needed:** Operator approval for merge (per policy)