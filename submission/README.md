# Thesis Submission Package

**Author:** Michał Dembski
**Title:** Structural Domain-Gap Analysis of OSM-Generated vs. Manually Authored CARLA Maps
**Institution:** Technische Hochschule Ingolstadt (THI)
**Degree:** Bachelor of Engineering
**Date:** April 2026

---

## Contents

```
submission/
├── thesis_final_submission.pdf       ← Final thesis PDF (81 pages)
│
├── thesis_source/                    ← LaTeX source
│   ├── Chapter1/ … Chapter9/        ← Chapter .tex files
│   ├── Appendix/
│   ├── thesis.tex                   ← Root document
│   ├── literature.bib               ← Bibliography
│   └── glossary.tex, metadata.tex, …
│
├── infrastructure/
│   └── ultimate_pipeline/           ← OSM→OpenDRIVE→CARLA pipeline code
│
└── results/
    ├── structural_gap_run11/        ← RQ2: Authoritative structural gap (run_11)
    │                                   RMSE=54.84m, matched=24.47m, Hausdorff=1663m
    ├── rq1_determinism/             ← RQ1: 5-run determinism audit (CV=0.0 topo)
    ├── gnn_v1/                      ← RQ4: GNN contrastive training results
    │                                   NT-Xent, cross-cosine=−0.160, NOT_COLLAPSED
    ├── rq4_variability/             ← RQ4: Structural variability across runs
    └── perception_rq3_bounded/      ← RQ3: Bounded Town10HD sensor-rig evidence
                                        20 frames, 14 sensor callbacks confirmed OK
```

---

## Key Authoritative Metrics (run_11)

| Metric | Value |
|--------|-------|
| Whole-network RMSE | 54.84 m |
| Matched-subset RMSE (73% match) | 24.47 m |
| Hausdorff distance | 1,663 m |
| Road coverage ratio (auto/manual) | 4.88× |
| Junction ratio (auto/manual) | 6.55× |
| Curvature std (auto vs manual) | 0.865 vs 0.055 m⁻¹ |

## RQ Status Summary

| RQ | Status | Evidence |
|----|--------|----------|
| RQ1 Determinism | BOUNDED | Structural CV=0.0; byte-level NONDETERMINISTIC |
| RQ2 Structural gap | RESOLVED | run_11 metrics above |
| RQ3 Perceptual gap | DEFERRED | Town10HD rig confirmed; generated map fails visual QA |
| RQ4 GNN latent space | OBSERVATIONAL | N=6 pilot, non-collapsed only |
| RQ5 Generalization | DEFERRED | Conditional on RQ3 paired capture |

---

## Pipeline Quick Reference

```bash
# Install
pip install -e ultimate_pipeline/

# Run structural gap analysis
python -m ultimate_pipeline.tools.run_thesis_final_experiments

# See ULTIMATE_PIPELINE_RUNBOOK.md for full usage
```

## Build Thesis PDF

```bash
cd thesis_source/
pdflatex thesis.tex
bibtex thesis
pdflatex thesis.tex
pdflatex thesis.tex
```
