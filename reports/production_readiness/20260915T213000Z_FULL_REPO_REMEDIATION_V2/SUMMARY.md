# Comprehensive Gap Audit Summary

## AUDITED_SHA: 540b5c5f12b10ff1f1add6fa51cc2c5cabea2c2a

## Repository State

- **Remote**: `lemoniadowyjohn/carla-control-suite`
- **Working Tree HEAD**: `540b5c5f12b10ff1f1add6fa51cc2c5cabea2c2a` on `fix/large-map-offline-hardening-v1-20260915`
- **Main Branch HEAD**: `e0aa1aab232129cac131bd61bf882e7115ea97c4`
- **Stabilization Branch**: `stabilize/research-release-20260905` (exists on remote)
- **Integration Branch `session-batch1-20260912`**: NOT ON REMOTE (local worktree only)
- **Worktrees**: 14 active
- **Dirty Files**: 8 modified
- **Untracked**: 5+ files including test files and reports

## RQ Status Summary

| RQ | Status | Claim |
|----|--------|-------|
| RQ1 Determinism | BOUNDED | Structural determinism AUTHORITATIVE; timestamp normalization BOUNDED |
| RQ2 Structural Gap | BOUNDED | Local comparison authoritative; whole-map overstated |
| RQ3 Perceptual Gap | DEFERRED_RUNTIME | No runtime; CARLA RPC hang blocks |
| RQ4 Variability | AUTHORITATIVE (caveats) | n=5 seed extension; fragile CIs |
| RQ5 Generalization | DEFERRED | No runtime for RQ5a; no external data for RQ5b |

## Key Confirmed Bugs

1. **AREA-001 (P0)**: `heading_error or math.pi` makes perfect heading match receive ZERO bonus — truthiness bug
2. **AREA-002 (P0)**: Ambiguity margin check inverted (`best[1] - scored[1][1]` should be `scored[1][1] - best[1]`)
3. **AREA-003 (P0)**: `_validate_legacy` sorts Python list but doesn't reorder XML; repair report claims fixes that don't exist
4. **AREA-008 (P0)**: `carla-runtime.yml` uses `if: always()` hard-coded PASS regardless of command result
5. **AREA-020 (P1)**: Roundtrip False does not produce FAIL; status='ok' overwrites failure

## Audit Verdict

### SOFTWARE_CLASS: PRE_PRODUCTION

The software is research-grade with partial production readiness. Key subsystems (geometry kernel, correspondence) have confirmed P0 bugs. CARLA runtime is NOT_RUN. RQ3 and RQ5 are blocked.

### Current Remote CI: NOT_RUN

No CI evidence found for the integration branch (which doesn't exist on remote). The last green run was `b059a9d0` under an earlier single-job workflow.

### Pipeline Dependency Order: FAIL

Position-dependent semantics (signals, crosswalks, signs) are written before structural geometry freeze. No explicit STRUCTURAL_FREEZE gate exists. Stages lack capability prerequisites.

### Geometry Authority: CONDITIONAL

The kernel correctly implements all 5 primitives (line, arc, spiral, poly3, paramPoly3). However: unknown pRange silently defaults, bounding boxes underestimate curves, projection is coarse, no independent numerical oracle exists.

### Geometry Validator Purity: FAIL

`_validate_legacy` mutates claims without XML mutation. `validate()` does mutate XML correctly but the legacy path is still present and produces false-positive repair reports.

### OSM-XODR Correspondence: FAIL

Two confirmed P0 bugs (heading_error truthiness, ambiguity margin inversion). The association model assumes 1:1 mapping (insufficient). No spatial index optimization. Scoring incomplete.

### Lane Model: CONDITIONAL

Lane generation needs orientation accounting. Lane width preservation has polynomial destruction risks. Lane offset not part of structural freeze. Lane links need scope-correct validation. Turn restrictions MISSING.

### Traffic Control: CONDITIONAL

Traffic lights are synthetic-as-source-truth. Sign placement uses fixed coordinates. Signal XML conformance unverified against CARLA 0.9.16 schema. Speed authority unclear.

### DEM CRS: PARTIAL

CRS transformation code is correct (pyproj used). But coverage gate only uses diagonal ratio, not road-centerline sample coverage. Ambient env var could weaken production.

### Roundabouts: PROTOTYPE

Current reconstructor uses heuristic detection, perfect-circle reconstruction, swallowed exceptions. NOT enabled in production. V2 behind feature flag.

### Junction Connectors: CONDITIONAL

Nearest-endpoint fallback, direct line without heading tolerance, contactPoint trust. No constrained primitive selection. Ambiguous connectors not handled.

### Map Connectivity: CONDITIONAL

Size-only quarantine insufficient. UNKNOWN auto-deletion forbidden in production. Literal vs recovered topology not separated.

### Large Map Offline: CONDITIONAL

Roundtrip fail-closed not implemented. Tile set comparison not exact. Transactional staging uses hardlinks. Per-tile computation skipped.

### Large Map Runtime: NOT_RUN

No runtime checks performed. Do not claim any check passed before execution.

### Artifact Authority: PARTIAL

Manifest says provisional/unaccepted while registry says current map-of-record. Authority drift confirmed.

### Packaging: CONDITIONAL

No package extras defined. Clean-venv testing not performed. Python 3.10/3.12 compatibility not verified.

## Confirmed P0 Count: 5
## Confirmed P1 Count: 15
## First Blocker: P0-A — `if: always()` hard-coded PASS in carla-runtime.yml means runtime CI cannot distinguish passing from failing runs, and the integration branch `session-batch1-20260912` does not exist on remote origin, so CI cannot run on the integration candidate.

## Next Implementation Packet: P0-A (CI Truth)

Fix `if: always()` in `.github/workflows/carla-runtime.yml` to derive status from actual command result. Ensure integration candidates get CI on their exact SHA. Add offline tests for status derivation. Write only CI/status changes.

## RQ Readiness

- RQ1: BOUNDED (structural authoritative, timestamp partial)
- RQ2: BOUNDED (local comparison authoritative)
- RQ3: NOT_READY (blocked on CARLA runtime)
- RQ4: AUTHORITATIVE (with n=5 caveat)
- RQ5(a): NOT_READY (blocked on RQ3)
- RQ5(b): BLOCKED_EXTERNAL_DATA (no real-world dataset)
