# Proposed gap register addendum 3 (DRAFT, append-only, not committed)

This addendum amends addendum 1 (`20261103T000000Z_…`) and addendum 2 (`20261104T000000Z_…`, sha256
`5f59fc60…`) by id. **Neither of them is modified.** The machine-readable version is
`GAP_REGISTER_ADDENDUM_3_PROPOSED.json`, built by `evidence/build_addendum3.py`, which reads both
earlier addenda to compute the register state.

**ID check:** no GAP-080 or higher exists on any local or origin branch. GAP-080..084 in the
unregistered ARCH-X8-X9 backlog draft are superseded by this allocation.

| ID | Kind | Status | Severity | Summary | Evidence class |
|---|---|---|---|---|---|
| GAP-070 | evidence_update | open → **open** | P2 (**proposed P1**) | Splits the GAP into (a) default-snap corruption at lane level, (b) the candidate `2cee039f` rejected, (c) safe default-OFF containment (C1, uncommitted), (d) remaining residuals, (e) missing independent validator, (f) pending X8 from raw OSM | LOCAL_REPRODUCED (one implementation) |
| GAP-079 | evidence_update | open → **open** | P2 | **Source attribution corrected** to `UNKNOWN_PENDING_RAW_OSM_REPRODUCTION`. The 2026-10-07 run's input was the map-of-record XODR (`370abbbb…`), not OSM. The counts stand as population counts (58 → 81). | LOCAL_REPRODUCED (counts); origin NOT_RUN |
| **GAP-080** | new | **open** | P1 | U-turn connectors are lane-discontinuous with no snap: 3,696 of 3,947 U-turn laneLinks have an entry lane-centre gap > 0.5 m; median 0.7467 m, median heading difference 26.565° (= atan ½); systematic. **Not** claimed to be undrivable. | LOCAL_REPRODUCED (one implementation) |

**Register state after the addendum:** 25 total; 19 fixed; 5 open (GAP-070, 076, 078, 079, 080);
1 blocked_external (GAP-077).

**To commit later (operator approval needed):**
1. Copy both files to `reports/production_readiness/<UTC>_GAP_REGISTER_ADDENDUM_3/`, and replace
   `run_id` with that name.
2. Keep the `reviews/…` evidence paths valid, either by publishing the review package (C0) first or
   by citing evidence hashes.
3. Make it a docs-only commit; `git diff --stat` must show only the new directory.
