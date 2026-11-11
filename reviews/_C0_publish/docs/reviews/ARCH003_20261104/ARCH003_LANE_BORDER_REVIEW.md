# ARCH-003 — Lane-border root cause: independent lane-level verification (2026-11-04)

**Reviewer:** Claude (Opus 5.5), read-only. I made no source edits, branches, pushes or uploads; did
not start CARLA; and did not launch X8.
**Verdict: `REQUIRES_SOURCE_HARDENING`** (see `X8_GO_NO_GO.json`).

| Item | Identity | Provenance class |
|---|---|---|
| Integration | `integration/post-pr16-final-20261102` @ `1a36b560a69286841d4c42973cf00258a38f56c1` | GITHUB_VERIFIED (SHA) |
| GAP-070 candidate | `fix/gap070-connector-snap-exit-20261103` @ `2cee039f235f2cff7c87fa1fce935154cdcf3cd8` | GITHUB_VERIFIED (SHA) |
| C1 | `fix/gap070-connector-snap-safety-c1-20261104` @ `2cee039f` + **uncommitted** edits to `stage_05_geometry.py` and `tests/unit/test_stage05_connector_snap_wiring.py` | LOCAL, work in progress |
| O13 geometry validator | — | **NOT_RUN: does not exist.** `tests/unit/test_o13_configuration_authority_audit.py` is an unrelated older task with the same label. |
| Input | `05_planview_20261007_214826_524342.xodr`, sha256 `45c52059ec5b7d8d1e5f2f90a2f814bde465a923e7e77768c5f5e660790c721c`, 138,932,131 bytes (re-hashed) | LOCAL_REPRODUCED |

## 1. Method (independent of the earlier reference-point checks)

`evidence/lane_centre_continuity.py` evaluates OpenDRIVE lane geometry directly, for **every**
`junction/connection/laneLink`: 23,406 lane links in 22,588 connections.

- **Reference pose:** from the canonical kernel `pose_at_s` (multi-geometry, local-s clamped).
- **Lane-centre lateral offset:** `t(s) = laneOffset(s) + sign(k)·(Σ_{|i|<|k|} w_i(s) + w_k(s)/2)`,
  with laneOffset and width cubic polynomials evaluated in the active laneSection and width record.
  Positive t is to the left, and left lanes have positive ids.
- **Travel heading:** the reference heading, plus π for left lanes (right-hand traffic).
- **Entry:** incoming lane `from`, at the incoming road's end that is linked to *this* junction (road
  `link/successor|predecessor` with `elementType="junction"`), versus connector lane `to` at s = 0.
  All connections use `contactPoint="start"`, and `to` is never a left lane (0 cases).
- **Exit:** connector lane `to` at s = L, versus the exit lane given by that lane's
  `link/successor id`, on the road named by the connector's road-level `successor` at its
  `contactPoint`. 0 lane links were unresolved at either end.
- **Arms on the identical input:**
  - `OFF`: the input as is;
  - `MERGED`: `snap_junction_connectors` from `1a36b560`, applied in memory;
  - `CANDIDATE`: the same function from `2cee039f`.
  Each arm ran in a separate process, so the two module versions never mix.
- **U-turn class:** the incoming lane's travel heading and the exit lane's travel heading differ by
  more than 150°.

**Limitations (stated, not hidden):**
- `<border>` lane records (OpenDRIVE alternative to `<width>`) are not evaluated; none were checked
  for in this map.
- Lane-centre heading uses the reference heading. The width-derivative term is ignored; it is
  < 0.01 rad for the near-constant widths here, but that was not measured.
- Right-hand traffic is assumed (Ingolstadt).
- This is one method. A second, independent implementation (O13 or a lane-centre checker) is still
  required before acceptance.

## 2. Results (`evidence/lcc_*.json`)

All 23,406 lane links:

| Metric | OFF | MERGED (default today) | CANDIDATE |
|---|---|---|---|
| connectors snapped | 0 | 4,025 | 4,025 |
| entry lane-centre gap > 0.1 m | 3,879 | 4,627 | 4,627 |
| entry gap > 1 m | **355** | 4,472 | 4,472 |
| exit gap > 1 m | **341** | 4,458 | 3,824 |
| max gap (entry / exit) | 10.50 / 10.50 m | 14.00 / 14.00 m | 14.00 / 14.00 m |
| entry heading kink > 10° | 3,829 | **459** | **459** |
| exit heading kink > 30° | **359** | 3,728 | 357 |
| entry / exit kink > 150° | 139 / 147 | 139 / 147 | 139 / 147 |

Split by class (`evidence/lcc_off_cls.json`, `lcc_merged_cls.json`):

| Class | Lane links | OFF: entry gap > 1 m | MERGED: entry gap > 1 m | OFF: entry kink > 10° | OFF: exit kink > 30° | MERGED: exit kink > 30° |
|---|---|---|---|---|---|---|
| Non-U-turn | 19,459 | **114 (0.59%)** | **863** | 113 | 111 | 111 |
| U-turn | 3,947 | 241 (but 3,696 > 0.5 m) | 3,609 | **3,716** | 248 | **3,617** |

## 3. Findings

**L-01 (CONFIRMED at lane level): for ordinary connectors, the lane-border hypothesis holds.**
- Without any snap, 19,345 of 19,459 non-U-turn lane links (99.41%) have lane-centre position
  continuity ≤ 1 m.
- The merged default snap adds **749** discontinuities over 1 m (114 → 863) and leaves the heading
  unchanged (113 → 112).
- The snap therefore breaks lane-centre position on outer-lane connectors without improving heading.
  That is exactly the predicted mechanism: the reference line is moved onto the incoming reference
  line, which shifts the lanes by whole lane widths.

**L-02 (NEW, P1): U-turn connectors are lane-discontinuous at source, independent of the snap.**
- Without any snap, 3,696 of 3,947 U-turn lane links have an entry gap > 0.5 m (mostly 0.5–1 m),
  3,716 have an entry kink > 10°, and the exit side is the same.
- The U-turns already exist at stage 01 (ARCH-X8-X9), so this defect is the Osm2Odr U-turn
  representation. It is **not** caused by the snap.
- The merged snap trades the U-turn **entry** kink (3,716 → 347) for **position** gaps over 1 m
  (241 → 3,609) and **exit** kinks over 30° (248 → 3,617). That trade is GAP-070's ~53° kink
  population.
- **Disabling the snap does not fix L-02.** It must stay visible as its own gap; a new GAP id is
  needed.

**L-03: disabling the default snap preserves drivable lane connections strictly better than either
snap variant, on every position metric.** Its only regression is heading at the **entry** of U-turn
links. Those links are discontinuous either way: with the snap off they have sub-metre gaps and about
26° kinks; with it on, gaps over 1 m and about 53° exit kinks. On this evidence, "snap OFF" is the
correct default, and it is **not** a fix for U-turns.

**L-04: the candidate's exit-kink "improvement" (3,728 → 357) comes with 3,824 exit gaps over 1 m**,
against 341 with the snap off. Lane-level measurement confirms the ARCH-X8-X9/ARCH-002 rejection.

**L-05: residual non-U-turn discontinuities with the snap off** (114 entry and 108 exit gaps over
1 m; 111 exit kinks over 30°). This is the true residual GAP-070 population for ordinary connectors,
roughly 0.6%. It must be reported as residuals and must not be hidden by a disabled-snap report
(see C1 finding C1-02).

## 4. What is still not established
- An independent second implementation of the lane-centre metric (required; O13 does not exist).
- `<border>`-record roads, if any, and laneSection changes inside connectors.
- CARLA traversability for any arm (GAP-077).
- A per-id mapping of the 114/108 non-U-turn residuals to causes.
- Whether the 139/147 links with kinks over 150° are GAP-079 stubs or legal reversed reference lines
  (`GAP079_X9B_DECISION_TREE.md`).
