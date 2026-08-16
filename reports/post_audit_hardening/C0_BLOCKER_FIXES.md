# C0 Blocker Fixes

Date: 2026-08-16

Verdict: PARTIAL_BLOCKERS_REDUCED_G6_REMAINS

## Scope

This pass fixes offline blocker regressions in the C0 clean-regeneration path without mutating or committing map artifacts. It does not claim a pinned auto map, live CARLA loadability, or perception readiness.

## Fixed

| Blocker | Fix | Evidence |
| --- | --- | --- |
| Geometric continuity overclaim | `check_geometric_continuity` now honors OpenDRIVE `contactPoint` semantics and separates junction-connector reference-line offsets from ordinary road-to-road hard failures. | Corrected checker reports 0 ordinary hard issues on the probed crash-safe C0 candidate; 9,192 junction-connector diagnostics remain visible for G4/G6-style lane audits. |
| G19 not enforced at final-stage tolerance | Stage 08 now runs the C3 crash-safe length repair before final integrity completion and raises if violations remain. | Unit test drives a synthetic certifier-tolerance violation to 0 and checks evidence output. |
| Phase-H OSM signal matching in the wrong frame | `phase_h0_osm_signal_extract` now inverse-applies the XODR header offset before planView matching. | Probe moved from 0 matched candidates / 0 signals to 2,595 matched candidates and 3,431 native signals. |
| Native signal enrichment not wired into C0 | Added fail-closed optional native signal enrichment for Stage 08 via `UP_ENABLE_NATIVE_SIGNAL_ENRICHMENT` / `UP_REQUIRE_NATIVE_SIGNALS`. | Missing OSM fails closed in unit coverage; full-map probe emits governed Phase-H signals from the authoritative OSM. |
| Lane-section successor/type defects | Lane-section repair now reclassifies linked plausible-width `none`/`restricted` lanes to driving and mirrors predecessor links only when a compatible driving lane exists. | G4 probe moved from `PHASE_G_LANE_CONTINUITY_BLOCKED` to PASS after repair. |

## Remaining Blocker

G6 coverage is still not fully clean after the safe lane-section repair plus the existing coverage repair:

| Metric | Before repair | After safe repair + coverage repair |
| --- | ---: | ---: |
| `missing_driving_from_coverage` | 138 | 5 |
| `type_incompatible_lanelinks` | 4 | 0 |

The unresolved coverage gaps are concentrated in three unique incoming/junction/lane cases:

| junction | incoming road | lane | incoming end |
| --- | --- | --- | --- |
| 1684 | 47310 | -1 | end |
| 3070 | 47309 | -1 | end |
| 684 | 46620 | 1 | end |

Those five residual G6 records must be resolved before any candidate is pinned or live-tested as drivable. No synthetic routing target was fabricated in this pass.

## Required C0 Runtime Configuration

The clean-regeneration path remains configuration-sensitive. The next C0 run should explicitly set:

```powershell
$env:UP_DISABLE_CARLA = "1"
$env:UP_PREANCHOR_INPUT_XODR = "0"
$env:UP_AUTOFIX_LANE_SUCCESSORS = "1"
$env:UP_ENABLE_NATIVE_SIGNAL_ENRICHMENT = "1"
$env:UP_REQUIRE_NATIVE_SIGNALS = "1"
$env:UP_OSM_FILE = "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm"
```

Strict CRS comparability still requires the manual map reference path to be provided by the C2/B3 registry flow.

## Tests

Targeted offline tests:

```text
46 passed, 4 warnings
```

Full offline suite:

```text
763 passed, 49 warnings in 165.08s (0:02:45)
```

## Boundaries

- No `.xodr` candidate is committed.
- No certifier/gate threshold is relaxed.
- No CARLA runtime is invoked.
- Junction-connector discontinuities are not hidden; they are moved to diagnostic evidence because junction routing is governed by lane links, not generic road-reference-line continuity.
