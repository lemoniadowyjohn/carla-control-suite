# Geometry invariant matrix — junction connector refit (2026-11-04)

The columns:
- **Proven:** source code enforces or checks the invariant.
- **Assumed:** the code relies on it without checking.
- **Measured:** this review measured it on the real stage-5 input (sha256 `45c52059…`, local only).

Code references are to the candidate `fix/gap070-connector-snap-exit-20261103@2cee039f`, file
`ultimate_pipeline/tools/junction_connector_snap.py`, unless stated otherwise. Measurements come from
`evidence/x7_geom_audit.json`: 4,025 refits, of which 3,375 are zero-chord U-turns ("U") and 650 are
other connectors ("O").

| # | Invariant | Proven / assumed | Where | Measured | Gate today? | Required gate (X8 / C1) |
|---|---|---|---|---|---|---|
| 1 | Start position = incoming contact point | Proven (checked) | `:413` (1e-6 m) | 0 failures | yes | keep |
| 2 | End position = exit contact point | Proven (checked) | `:413` (1e-6 m) | 0 failures | yes | keep |
| 3 | Start tangent = required heading (contactPoint-aware) | Assumed, and the convention is wrong for flipped cases | `:188`, `:380`; `audit_xodr_visual_geometry.py:73-81` | 0 errors > 10° (no flipped cases on this map) | no | check heading within 1e-6 rad, with the contactPoint flip (F-06) |
| 4 | End tangent = required heading | Assumed (as #3) | `:210-212` | 0 errors > 10° | no | as #3 |
| 5 | World→local frame transform | Proven by construction | `:208-209` | consistent with #1/#2 | n/a | unit test with a rotated frame |
| 6 | `pRange="normalized"` → p = s/length | Proven (kernel) | `opendrive_geometry_kernel.py:48` | — | n/a | keep |
| 7 | `@length` = arc length | **Assumed; violated** | `:205-226` | U: ratio 0.50 (3,375/3,375 off > 10%); O: p50 1.055, 344/650 off > 10%, max 3.71 | no | `|arc/length − 1| ≤ 1e-4` (numerical; F-03) or reject |
| 8 | Regular curve (`|r′(p)| > 0`) | **Assumed; violated** | — | U: 2,734 cusps; O: 0 | no | hard 0 |
| 9 | Simple curve (no self-intersection) | **Assumed; violated** | — | U: 423; O: 0 | no | hard 0 |
| 10 | No overshoot beyond the chord | Assumed | — | U: 2,037 > 0.5 m; O: 0 | no | report only (implied by #8/#9 for U) |
| 11 | Peak curvature bounded | Assumed | — | U: unbounded (p50 3×10¹³ m⁻¹); O: 28 with radius < 2 m (3 before), 81 doubled | no | ≤ max(original peak, boundary curvature) × factor; **the factor is an unresolved decision** |
| 12 | G1 continuity with neighbours | Proven at the endpoints | follows from #3/#4 | yes | no explicit gate | gate on #3/#4 |
| 13 | G2 (curvature) continuity with neighbours | Not enforced | Hermite has free end curvature | jumps up to 7.0 m⁻¹ (O, 68739) | no | report only; whether to require it is **an unresolved decision** |
| 14 | Displacement bounded | **Not enforced** (`rechain_guard_m` deleted) | `:284-302`, `:382` | O: 8 m move on a 3 m road (68739) | no | guard, with the value an **unresolved decision** (F-04) |
| 15 | Degenerate chord / Δhdg≈π excluded | **Not enforced** | — | U: 3,375 | no | hard skip (F-01) |
| 16 | Heading wraparound | Proven | `_norm_angle` `:210` | — | n/a | keep |
| 17 | laneSection / lane width s-ranges valid | Assumed (valid only if #7 holds) | — | not measured | no | assert every s-indexed child is in [0, length] |
| 18 | Lane-boundary / lane-centre continuity at laneLinks | **Not measured anywhere** | — | — | no | new report-only check (F-08) in X8 |
| 19 | Elevation continuity | Not touched by the refit (only valid if #7 holds) | — | not measured | existing stage-5 elevation gates | rerun in X8 |
| 20 | Junction connection / laneLink references unchanged | Proven (only planView is edited) | `:404-418` | — | reciprocity check (integration) | 0 violations in X8 |
| 21 | Atomic restore on failure | Proven | `:393`, `:415` | 0 restores (validation never fails) | n/a | keep, and extend to the new gates |
| 22 | Determinism | Assumed | — | not measured | RQ1 tooling | A vs B structural identity in X8 |

Rows 7, 8, 9, 11, 14 and 15 are the reasons for `REQUIRES_SOURCE_HARDENING`.
