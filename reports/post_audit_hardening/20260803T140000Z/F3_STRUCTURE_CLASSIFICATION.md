# F3 — road structure classification evidence

- run_id: `20260803T140000Z`
- verdict: **F3_STRUCTURE_CLASSIFICATION_PASS**
- candidate: `raw_xodr_run_1_epsg32632_header_pinned.xodr` (sha256 unchanged: True)
- roads classified: 32710

## Class counts

| class | roads | profile policy |
|---|---|---|
| bridge | 6 | `deck_linear` |
| covered | 2 | `terrain_checked` |
| cutting | 63 | `terrain_following` |
| elevated | 180 | `deck_linear` |
| embankment | 254 | `terrain_following` |
| terrain_following | 31421 | `terrain_following` |
| tunnel | 74 | `deck_linear` |
| underpass | 49 | `deck_linear` |
| unknown | 661 | `fail_closed` |

## Checks

- candidate_sha256_unchanged: PASS
- classification_ok: PASS
- roads_total_equals_frozen: PASS
- structure_identity_established: PASS
- structure_gate_passed: PASS
- unknown_fail_closed_policy: PASS

- matched structure ways: 306 / 0
- matched centreline length: 40056.311 m (0.0255 of 1568868.571 m)
- deck_linear (never ground-DEM forced) roads: 309
- unknown roads: 661 (profile policy: `fail_closed`)

Classification never mutates the XODR document; the structure gate must PASS (fail-closed) before any DEM application, and unidentified roads resolve to the fail_closed profile policy.