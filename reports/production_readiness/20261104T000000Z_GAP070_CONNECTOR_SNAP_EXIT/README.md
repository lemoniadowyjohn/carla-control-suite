# GAP-070 connector-snap exit preservation

Baseline: `46708baa`.  This change fixes the source-stage connector snap only;
it does not alter the default `UP_ENABLE_JUNCTION_CONNECTOR_SNAP=1`, regenerate
or promote a map, raise a tolerance, or write an XODR during measurement.

## Change

Before moving a displaced connector start, the snap now resolves exactly one
topology-declared road exit anchor.  It replaces the connector planView with one
normalized cubic-Hermite `paramPoly3`, retaining the connector's original length
scale and holding both poses: entry = incoming-road endpoint; exit = declared
exit-road endpoint.  The canonical geometry kernel validates both endpoints
before accepting the refit.  Missing or ambiguous exit anchors fail closed:
the connector is left unrotated and reported as a residual.

The regression fixture is a displaced `paramPoly3` connector.  The old snap
would have joined the entry while rotating its exit tangent; the new test proves
zero entry and exit error after refit.

## In-memory 05_planview measurement

Input: the historical prompt-specified `05_planview` XODR, read-only from the
shared checkout.  SHA-256 before and after was
`45c52059ec5b7d8d1e5f2f90a2f814bde465a923e7e77768c5f5e660790c721c`.

| metric | before | after |
| --- | ---: | ---: |
| connector start mismatches | 4,092 | 67 |
| connector end mismatches | 4,043 | 560 |
| junction-exit heading discontinuities | 351 | 349 |
| 53-degree exit bucket | 4 | 4 |
| junction-exit geometry gaps | 0 | 0 |
| connectors snapped | — | 4,025 |
| residuals | — | 0 |

All 4,025 refits recorded per-connector entry and exit error before/after in
`measurement.json`; each accepted refit ended at 0 m for both anchors.  The
entry-side benefit is retained while the exit result remains at the pre-snap
population rather than creating the historical 3,373 53-degree kinks.

## Verification

Executed with E:-resident pytest temporary directories:

- `ultimate_pipeline/tests/unit/test_junction_connector_snap.py`: 8 passed.
- `ultimate_pipeline/tests/unit/test_check_road_link_reciprocity.py`: 17 passed.

Residual risk: Hermite endpoint preservation establishes C0 position and tangent
at both declared anchors, but a governed full-map regeneration and independent
quality review are still required before any default decision or map promotion.
