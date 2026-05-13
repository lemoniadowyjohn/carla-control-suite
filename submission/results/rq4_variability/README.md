# RQ4 N-run Diversity Report (Observed Conversion Variability)

This folder contains evidence of conversion variability for the OSM to CARLA pipeline, as measured by an N=5 determinism batch.

## Allowed Thesis Wording
"The OSM-to-XODR conversion pipeline exhibits bitwise non-determinism; multiple runs from the same OSM input yield unique file hashes. However, structural features (road count, junction count, and tile count) remained identical across all observed runs (CV=0.0), indicating that conversion noise is localized to bit-level representation (e.g., XML ordering or metadata) rather than topological structure."

## Prohibited Wording
- DO NOT claim this represents "domain randomization" or "robustness."
- DO NOT claim the variability is "caused" by any specific subsystem without further ablation.
- DO NOT claim the pipeline is "deterministic" (it is NOT bit-identical).

## Artifacts
- `index.csv`: Detailed run metadata.
- `diversity_summary.csv`: Summary metrics including Coefficient of Variation.
- `diversity_report.json`: Interpretation and source paths.
