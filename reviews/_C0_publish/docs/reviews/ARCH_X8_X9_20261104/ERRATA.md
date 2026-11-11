# Errata to ARCH-X8-X9 (found by ARCH-002; the original text is left unchanged)

| # | ARCH-X8-X9 said | Corrected | Source |
|---|---|---|---|
| E1 | "2,734 have a zero-speed cusp" | Correct for the `|r′| < 1e-6·L` cut-off, but that count depends on the cut-off. **3,367 of 3,375** U-turn refits reverse direction (kernel sampling, N=2000). | `evidence/x7_crosscheck_kernel.json` |
| E2 | "423 self-intersect" | Depends on sampling: 423 at N=800 (analytic), 426 at N=2000 (kernel). Report it as ≥ 423. | same |
| E3 | "worst: road 68739 … 3.7×" | 68739 is the worst by **curvature**. The overall maximum arc/length is **4.02**. | `x7_geom_audit.json` `arc_ratio.max`; crosscheck `other_arc_ratio_max` |
| E4 | "Its start moved roughly 8 m" (68739) | **10.5 m** measured (`entry_error_before_m`). The maximum over all refits is 14.0 m, and 26 refits move more than their own length. | `evidence/x7_displacement.py` |
| E5 | C1 scope: harden the Hermite refit (U-turn exclusion, arc-length, guard, gates) | **Redirected.** The snap's premise is false. Its moves equal lane-border offsets (4,024 / 4,025), and 85% of all connectors start on their from-lane inner border. The minimal fix is to disable the snap or gate it on lane borders. The hardening gates apply only if any snapping is kept. | `docs/reviews/ARCH002_20261104/ARCH002_INDEPENDENT_REVIEW.md` §A+ |
| E6 | "Entry reference-line mismatches: report only" (X8 plan) | Stronger: this metric scores correct lane-border placement as a defect. It is largely a false-positive metric and must not drive decisions. | ARCH-002 §A+ |
| E7 | "hashes in `evidence/SHA256SUMS.txt`" | In this published package the hash list is `SHA256SUMS` at the package root. It covers every file, including `evidence/`. | this package |
| E8 | Summary item 3: "The U-turns come from CARLA Osm2Odr, not netconvert" | **Invalid inference.** The 2026-10-07 run's input was the map-of-record XODR (`370abbbb…`), not OSM, so the U-turns are present in the map-of-record and their origin is unknown. | `docs/reviews/ARCH003_20261104/ERRATA_TO_PRIOR_REVIEWS.md` (X1) |
