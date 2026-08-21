# C11 — Reproducibility is STRUCTURAL, not byte-exact (Osm2Odr non-determinism)

## Finding (from RQ4 / C15)
`carla.Osm2Odr.convert()` on the **same pinned OSM** (`b9e07465`) is **structurally deterministic** but
**byte-non-deterministic**. Three runs (`C15_RQ4_DR/determinism/`):

| run | sha256 (byte) | num_roads | num_junctions | total_road_length |
|---|---|---|---|---|
| 0 | `7d64a2c0…` | 32920 | 3717 | 1498527.5916156755 |
| 1 | `d814f0ca…` | 32920 | 3717 | 1498527.5916156755 |
| 2 | `3775b65f…` | 32920 | 3717 | 1498527.5916156755 |

Identical structure (roads / junctions / length to 10 digits), **3 different sha256** — serialization ordering /
element IDs / metadata vary run-to-run while the map is the same.

## Implication for the pinning-by-sha reproducibility claim (C11)
`INPUTS_MANIFEST` + `scripts/regen_map_of_record.py` pin artifacts by sha256. That correctly guarantees the
**identity of a specific pinned artifact** (the map-of-record `69b1f520` is exactly those bytes). But it does NOT
guarantee **byte-reproducibility across re-conversions**: re-running the canonical regen from the pinned inputs
produces a **structurally-equivalent** map with a **different** seed sha (and therefore a different final sha).

**So the honest reproducibility claim is:**
> The pinned map-of-record is a specific, digest-identified artifact. Re-running the canonical regeneration from the
> pinned inputs reproduces the map **structurally** (identical road/junction counts, total length, topology, and
> acceptance verdict) but **not byte-exactly**, because `Osm2Odr` serialization is non-deterministic. Reproducibility
> is verified by the **structural signature + acceptance gates**, not by seed/candidate byte-sha equality.

Do NOT claim "re-running yields sha `69b1f520`." Claim "re-running yields a structurally-identical, acceptance-passing
map; `69b1f520` is the pinned instance used for all downstream RQ artifacts."

## Recommended hardening (follow-up)
1. **Record a structural signature** in `regen_provenance.json` — `{num_roads, num_junctions, total_road_length}`
   (frame-invariant) as the reproducibility ANCHOR, alongside the sha (which identifies the specific instance).
2. Add a `--verify-structural <xodr>` mode to `scripts/regen_map_of_record.py` that re-runs the conversion and
   asserts the structural signature matches (not the byte sha) — the correct reproducibility check.
3. State the structural-not-byte reproducibility boundary in the thesis reproducibility section.

## Why this matters (not a defect — a claim boundary)
This is not a bug in Osm2Odr or the pipeline; it is an inherent property of the converter. Surfacing it keeps the
reproducibility claim defensible: a reviewer who re-runs the pipeline and gets a different sha has NOT found a
reproducibility failure — they've reproduced the map structurally, which is what the claim guarantees.
