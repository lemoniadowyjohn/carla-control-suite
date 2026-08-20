# C15 — RQ4: does domain randomization occur naturally? + explicit DR

**RQ4:** When generating many maps with the OSM→CARLA pipeline, does domain randomization occur naturally?

## Determinism arm (Osm2Odr on the pinned OSM `b9e07465`, 3 runs)
| run | sha256 (byte) | num_roads | num_junctions | total_road_length |
|---|---|---|---|---|
| 0 | `7d64a2c0…` | 32920 | 3717 | 1498527.5916156755 |
| 1 | `d814f0ca…` | 32920 | 3717 | 1498527.5916156755 |
| 2 | `3775b65f…` | 32920 | 3717 | 1498527.5916156755 |

- **Structurally deterministic:** identical roads / junctions / total length to 10 digits on every run.
- **Byte-non-deterministic:** 3 distinct sha256 — serialization ordering / IDs / metadata vary while the map is the same.

## Answer (honest, with claim boundary)
**Natural domain randomization does NOT occur.** Re-running the pipeline on the same OSM reproduces the same map
structure; the byte differences are non-semantic serialization noise, not randomization. Therefore the thesis's
domain randomization must be **EXPLICIT** — do not claim natural DR.

## Explicit DR — `RealismAugmentor` (verified)
- `apply_n(img, 5)` → **5 distinct variants**; changes the input; **deterministic given a seed**; **varies across seeds**.
- Mechanism: image-space augmentation (weather/lighting/texture) applied at capture time; seeded local RNGs (no
  global seeding — HPC/multiproc safe). This is the thesis's controlled, reproducible DR distribution.
- (Memory 2026-08-17: an earlier `dataset_generator` import silently pointed DR at a non-existent module → DR was
  silently disabled; since fixed. The class itself is correct, characterized here.)

## Two findings for the write-up
1. **RQ4:** natural DR absent → explicit DR applied (RealismAugmentor). Multi-map "variability" comes only from
   explicit parameter/seed variation, never from natural randomization.
2. **Reproducibility nuance (feeds C11):** Osm2Odr is byte-non-deterministic, so exact-sha reproduction of the
   seed XODR (and possibly the final candidate) is NOT guaranteed — only **structural** reproduction. Pinning-by-sha
   guarantees *identity of a specific artifact*, not *byte-reproducibility across re-conversions*. Document this in
   the reproducibility claim.

## Deferred (justified)
`generate_n_runs` (full pipeline ×N, ~1.5 h each) is deferred: since the pipeline is structurally deterministic, N
runs on the same OSM only re-confirm determinism and do not change the RQ4 answer.

Machine-readable: `C15_RQ4_DOMAIN_RANDOMIZATION.json`, `determinism/`.
