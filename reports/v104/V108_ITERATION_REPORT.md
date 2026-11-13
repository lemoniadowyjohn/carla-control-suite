# V108 — Iteration report: CI reconciliation, adversarial QA, production closure

**Author:** OpenCode
**Date:** 2026-11-13
**Production lineage:** `integration/production-large-map-20260918` @ `225ed15d0da6444cc257835ca777aba281553f3c` (re-verified at the start of this iteration, unchanged)
**Release verdict: NO_GO** — see §9.

---

## 0. What this iteration did

| Phase | Outcome |
|---|---|
| Phase 1 — reconcile and validate the four V107 patches | **4 / 4 reviewed, verified and integrated.** One was materially better than its own description. |
| Phase 1 — resolve the bot review threads on my own PRs | **33 / 33 replied to and resolved** (5 on #39, 7 on #40, 21 on #41). |
| Phase 2 — O3 topology gaps | **One P0 defect found, fixed and measured on the real map** (the undecidable-direction defect). |
| Phase 3 — O1/O2 semantics | Partially surveyed; `oneway:conditional` / `junction` retention and conditional/reversible authority were **already correct** on #39. |
| Phase 4 — GUI / CI / packaging | The 6 GUI false-success defects were made **visible and reproducible**; the 3 wrong branch-protection context names were corrected. |
| Phase 6 — integrated candidate | **NOT built** — see §8 for why this is the correct next step rather than a skip. |

---

## 1. Authoritative re-fetch

Everything below was re-fetched at the start of this iteration; the values
may have moved during it.

```
origin/integration/production-large-map-20260918   225ed15d0da6444cc257835ca777aba281553f3c   (UNCHANGED)
origin/fix/v86-acceptance-strict-schema-20261111   4d38a1fc -> 21dce53c   (PR #30, Codex)
origin/fix/v94-worktree-lease-20261112              a72700bb -> e44e230e   (PR #37, Codex)
```

46 pull requests exist. New branches appeared during the iteration for the
V117/V119/V121/V122 research work (`#52`–`#55`), which is another agent's
scope.

---

## 2. Phase 1 — the four V107 patches: reviewed, verified, integrated

All four are **my own** follow-up PRs, stacked on my owner branches. Per
V108 Phase 1 item 8 they were integrated into their owner branches without
changing unrelated files.

### #44 — GUI adversarial test discovery  → **ACCEPTED**

| | |
|---|---|
| Base | `fix/v104-gui-authority-adversarial` @ `bf9ba23f` |
| Head | `19a4c2e13430628ca7ea75923a65311e81b86a8f` (2 commits) |
| Scope | rename only: `tests/unit/v104_gui_authority_adversarial.py` → `tests/unit/test_v104_gui_authority_adversarial.py` |

**Fail-before** (base `bf9ba23f`): `py -m pytest tests/unit/ --collect-only -q`
→ the suite is **not collected at all**. `pytest.ini` sets
`python_files = test_*.py`, and the old name does not match it.

**Pass-after** (head `19a4c2e1`): **15 tests collected**; 9 pass and
**6 fail**.

Those 6 failures are the V108 Phase 4 GUI false-success defects, and per
V108 Phase 1 item 3 they are **not suppressed**:

```
FAILED test_unbound_pass_verdict_is_not_a_success
FAILED test_unbound_pass_verdict_with_a_forged_success_marker_is_not_a_success
FAILED test_stale_verdict_from_a_previous_run_is_not_a_success
FAILED test_contradictory_verdict_is_not_a_success
FAILED test_pass_with_a_missing_acceptance_receipt_is_not_a_success
FAILED test_verdict_with_a_mismatched_artifact_digest_is_not_a_success
```

The GUI source is a Codex single-writer file, so OpenCode does not repair
them; the value of #44 is that they are now **visible to CI at all**.

**Note on the CI failure claim in the V108 brief:** the four collection
errors in workflow run `43252157591` are **pre-existing in the GUI lineage**
— they reproduce on the unmodified base `bf9ba23f` (25 collection errors,
verified). They are **not** a regression from #44. `PyQt6` is not installed
in this environment, but the V104 GUI adversarial suite does **not** need
it — it imports `ultimate_pipeline.gui.jobs.governance` and runs.

### #45 — registry drift is terminal  → **ACCEPTED**

| | |
|---|---|
| Base | `fix/v103-o3-osm-road-graph-orphans` @ `5d35015c` |
| Head | `e60c8182a...` |
| Scope | `reports/v103/o3/run_orphan_reconciliation.py` + 1 test file |

**The defect was real.** The pre-fix runner set `BLOCKED_INPUT` on a digest
mismatch and then **continued**; the later unconditional
`report["status"] = "PASS"` (line 224) overwrote it.

**Fail-before**, executed against the old runner source in the O3 worktree:

```
"status": "PASS"
WROTE .../ORPHAN_ROAD_SOURCE_RECONCILIATION.csv
F ...test_v107_o3_registry_drift_failclosed.py:47: assert 0 != 0
FAILED test_candidate_registry_digest_drift_is_terminal[000...0-candidate_digest_differs_from_registry_pin]
FAILED test_candidate_registry_digest_drift_is_terminal[None-candidate_registry_digest_missing]
2 failed
```

The runner returned **0** (success) for a candidate whose digest does not
match the registry pin, and wrote the reconciliation CSV.

**Pass-after:** 2 passed. The runner now exits non-zero, writes the JSON
with `BLOCKED_INPUT`, and writes **no CSV**.

### #46 — canonical OpenDRIVE geometry and elevation  → **ACCEPTED**

| | |
|---|---|
| Head | `941212bc4...` |
| Scope | `ultimate_pipeline/topology/orphan_road_repair.py` + 1 test file |

**Canonical kernel reuse verified (V108 Phase 1 item 5):** the patch imports
the canonical kernel directly —
`from ultimate_pipeline.geometry.opendrive_geometry_kernel import (endpoint as _kernel_endpoint, pose_at_s as _kernel_pose_at_s)` —
so there is **no duplicated geometry rule**. Elevation has no canonical
evaluator in the repository (the `quality/` elevation modules are checkers,
not a shared evaluator), so a local `_road_z` is not a duplication.

**Fail-before → pass-after: 4 failed → 4 passed**, against the pre-#46 source:

| Test | Pre-fix failure |
|---|---|
| `test_true_arc_endpoint_connects_to_next_road` | `assert 2.0 == 12.0` — the arc endpoint was a straight chord |
| `test_normalized_parampoly3_endpoint_is_not_straight_projected` | paramPoly3 endpoint wrong |
| `test_elevation_at_geometry_end_is_not_first_record_constant` | elevation copied from the first record instead of evaluated at s |
| `test_unsupported_geometry_does_not_invent_straight_endpoint` | `[(0,0,0)] == []` — malformed geometry invented an endpoint |

### #47 — branch protection context names  → **ACCEPTED**

| | |
|---|---|
| Base | `fix/v103-o5-ci-audit` @ `9b0d508c` |
| Head | `2f64b3eb5b5ce5c6d2f67b97e2850d7fbe1d43b9` |

The real job display names in `.github/workflows/tests.yml` are:

```
offline-tests           -> offline tests
package-wheel-smoke     -> package / wheel smoke
governance-integrity    -> governance integrity
thesis-rq-contract      -> thesis RQ contract
research-provenance     -> research provenance
offline-evidence-graph  -> offline evidence graph / freshness
offline-release-gate    -> offline release gate
windows-single-writer   -> Windows named-mutex arbitration
```

My PR #41 checklist had **three wrong names**
(`thesis rq contract`, `offline evidence graph`, `windows single writer`).
Requiring those would have blocked **every** merge.

**Fail-before → pass-after: 1 failed → 1 passed**, and the failing diff
names the three wrong entries exactly.

#47 also repairs a **corrupted paragraph** I had introduced in PR #41: my
earlier patch inserted a correction *before* the original sentence instead
of replacing it, leaving this dangling in the owner-facing checklist:

> “…the test would itself rewrite production history. **— push a throwaway
> commit to the production branch** with the gate not run and confirm the
> push is REFUSED by GitHub…”

That is an instruction to push to production. #47 replaces the whole
region with a safe procedure (disposable test branch, API-confirmed
ruleset scope, non-destructive rejected operation, `CONTROL FAILURE` on an
unexpected success).

### Integration result

| PR | Owner branch | Result |
|---|---|---|
| #44 | `fix/v104-gui-authority-adversarial` | fast-forward → `19a4c2e1` |
| #45 | `fix/v103-o3-osm-road-graph-orphans` | fast-forward → `e60c8182a` |
| #46 | `fix/v103-o3-osm-road-graph-orphans` | merge (no file overlap with #45) → `fc8958e3` |
| #47 | `fix/v103-o5-ci-audit` | fast-forward → `2f64b3eb` |

All four owner branches were pushed.

---

## 3. Review threads — 33 / 33 resolved

| PR | Threads | Unresolved before | Unresolved after |
|---|---|---|---|
| #39 | 23 | 5 | **0** |
| #40 | 7 | 7 | **0** |
| #41 | 21 | 21 | **0** |

Every thread received a reply naming the concrete fix and the named
regression test, and was then resolved through the GraphQL
`resolveReviewThread` mutation. Nothing was resolved without both.

The 5 that were still open on #39 were individually re-verified before
resolution (all 5 named tests run and passing):

```
test_4551555409_odd_lane_total_keeps_the_historical_side_assignment  PASSED
test_4551555419_unsupported_oneway_does_not_pass_coverage             PASSED
test_4551555425_structural_extractor_keeps_junction_and_conditional   PASSED
test_4551582252_unknown_orientation_is_not_authoritative              PASSED
test_4551582490_reversed_correspondence_survives_the_stage_hand_off   PASSED
```

`test_4551582490` was checked to assert `ORIENTATION_REVERSE` through
`_build_structural_osm_metadata`, which is exactly what the finding asked
for — it was not a weakened assertion.

The two PR #41 findings that were **false** (`4551933360`, `4551961633`,
the "36-character action ref" claim) were resolved with an explicit
**RETRACTION** reply rather than a fix, because the correct disposition of
a false finding is to withdraw it.

---

## 4. Phase 2 — new defect found, fixed and measured on the real map

### V108-O3-DIRECTION-AUTHORITY (P0, fixed)

**The defect.** `ultimate_pipeline/quality/osm_road_link_topology.py`:

* `_way_is_oneway_forward` returned `ONEWAY_UNKNOWN` both for a way with
  **no** `oneway` tag **and** for the genuinely undecidable cases
  (`oneway=reversible`, `oneway:conditional`, an unrecognised value);
* `_can_leave` / `_can_enter` then returned **`True`** for
  `ONEWAY_UNKNOWN` — *"bidirectional / unknown -- it may leave anywhere"*;
* the restriction extractor dropped `oneway:conditional`, `reversible` and
  `highway`, so the module could not even see a conditional restriction.

The consequence is precisely what the brief forbids: **an undecidable
source was treated as proven legal movement.** On the pinned real OSM,
**14,851 of 17,200 ways** — every way without an explicit `oneway` tag —
were traversable in every direction, and such a pair could authorize an
orphan-road repair.

**The fix.**

* the extractor retains `oneway:conditional`, `reversible` and `highway`;
* a way with **no** `oneway` tag is `bidirectional` — the OSM default is a
  **proven** two-way fact, not missing evidence;
* `oneway:conditional` / `oneway=reversible` / an unrecognised value is
  `unknown` — **not assessable**;
* a `motorway` / `motorway_link` without an explicit `oneway` is the OSM
  implicit one-way (an explicit tag still wins);
* `unknown` is **not traversable**, and is reported in its own
  `not_assessable` bucket (payload + `summary.not_assessable_count`), so
  *"we could not prove this movement"* is never rendered as *"this movement
  is blocked"* nor as *"this movement is proven legal"*.

**Measured on the pinned real OSM** (`b9e07465…`, 17,200 highway ways):

| Measure | Before | After |
|---|---|---|
| ways in state `unknown` | **14,851** | **4** |
| ways in state `bidirectional` | 299 | 15,146 |
| ways carrying `oneway:conditional` | **0** | **4** |
| `adjacency_edge_count` | 25,435 | **25,419** |
| `not_assessable_count` | *did not exist* | **32** |
| `unresolved_count` | 904 | **0** |

16 adjacency edges were removed — they existed only because an
undecidable way was being treated as proven legal movement.

**Real-map outcome unchanged.** The O3 orphan reconciliation over the
registry-pinned map-of-record (`370abbbb…`, 32,267 roads) reports
`orphan_count 0 / repaired_count 0 / unresolved_count 0` and `PASS`
**before and after** — the two report JSONs are byte-identical. **No frozen
evidence changes.**

**Tests.** `tests/unit/test_v108_o3_direction_authority.py`, 11 tests.
Fail-before / pass-after, executed: **8 failed → 11 passed**.
O3 suite including the #45 and #46 regressions: **64 passed**.

**Commits.** `5a360c600af940c78d82ca6e4a14e9f69c67ce07` on
`fix/v103-o3-osm-road-graph-orphans`.

### Phase 2 / Phase 3 survey — what is already correct

Verified directly in the **current** trees (an earlier read-only subagent
survey was discarded because it inspected the stale `C:` checkout rather
than the `F:` worktrees):

| Defect class | Status |
|---|---|
| Interior OSM nodes | **HANDLED** — `role = "interior"` at `osm_road_link_topology.py:328`, registry T09 |
| Directed adjacency | **HANDLED** — `directed[(way_id, other_id)]` evaluated per ordered pair |
| Departure vs arrival separation | **HANDLED** — `_can_leave` / `_can_enter` |
| Bridge/tunnel vs grade-separated crossing | **HANDLED** — structure-transition rule (finding 4551845530) |
| Vehicle access inheritance | **HANDLED** — `vehicle` in the access hierarchy (4551845558) |
| Registry-pin map identity | **HANDLED** — #45 |
| Canonical geometry | **HANDLED** — #46 |
| `oneway:conditional` retention | **HANDLED on #39** — in `_STRUCTURAL_LANE_METADATA_TAGS` and `_POSITIONED_METADATA_TAGS`; **WAS MISSING on #40** and is fixed by V108-O3-DIRECTION-AUTHORITY |
| Conditional / reversible / unknown direction authority | **HANDLED on #39** (`OnewayState.REVERSIBLE`, conditional never authoritative); **WAS MISSING on #40** and is fixed by V108-O3-DIRECTION-AUTHORITY |
| Motorway implicit one-way | **HANDLED on #39** (finding 4551582303); **added to #40** by V108-O3-DIRECTION-AUTHORITY |
| OSM shared nodes unrelated to the XODR endpoints | **NOT YET ADDRESSED** — open |
| Duplicate / contradictory / nonreciprocal road-lane links | **NOT YET ADDRESSED** — open |
| O2 legal-movement graph (restriction relations, `only_*` / `no_*`, via-node / via-way) | **NOT STARTED** — open, large |

---

## 4a. V106 Priority 0 item 1 — the XML admission P0 is REPAIRED and independently VERIFIED

PR #30's branch advanced during this iteration from `4d38a1fc` to
`21dce53c1`. Codex has landed a dedicated
`ultimate_pipeline/quality/xml_admission.py` (190 lines) and rewired the
active parsers through it. OpenCode verified this **read-only**, on the
exact PR head, using the original V104 reproduction cases (written before
the repair existed).

### The three original bypasses are dead

| Case | Pre-repair (head `4d38a1fc`) | Post-repair (head `21dce53c1`) |
|---|---|---|
| A — UTF-16 encoded DOCTYPE with an external entity | ACCEPTED **and PARSED** (the attack was live) | **REJECTED before the parser** — `DOCTYPE and entity declarations are forbidden` |
| B — DOCTYPE beyond a 64 KiB prefix window | ACCEPTED **and PARSED** | **REJECTED before the parser** |
| C — fake `<OpenDRIVE>` token in a comment before the padding | ACCEPTED | **REJECTED before the parser** |

`parse_xodr_bytes` on all three payloads raises `UnsafeXMLError` — none
reaches the parser.

### No raw-parser bypass remains in any release-facing path

The mandatory gate sets on PR #30 are `FINAL_ARTIFACT_MANDATORY_GATES` (12)
and `PIPELINE_SUPPLIED_MANDATORY_GATES` (3). Every gate module that parses
XML now routes through the admission boundary:

| Mandatory gate module | raw parser | admission |
|---|---|---|
| `check_origin_sanity` | 0 | yes |
| `check_geometric_continuity` | 0 | yes |
| `check_lane_section_successors` | 0 | yes |
| `check_elevation_continuity` | 0 | yes |
| `check_elevation_missing_and_cliffs` | 0 | yes |
| `check_junction_integrity` | 0 | yes |
| `check_lane_geometry_continuity` | 0 | yes |
| `check_lane_link_targets_exist` | 0 | yes |
| `check_lane_width_continuity` | 0 | yes |
| `check_post_tiling_integrity` | 0 | yes |
| `check_carla_import_s`, `check_carla_opendrive_compat`, `check_elevation_smoothness`, `check_physics_feasibility` | no XML parse | n/a |

**0 mandatory-gate modules with a raw-parser bypass.** (214 non-mandatory
modules elsewhere in the tree still use a raw parser; none is on the
release-facing path.)

### Size is checked before bytes are allocated

`MAX_XODR_BYTES = 512 MiB` is enforced on `len(data)` **and** on
`st_size`, and the file reader performs a **bounded** read
(`stream.read(MAX_XODR_BYTES + 1)`) so it never allocates beyond the limit
before the check. Complexity limits are also present: `MAX_XML_DEPTH = 256`,
`MAX_XML_ELEMENTS = 5,000,000`, `MAX_XML_ATTRIBUTES_PER_ELEMENT = 512`,
and an explicit `_SUPPORTED_ENCODINGS` allowlist.

### The real pinned maps still pass

| Map | Size | `check_xml_boundary` | `parse_xodr_file` |
|---|---|---|---|
| map-of-record `370abbbb…` | 142.9 MiB | ACCEPTED (5.4 s) | PARSED, 32,267 roads (11.2 s) |
| manual `Grid0828.xodr` | 63.4 MiB | ACCEPTED (2.0 s) | PARSED, 993 roads (5.0 s) |

### One correction to my own earlier evidence

My V104 reproduction classified `<!DOCTYPE OpenDRIVE><OpenDRIVE/>` as a
**control that must be accepted**. That classification was wrong: OpenDRIVE
has no DTD, and a real DOCTYPE declaration is not a legitimate OpenDRIVE
document. Verified over the whole repository: the pinned map-of-record
(149,799,632 B) and the manual map (66,530,869 B) contain **no**
`<!DOCTYPE` anywhere, **no** `<!ENTITY` anywhere, and **none of the 49
tracked `.xodr` files** contains a DOCTYPE in its first 64 KiB. Rejecting a
DOCTYPE is therefore correct and breaks no real input.

**Disposition: `V96-XMLBOUND-001` moves from `REPRODUCED` to `VERIFIED`.**
This removes one of the two P0 release-path blockers.

---

## 4b. V108 Phase 4 — PR #32's release-gate logic verified

PR #32 (`fix/v94-ci-needs-20261112` @ `6b2c348b5`, base production) adds
`if: ${{ always() }}` to the `offline-release-gate` job and a
`tools/ci_needs_gate.py` validator that is run as the first step after
checkout.

**Verified by execution on the PR head: 8 tests passed** (the 8th test
reads the repository's own `tests.yml`, so it can only pass on the PR
branch; on the base it fails for exactly that reason).

The validator:

* binds the run to an exact 40-character SHA and requires the checked-out
  `HEAD` to equal the workflow SHA;
* requires the `needs` set to be **exactly** the seven required predecessor
  job ids — missing **and** extra are both rejected;
* requires every predecessor's `result` to be the literal `success`;
  skipped, cancelled, failed, absent and unknown values all fail closed;
* emits a receipt labelled `PASS_OFFLINE_PREDECESSORS_ONLY` with
  `runtime_certification: NOT_RUN`, so it cannot be read as live-CARLA
  proof.

**One important distinction verified, which a naive reviewer would
conflate:** the `needs` context is keyed by **job id**
(`offline-tests`, `package-wheel-smoke`, …), while the branch-protection
`required_status_checks` contexts are keyed by the **job display name**
(`offline tests`, `package / wheel smoke`, …). PR #32 uses job ids in the
`needs` context — correct. PR #41/#47 use display names for branch
protection — also correct. Both are right in their own context.

---

## 5. CI conclusions and release impact

The CI probe (`reports/v103/o5/collect_test_execution.py`) now reports
honestly and exits non-zero when a probe fails:

```
PROBE COMPLETED WITH 1 FAILED PROBE(S) - the missing
sections above are NOT evidence.
```

Observed on the production branch: recent `offline research gates` runs
report **`failure`** on several pushes. **CI is red on the production
lineage.** This is recorded, not worked around; no CI result is claimed
as a pass.

The four V107 patches were integrated into the owner branches and pushed;
their GitHub CI has not been observed green in this iteration, so **no
CI-based release claim is made for any of them.**

---

## 6. Branch policy and administrative enforcement

| Item | Status |
|---|---|
| Production branch protection | **ABSENT** — `GET /branches/{b}/protection` → 404 "Branch not protected" |
| Repository rulesets | **ZERO** — `GET /rulesets` → `[]` |
| Owner-executable plan | `reports/v103/o5/BRANCH_POLICY_CHECKLIST.md` (PR #41), corrected by #47 |
| Required context names | **CORRECTED** — 8 exact job display names, now regression-tested |
| Destructive refusal test | **SAFE** — the dangling "push to production" instruction is removed |

Applying protection is **repository administration** and is the owner's
action. OpenCode proposes; it does not administer.

---

## 7. Test counts and complete failure details

| Run | Result |
|---|---|
| O1 targeted suites (`test_v103_o1_osm_direction`, `test_v104_pr39_review_fixes`, `test_v104_safe_xml_boundary`, `test_stage07_structural_osm_metadata`, `test_v104_p2_coverage_honesty`, `test_v104_p2_coverage_behaviour`) | **89 passed** |
| O3 suites (road graph, link topology, orphan repair, #45, #46, #108) | **64 passed** |
| GUI adversarial suite | 15 collected — **9 passed, 6 failed** (the live Codex-owned defects, not suppressed) |
| Full offline suite, **base** `225ed15d` | 61 failed, 8196 passed, 22 skipped, 28 errors |
| Full offline suite, **O1 head** `a0a97394` | 61 failed, **8287 passed**, 22 skipped, 28 errors |

The full-suite comparison was proven per-node, not per-count: the union of
both trees' pytest `lastfailed` caches was re-run in both trees. **0
regressions** (pass in base → fail in O1). The only two differences are
explained: a test **renamed** by this branch, and the new P2 test file that
does not exist in base. The 61 failures and 28 collection errors are
identical and pre-existing (torch / PyQt6 / research-module imports).

---

## 8. Integrated candidate — NOT built, and why

V108 Phase 6 asks for an immutable integrated candidate built from the
production lineage. **It is deliberately not built in this iteration**, for
three evidence-backed reasons:

1. **Two P0 release-path defects were open and unowned by OpenCode.**
   `V96-XMLBOUND-001` (whole-document, encoding-aware XML admission) has no
   corrected implementation — the file is Chat 1/Codex-owned — and the six
   GUI false-success defects are now reproduced and visible but the GUI
   source is Codex-owned. A candidate that merges OpenCode's branches onto
   production while both of those remain open would be a candidate whose
   release path is known-unsound.

   **Update (this iteration):** the XML admission defect is now **repaired
   and independently verified** on PR #30 head `21dce53c1` (§4a), so only
   the GUI verdict authority remains as an open P0 release-path blocker.
   The candidate is still deliberately not built, for the reasons in (2)
   and (3).
2. **The GUI lineage is divergent.** PR #43's base is
   `integration/carla-gui-integration-20261015`, not the production
   lineage. Merging it blindly is explicitly prohibited by the brief.
3. **CI is red on the production lineage** (see §5). A candidate cannot be
   validated when the required gate is failing.

The correct next step is therefore to close the two P0 release-path items
with their owners, then build the candidate. Building it now would
produce an artifact with a known-unsound release path, which is precisely
what the brief forbids.

---

## 9. Explicit GO / NO_GO

# **NO_GO**

Required conditions and their status:

| Condition | Status |
|---|---|
| One immutable integrated candidate, independently validated | **NOT MET** — no candidate built (§8) |
| Enforced branch policy | **NOT MET** — no protection, zero rulesets; owner action |
| No unverified P0 release-path defects | **PARTIALLY MET** — the XML admission P0 is now **VERIFIED** (§4a); the six GUI false-success defects remain open on a Codex-owned file |
| All required CI workflows green on the candidate | **NOT MET** — production CI is red |
| Terminal/acceptance receipt authority verified | **NOT MET** — Codex-owned, unverified here |

An OpenCode-owned, independently verified slice **does** stand on its own:
the O1 coverage-honesty fix, the O3 seven-finding repair, the V107 #45/#46/#47
patches, the V108-O3-DIRECTION-AUTHORITY fix, and the P2 headline
self-check — 158 targeted tests green with no regressions in the full
offline suite.

**The remaining P0s are blocked on their single writers, not on OpenCode's
capacity.** They are enumerated in
`reports/continuous_closure/v105/ISSUE_REGISTRY.json` (16 issues).

---

## 10. Residual risks

1. **The production branch has no protection and no rulesets.** Every
   merge is unguarded, including one that would break the release gate.
2. ~~**The XML admission defect has no corrected implementation.**~~ —
   **RESOLVED this iteration**: repaired on PR #30 head `21dce53c1` and
   independently verified (§4a). The remaining release-path blocker is
   the GUI verdict authority.
3. **Six GUI false-success defects are live.** They are now visible to CI
   for the first time, which is progress, but they are not fixed.
4. **CI is red on the production lineage** and the cause has not been
   reproduced in this iteration.
5. **The GUI lineage's 25 collection errors are pre-existing** but mask the
   GUI lineage's own signal.
6. **O2 — the legal-movement graph — is not started.** `only_*` / `no_*`
   turn restrictions, via-node / via-way relations, conditional access and
   vehicle exceptions are not modelled at all. This is the largest
   remaining scientific-correctness gap in OpenCode's scope.
7. **Two O3 Phase-2 classes are open**: OSM shared nodes unrelated to the
   XODR endpoints being repaired, and duplicate / contradictory /
   nonreciprocal road-lane links.
8. **The `V103-O1-001` OSM-correspondence issue is `INTEGRATED_UNVERIFIED`** —
   no independent reviewer has signed the O1 head.
9. **The coverage shortfall is real and material**: OSM directional
   enrichment reaches **0.23% of the governed map's roads** (41 of 32,267
   authoritative). Any thesis or RQ claim leaning on OSM directional
   enrichment as a significant input should be re-examined.

---

## 11. Single next highest-priority work unit

**V108-O3-DIRECTION-AUTHORITY is closed. The next unit is the O2 legal-movement
graph** — because it is the largest remaining gap inside OpenCode's own
file ownership, it blocks the O3 topology conclusions from being complete,
and it does not require any Codex-owned file.

Concretely: `only_*` / `no_*` turn restrictions, via-node and via-way
restriction relations, conditional access windows and vehicle-specific
exceptions, with `unknown` modelled as a **first-class not-assessable
status** that can never be silently permitted as authoritative. Each
accepted movement must carry a traceable source-authority receipt.

In parallel, and **not** by OpenCode: the XML admission repair (Chat 1 /
Codex, PR #30) and the six GUI release-authority defects (GUI source owner).

---

## 12. Reproduction commands

```powershell
# Phase 1 -- each patch, fail-before and pass-after
cd F:\v103\gui ; git checkout bf9ba23f
py -m pytest tests/unit/ --collect-only -q            # 0 of the GUI suite collected
git checkout 19a4c2e1
py -m pytest tests/unit/test_v104_gui_authority_adversarial.py -q   # 15 collected, 9 pass, 6 live defects

cd F:\v103\o3 ; git checkout 5d35015c -- ultimate_pipeline/topology/orphan_road_repair.py
py -m pytest tests/unit/test_v107_o3_geometry_endpoints.py -q        # 4 failed
git checkout HEAD -- ultimate_pipeline/topology/orphan_road_repair.py
py -m pytest tests/unit/test_v107_o3_geometry_endpoints.py -q        # 4 passed

cd F:\v103\o5 ; git checkout 9b0d508c -- reports/v103/o5/BRANCH_POLICY_CHECKLIST.md
py -m pytest tests/unit/test_v107_branch_policy_context_names.py -q  # 1 failed
git checkout HEAD -- reports/v103/o5/BRANCH_POLICY_CHECKLIST.md
py -m pytest tests/unit/test_v107_branch_policy_context_names.py -q  # 1 passed

# Phase 2 -- the direction-authority fix
cd F:\v103\o3
py -m pytest tests/unit/test_v108_o3_direction_authority.py -q      # 11 passed
py "C:\Users\admin\AppData\Local\Temp\opencode\_v108_adj_measure.py" "...\_adj_after.json"
py reports/v103/o3/run_orphan_reconciliation.py                     # PASS, unchanged

# Thread state
py "C:\Users\admin\AppData\Local\Temp\opencode\_v108_threads.py" inspect
```

---

## 13. Evidence index

| Item | SHA |
|---|---|
| Production base (unchanged) | `225ed15d0da6444cc257835ca777aba281553f3c` |
| PR #39 head (OpenCode) | `a0a97394c61bf154157e96dc13834b5fdfcdd590` |
| PR #40 head (OpenCode) | `5a360c600af940c78d82ca6e4a14e9f69c67ce07` |
| PR #41 head (OpenCode) | `2f64b3eb5b5ce5c6d2f67b97e2850d7fbe1d43b9` |
| PR #43 head (OpenCode, GUI) | `19a4c2e13430628ca7ea75923a65311e81b86a8f` |
| PR #30 head (Codex, XML/acceptance) | `21dce53c1` |
| PR #37 head (Codex, locking) | `e44e230e9` |
| Pinned map-of-record | `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8` |
| Pinned OSM | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` |
| Issue registry | `reports/continuous_closure/v105/ISSUE_REGISTRY.json` (16 issues) |
| P2 self-check | `reports/v104/V104_P2_HEADLINE_SELF_CHECK.md` |
| P5 backlog recommendation | `reports/v104/V104_P5_BACKLOG_PR_RECOMMENDATION.md` |
