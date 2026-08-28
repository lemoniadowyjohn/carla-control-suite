# C15 (HIGH) — RQ4: does domain randomization occur naturally? + wire explicit DR

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803` · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1
Rules: TDD; **EXPLICIT-PATHSPEC commit**; conservative claim boundaries. Model: high. Plan: Phase R3. Offline.

## RQ4
*When generating many maps with the OSM→CARLA pipeline, does domain randomization occur naturally?* And if not,
what explicit randomization does the thesis apply?

## Machinery (reuse)
- Determinism arm: `experiments/thesis/exp_osm_to_xodr_determinism.py`, `tools/check_osm_to_carla_determinism.py`,
  `tools/compare_runs_determinism.py`, `domain_gap/deterministic_alignment.py`.
- Multi-map arm: `tools/generate_n_runs.py`, `experiments/thesis/exp_natural_domain_randomization.py`.
- Classifier: `config/thesis_contract.py::classify_variability_experiment` (same_input_repeat vs multi_map).
- Explicit DR: `ultimate_pipeline/augmentation/realism_augmentor.py`.
- Protocol requires `maps.generated.n_variants >= 5` (`experiments/thesis/protocol.py::MIN_GENERATED_VARIANTS`).

## Steps
1. **Determinism arm (same-input repeat).** Convert the SAME pinned OSM → XODR N times
   (`exp_osm_to_xodr_determinism.py`); measure byte/geometry variance. Expected result (from C0 evidence):
   ≈ deterministic → **natural DR ≈ absent**. Classify via `classify_variability_experiment(same_input_repeat=True)`
   → `same_input_repeat_determinism`.
2. **Multi-map arm (n ≥ 5 variants).** `generate_n_runs.py` → ≥5 generated map variants (vary only what the
   pipeline legitimately varies: seed/config knobs that are part of the method, NOT hand edits). Compute the
   **structural spread** across variants using the C14/RQ1 machinery (per-aspect gap variance across the 5) →
   `multi_map_variability_natural_randomization`. Report how much variability the pipeline produces on its own.
3. **Answer RQ4 honestly.** If same-input is deterministic and multi-map spread is small, the answer is
   **"natural DR is ≈ absent / insufficient"** — state it plainly; do NOT dress deterministic conversion up as DR.
4. **Wire + document explicit DR.** Since natural DR is insufficient, the thesis’s randomization must be
   **explicit**: TDD-verify `augmentation/realism_augmentor.py` (weather/lighting/texture/asset randomization at
   capture time) and document it as THE DR mechanism the perception experiments use. Characterize it (deterministic
   given a seed; produces a controlled distribution of appearances) — do not claim it emerges from map generation.
5. Emit a machine-readable variability report so the contract auditor records both experiment classes with the
   correct labels + reasons.

## Boundaries
- Deterministic/offline. The n≥5 variants must come from the *pipeline’s own* parameters, not manual edits (else
  it is not a "natural" variability measurement). Explicit DR is clearly separated from natural DR in every claim.

## Deliverables / verdict
- `experiments/thesis/` variability report (determinism variance + n≥5 structural spread) + explicit-DR
  characterization tests; `reports/post_audit_hardening/C15_RQ4_DOMAIN_RANDOMIZATION.md`.
- Push (explicit pathspec); suite green.
- **Verdict:** `RQ4 natural_DR=absent|weak(spread=<x>) determinism=<var> explicit_DR=wired` | PARTIAL | BLOCKED.
