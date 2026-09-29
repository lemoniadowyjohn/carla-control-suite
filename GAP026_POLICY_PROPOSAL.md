# GAP-026 Policy Proposal — Junction Lane-Link Pose Continuity

**Status: DRAFT — FOR INDEPENDENT REVIEW ONLY**
**Precondition:** Methodology validated per `GAP026_METHOD_VALIDATION.json` (verdict `MAP_DEFECT_CONFIRMED`, oracle intersection 2992/2992, kernel vs. `opendrive_geometry` delta 0 m). No hard gate may be wired until this proposal is independently reviewed and approved.

---

## 1. Context

- **Map-of-record:** `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr` — `verify_pinned_map("auto_map_of_record")` → SHA256 `370abbbb...c8c8`, 149,799,632 bytes, frame `rebased-to-local (dx=832671.676 dy=5458671.104)`.
- **Current signal (validated):** 23,529 laneLinks checked, 2,992 failed (12.72%), 832 > 3 m, maximum 14.0 m. Reference-line coincidence is intact for 98.5% of failures (807/832 >3 m have ref ≤ 0.25 m) — the defect is lane-center pairing, not reference geometry.
- **Prior state:** `sanitize_junction_lane_links` is wired in `stage_08_integrity.py:560` and writes `junction_lanelink_sanity.json` on every run, but its `status`/`failed` fields are never consumed by any `hard_fail_reasons`/`valid_for_experiments` gate (`grep -rn junction_lanelink_sanity` — write-only). The gap register (GAP-026 entry dated 2026-09-24) correctly characterizes this as *measured but not gating*.

This proposal defines how the validated checker should become a gating signal, with explicit tolerance, warning bands, and waiver semantics, **without mutating the promoted map, changing tolerance, or wiring a hard gate before review**.

---

## 2. Definitions

- **Position metric:** Euclidean distance (m) between independent lane-center world poses at the junction interface. Lane center = reference pose + lateral, where lateral = `(preceding_width + width/2) * sign + laneOffset`. Implemented independently in `gap026_oracle.py:lane_center_oracle` and cross-validated against both geometry kernels.
- **Angular metric:** Absolute heading discontinuity (degrees) after applying `contactPoint` orientation (`heading_target = connecting_heading + (0 if start else π)`), wrapped to `[0,π]`.
- **Scope:** Only `<junction><connection><laneLink>` elements where both `incomingRoad` and `connectingRoad` resolve. `from` is evaluated at `incomingRoad` **end**; `to` at `connectingRoad` **start** if `contactPoint=start` else **end**.

---

## 3. Proposed Thresholds

| Signal | Hard failure | Warning band | Pass | Rationale |
|---|---|---|---|---|
| **Position** | `> 0.50 m` | `0.25–0.50 m` | `≤ 0.25 m` | 0.25 m is the checker's current inclusive tolerance. Empirical stratification shows 57.5% of all failures (1,721) sit exactly in `0.25–0.50`, dominated by a single systematic width mismatch (1,489 with `Δwidth=0.50 m → Δlateral=0.25 m`, i.e., incoming 3.0 m vs. connector fallback 3.5 m). Hard at 0.50 m separates this correctable width-tier inconsistency (fixable by width harmonization) from lane-count mispairing (≥ 3.5 m) which is the genuine severe tail. A hard at 0.25 m would fail-closed on a bounded, non-safety-critical width artifact; a hard at 1.0 m would silently waive 292 `1–3 m` cases that already combine lateral+angular error and are visible as lane jumps. |
| **Angular** | `> 12°` **and** `position > 0.25 m` (conjunctive) or `> 30°` standalone | `12–30°` with `position ≤ 0.25 m` (heading-only) | `≤ 12°` | 451/2,992 failures (15%) exceed 12°. The solitary `heading_only` case (junction 3125, conn 4, −1→−1, 0.143 m / 175.3°) proves heading-only failures exist but are rare (1/23,529). Conjunctive hard prevents a noisy heading sensor spike from failing a geometrically sound link. Standalone `>30°` captures reversed or kinked connectors (57 cases `90–120°`, 136 `>120°`) that are safety-relevant even when position happens to be small (e.g., micro-stub advisory pattern excluded). |
| **Population** | Hard if `> 2%` of checked links are `> 0.50 m` **or** `> 0.5%` are `> 3 m`, irrespective of per-link pass rate | Warning if `> 5%` are in `0.25–0.50` | — | Absolute per-link thresholds alone would allow a map with thousands of 0.49 m errors to pass. Population caps enforce systemic quality: current map has 12.7% overall failure, 2.92% in `0.5–1 m` + `1–3 m` + `3–5 m` + `5–10 m` + `>10 m` (≈ 686+123+23+292+146 = 1,270 ≈ 5.4% >0.5 m) and 3.54% >3 m (832/23,529) — both would hard-fail under this rule, which is intentional. A future repaired map targeting `<1%` overall `>0.25 m` and `<0.1%` `>3 m` would be production-grade. |

**Tolerances are inclusive:** `≤ 0.25` passes. The checker uses `<=` (verified in `lanelink_builder.py:265`). Distance = `0.2500000001` fails; `0.25` exactly passes. Floating-point tie at `0.25` observed in 1,721 bucket is within `±1e-9` of kernel agreement, so inclusive semantics does not materially change the count (verified: flipping to `<` would add ≤ 10 cases).

---

## 4. Warning Band Handling

- `0.25–0.50 m` is **not** a hard failure but is **not** invisible.
- It must be emitted as `WAIVED`-eligible `INCOMPLETE`/`FAIL` with a recorded waiver (per `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:waiver_schema`) rather than silent `PASS`. The contract already forbids `SKIPPED`-as-`PASS`; this band would be reported as `FAIL` with `waiver_status=WAIVED` and explicit rationale, not suppressed.
- Rationale for warning (not hard): the 1,721 count is 98% width-mismatch (checker-validated, no bias). The fix is width harmonization (see `GAP026_ROOT_CAUSE.md`), not geometry rework, and the lateral error (0.25 m) is at the threshold of visual perceptibility in CARLA but below the lane-edge crossing.

---

## 5. Minimum Affected Population & Promotion Block

- **Hard-fail population gates** (see §3) apply even if individual link metrics are marginal. A map with 23,529 links and 50 hard failures (`>0.50 m`) spread across 30 junctions is more concerning than the same 50 clustered in one junction (which might be a single localized defect). Therefore:
  - **Hard:** `>0.50 m` count > 2% of checked (currently 5.4% → fail) **or** `>3 m` count > 0.5% (currently 3.54% → fail) **or** distinct junctions with hard failures > 10% of total junctions (currently 491 distinct / ~3,561 junctions ≈ 13.8% → fail).
  - **Warning:** `0.25–0.50` population > 5% (currently 7.31% → would trigger warning even after hard thresholds are tightened).

These population gates prevent a per-link tail from being dismissed as "outlier."

---

## 6. Exception / Waiver Semantics

- **No anonymous suppression.** Per `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:waiver_schema`, a `WAIVED` status requires: `identifier, gate_id, exact_issue, owner, evidence, rationale, expiration_or_review_trigger`. Example waiver for the warning band:
  ```yaml
  identifier: WAIVER-GAP026-WARN-2026-09-24-001
  gate_id: junction_lanelink_pose_continuity
  exact_issue: "1721 links in 0.25-0.50 m, 1489 due to incoming 3.0 m vs connector 3.5 m width tier"
  owner: "map-maintainer (reviewed by independent auditor)"
  evidence: ["GAP026_METHOD_VALIDATION.json", "GAP026_FAILURE_POPULATION.csv", "junction_lanelink_sanity.json"]
  rationale: "0.25 m is half-width difference of documented fallback tier; no traversability loss; fix is width harmonization in stage_07_lanes, not geometry; lateral error < half lane width"
  expiration_or_review_trigger: "re-review when stage_07 lane_width_policy harmonization lands or at next map regen"
  ```
- **No blanket waiver for `>0.50 m` or `>3 m`.** Waivers for hard buckets are only allowed if the affected links are proven **non-traversable** (e.g., `lane type != driving`, `access=restricted`, or `junction type=virtual` with explicit `defer` tag) and the waiver enumerates every `junction_id/connection_id/from/to` with per-link evidence. Current `>3 m` population is 832/832 `driving` (see `GAP026_METHOD_VALIDATION.json:gt3_clustering.traversable_driving_links`) — therefore **not waivable**.
- **Outer-lane isolation waiver (bounded):** The 704 `>3 m` failures where `incoming lane count != connecting lane count` (677 `outer→inner` mispairings, multiples of 3.5 m) indicate a lane-count synthesis gap, not a per-link geometry error. A *temporary* waiver may be granted **only** if: (a) the waiver enumerates every outer lane (`from=-n` where `n = incoming_count`) across 628 distinct incoming roads / 756 connecting roads, (b) the map is regenerated with new connectors or with outer lanes explicitly left unlinked (i.e., laneLinks for outer lanes removed and `component_reachability` documents isolated outer components as expected), and (c) the waiver expires at the next connector-generation fix. The waiver does not make the map production-grade; it only allows `research_release` with `WAIVED`.
- **Angular-only waiver:** `heading_only` (1 case) may be waived if the heading discontinuity is on a micro-stub (`road length < 1.0 m`) and `reference distance ≤ eps` — matching the existing `micro_stub_heading_advisory` pattern already used in `check_geometric_continuity`. This is a 1-row waiver, not a class waiver.

---

## 7. Evidence Required for Promotion

A candidate map may only be promoted to `auto_map_of_record` when, **in addition to the existing `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:production_candidate` gates**, it provides:

1. **Governed regeneration receipt:** `final_artifact_receipt.json` (via `ultimate_pipeline/contracts/artifact_authority.py:resolve_final_artifact_receipt`) proving the XODR on disk is the governed output, not a hand-edited copy. No direct XODR coordinate patch is permitted unless the patching stage is the canonical transformation for that coordinate (see `GAP026_ROOT_CAUSE.md` §4).
2. **Structural fingerprint comparison:** `structural_signature` / `map_content_fingerprint.json` showing `roads`, `junctions`, `lanes`, `laneLinks` counts vs. previous pin, with `semantic_hash_algorithm c55v01a-xodr-structure-v1` stable. The laneLink count change must be justified (e.g., outer lanes unlinked → count decreases).
3. **RQ2 metrics:** Local re-verification (hull footprint) — road length ratio, junction ratio, lane count, `component_reachability` (isolated lane components) — must not regress beyond the current research bounds (`2.68× / 3.78× / 3.56×` ratios ± tolerance).
4. **Lane-link failure distribution:** Fresh `junction_lanelink_sanity.json` from the validated checker (both oracles agree), plus `GAP026_FAILURE_POPULATION.csv`-style stratification (distance buckets 0.25–0.5 / 0.5–1 / 1–3 / 3–5 / 5–10 / >10 and angular buckets). Hard buckets must be 0 unless an explicit per-link waiver exists.
5. **Static CARLA gates:** `StrictCarlaOpendriveGate`, `preflight_xodr_loadability`, `xodr_xml_integrity`, `junction_integrity` — all `PASS` against the candidate. `visual_cooked_map_certificate` offline fields remain `INCOMPLETE` until Phase J is wired (per contract), but that does not block `production_candidate` if offline fields are `PASS`.
6. **Final receipt comparison:** Candidate vs. old pin diff for: `roads, junctions, lanes, structural fingerprint, RQ2 metrics, lane-link failure distribution, static CARLA gates, final receipt` — all enumerated in the task's "Any corrected map must be regenerated…" clause.

---

## 8. Rollout Plan (No Code Yet)

1. Independent review approves this proposal and the methodology in `GAP026_METHOD_VALIDATION.json`.
2. Implement the policy as a **soft** gate first: wire `sanitize_junction_lane_links` into `scripts/measure_candidate_acceptance.py` and `ultimate_pipeline/quality/map_acceptance.py` to emit `FAIL`/`WAIVED`/`PASS` per §3 without blocking `valid_for_experiments`. Collect one full-map run of evidence.
3. After one clean run with the soft gate, promote to hard gate: add `junction_lanelink_pose_continuity` to `PRODUCTION_MAP_QUALITY_CONTRACT.yaml:production_candidate.required_gates` with `fails_closed_on: [FAIL]` and the population caps in `map_acceptance.py:hard_fail_reasons`.
4. Never mutate the promoted map in place. Any repair is a governed regen (see root cause).

---

## 9. Non-Goals

- No change to the current pin's tolerance (0.25 m / 12°) in this proposal.
- No wiring of a hard gate before independent review.
- No direct XODR coordinate patching (see root cause).

---

*Author: GAP-026 forensics (read-only discovery, independent oracle, both geometry authorities). Verification: `verify_pinned_map("auto_map_of_record")` SHA256 `370abbbb...c8c8`, bytes 149799632. Baseline SHA `98d47e38` + worktree evidence preserved per L4 coordination rules.*
