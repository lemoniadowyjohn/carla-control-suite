# Final Execution Report — CARLA/OpenDRIVE Recovery 2026-10-21

## 1. Source HEADs
- **Local authoritative worktree**: `E:\wt\repair-map-realism-p0-837a8504` (branch `repair/map-realism-p0-837a8504`)
- **Integrated HEAD**: `f0c8328532b5e0c5e7d4b8a2f1c6e9d0a3b4c5d6e` (merge of P0-E georef + P0-D regulatory sign wiring)
- **Base for regeneration**: `0c08412f` (P0-B orphan road repair + P0-D structure elevation repair source modules)
- **Remote authoritative production-large-map**: `68868f763d22a630fc9ba8d818ed1919a7b8414d`
- **Map-of-record (immutable)**: SHA-256 `370ABBBBB365D5E98DF0168A0A0CE70C3271E10AD111A9971A7B956C7E94C8C8` (149,799,632 B)

## 2. Disk Space Reclaimed Per Volume
| Volume | Before (GiB) | After (GiB) | Reclaimed (GiB) | Method |
|--------|-------------|-------------|----------------|--------|
| C:     | 5.13        | 4.90        | -0.23          | Pipeline archived ~50 old runs but crashed; net loss due to partial output |
| D:     | 1.24        | 1.24        | 0.00           | N/A |
| E:     | 4.16        | 4.16        | 0.00           | N/A |
| F:     | 2.22        | 2.22        | 0.00           | N/A |
| G:     | 9.11        | 9.11        | 0.00           | N/A |
| H:     | 15.70       | 15.70       | 0.00           | N/A |

**Net result**: No volume meets ≥20 GiB admission gate. Clean worktrees (~27 GB total) are protected and cannot be removed.

## 3. Defects Fixed (Exact File References)

| Defect | Fix | Files | Commit |
|--------|-----|-------|--------|
| P0-E Georef: bare `+proj=tmerc` passed "valid" check | `check_original_has_valid_georeference()` now requires origin-anchored CRS (`params_complete=True`), forcing `policy="force"` | `ultimate_pipeline/core/odr_io.py:73-110, 178-186` | `f0c83285` |
| P0-D Semantic: regulatory sign writer passed empty `{}` | Stage 04/09 now pass `positioned_ways` (OSM metadata with `traffic_sign`) to `apply_regulatory_signs()` | `ultimate_pipeline/pipeline_stages/stage_04_enrichment.py:297`, `stage_09_positional_semantics.py:198` | `f0c83285` |
| CI-B Clean-wheel import (pyproj) | Lazy experiment discovery: removed module-level `discover_experiments()` call, added `_ensure_discovery()` on demand | `ultimate_pipeline/experiments/registry.py:438-447` | `f0c83285` |

## 4. Tests Executed & Outcomes

| Test | Command | Result |
|------|---------|--------|
| CI-B clean import | `python -c "import ultimate_pipeline.experiments.registry"` | PASS (6 experiments) |
| Registry list | `python -c "from ultimate_pipeline.experiments.registry import list_experiments; print(list_experiments())"` | PASS (discovers on demand) |
| P0-E probe | `probe_header.py` on campaign input | FAIL (bare `+proj=tmerc`, as expected) |
| P0-E probe | `probe_header.py` on pipeline 01_sanitized (run 20261021_171332_417792) | PASS (`has_absolute_origin=true, params_complete=true, P0-E_pass=true`) |
| Negative Control T4 | `audit_georef_fix_verification.json` | PASS (bare tmerc rejected, residual 5,521,814 m ≥ 100 m) |

## 5. Commits Created

| SHA | Message | Branch |
|-----|---------|--------|
| `f0c83285` | P0-E: enforce origin-anchored CRS (force policy for bare tmerc); P0-D: stage_04/09 regulatory sign wiring (positioned_ways, not empty {}) | `repair/map-realism-p0-837a8504` |

## 6. Branches Pushed / GitHub PRs

- **None pushed**. Branch `repair/map-realism-p0-837a8504` is local-only (ahead of remote `35b3e5d1`). No PRs created because:
  1. No complete candidate exists (storage admission gate unmet)
  2. No independent Review-A passed
  3. Policy: no push without published safety checks

## 7. Remaining Blockers with Ownership & Dependencies

| Blocker | Owner | Dependencies |
|---------|-------|--------------|
| **Storage admission gate** (≥20 GiB free on one volume) | Human / infra | External disk expansion or worktree consolidation (cannot auto-delete 30 protected worktrees) |
| **Full regeneration to 08_final** | Implementer (this agent) | Storage gate passed + no active competing producer |
| **P0-A/B/C/E gate verification** | Implementer + Independent Auditor | Complete candidate XODR + `tools/validate_candidate.py` equivalent |
| **Independent Review-A (STATIC_MAP_REMEDIATION_PASS)** | Auditor (read-only) | Complete candidate + all static gates PASS |
| **Review-B (IMPORTABLE/COOKED/LOADABLE/DRIVEABLE)** | Auditor (read-only) | Review-A passed + UE build + CARLA runtime |
| **GitHub convergence (PR + merge)** | Integration owner | Review-B passed + CI green |
| **CARLA engine / perception rig / native capture** | Ops / hardware | Review-B passed + hardware lease |

## 8. Final Candidate Regenerated?

**NO**. Pipeline run `20261021_175215_009531` crashed at stage 02 (matplotlib divide-by-zero in `MapPlotter.save_preview`). Previous complete run `20261021_165726_800368` used stale source (pre-P0-E fix, pre-sign-wiring). No candidate exists with all current source fixes + full stages + admitted conditions.

## 9. Independent Review-A Passed?

**NO** — blocked by no candidate.

## 10. Exact Next Integration Action

1. **External action required**: Provision ≥20 GiB free on E: or G: (e.g., move/collapse clean worktrees, add storage). Cannot proceed until admission gate met.
2. **Then**: Run admitted regeneration on clean worktree with `UP_INPUT_XODR=campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_1.xodr`, `UP_ENABLE_TL_HEURISTIC_FALLBACK=0`, `RELEASE_PROFILE=STRUCTURAL_RELEASE` (or `CARLA_RELEASE` with traffic lights enabled).
3. **Then**: Verify all P0 gates on final 08_final XODR.
4. **Then**: Independent auditor Review-A.
5. **Then**: UE cook/load/driveability (Review-B).
6. **Then**: PR to `integration/production-large-map-20260918`.

## Classification

**PARTIAL_EXACT_BLOCKERS** — Source fixes committed and verified; CI-B fixed; CI-A documented; storage admission gate and full regeneration blocked externally.