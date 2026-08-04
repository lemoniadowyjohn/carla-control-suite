# I — Tiling strategy and tile equivalence

- run_id: `20260804T060000Z`
- verdict: **PHASE_I_TILING_PASS**

## Strategy (three concepts, not mixed)

1. **XODR logical partitioning** — NOT applied to the cooked campaign; the candidate is one logical CARLA map identity (32710 roads, single document). Partitioned builds remain supported by the hardened tiler (observation windows + context duplication).
2. **Unreal visual-asset tiling** — import-time (CARLA editor); no per-tile markers in XODR (I5).
3. **CARLA map identity** — one logical map per campaign.

## I1 curve-aware bounds

- geometry_curve_extrema: 10553
- geometry_kind_counts: {'line': 26220, 'paramPoly3': 54041}
- max_geometry_bounds_delta_m: 37.111
- roads_curve_extrema_beyond_endpoints: 10540
- roads_scanned: 32710
- threshold_m: 0.5

## I2 ownership policy

- policy: `midpoint` (reference-line midpoint)
- assigned: 1373 / unassigned: 31337 (expected: roads whose midpoint falls outside the 4-tile observation window are not owned by any window tile)
- junction context: all roads of a junction co-assigned to the majority tile; context duplication via buffer; ownership out of band.

## I3 junction-cut prevention

- window junctions: 142
- junctions with missing roads in union: 0
- split junctions (incomplete in every straddled tile): 0
- dangling lane links in tiles: 0

## I4/I5/I8 equivalence (untiled source vs union of tiles)

- core roads: 1414 / union roads: 1555
- missing core roads: 0
- byte violations: 0
- duplicated (context) roads: 69, non-identical: 0
- inventory mismatches: 0

## I6 adjacency and seams

- adjacency ok: True (6 edges)
- border roads total: 10, not context-duplicated: 0

## I7 fail closed

- release_profile_flag_exists: PASS
- run_full_test.py: PASS
- run_thesis_final_experiments.py: PASS
- stage_09_profile_consumed: PASS

Tiles (observation windows over the window origin) are stored under `tiles/`; ownership/health are recorded out of band in this report.