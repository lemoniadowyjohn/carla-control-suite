# V105 — Final Verification

**State:** `reports/continuous_closure/v105/` · generated 2026-11-12
**Release state:** **NO_GO**

This file records what was actually executed in iteration 1 and what remains
unverified. It is not a release certificate.

---

## 1. Production state

| Item | Value | How it was measured |
|---|---|---|
| Production branch | `integration/production-large-map-20260918` | — |
| Production SHA | `225ed15d0da6444cc257835ca777aba281553f3c` | `git ls-remote origin refs/heads/…` |
| `main` lineage | **disconnected** from production | AGENTS.md; never used as a base |
| V97 archive refs | **6 / 6 published** | `git ls-remote origin "refs/archive/opencode-v97/*"` |
| Staging worktree `E:\wt-v97\staging` | **not read, not mutated** | quarantined by instruction |
| Isolation | own Git common dir `F:/v103/_gitdirs/base.git` | `git rev-parse --git-common-dir` |

## 2. Executed commands and outcomes

| Command | Exit | Passed | Failed | Errors | Notes |
|---|---|---|---|---|---|
| `py -m pytest tests/unit/test_v104_pr39_review_fixes.py -q` | 0 | 28 | 0 | 0 | one test per PR #39 review finding |
| `py -m pytest tests/unit/test_v104_safe_xml_boundary.py -q` | 0 | 8 | 0 | 0 | XML admission boundary |
| `py -m pytest <12 related suites> -q` | 0 | **146** | 0 | 0 | lane / correspondence / stage-07 / turn-cycle / acceptance |
| `py -m pytest tests/unit ultimate_pipeline/tests/unit -q` | 1 | 2 | 0 | **23** | 23 collection errors, all `No module named 'torch'`; **identical on the unmodified base `225ed15d`** |
| `py reports/v104/v104_xml_scope1_repro.py` | 0 | 0 | **3** | 0 | V96-XMLBOUND-001 reproduced on PR #30 head `4d38a1fc`; one payload was **parsed** (live) |
| `py -m pytest tests/unit/v104_gui_authority_adversarial.py -q` | 1 | 9 | **6** | 0 | 6 GUI release-authority defects; 9 properties already hold |
| `py -m pytest tests/unit/test_v103_o3_osm_road_graph.py -q` | 0 | 19 | 0 | 0 | OSM road graph / orphan repair |
| `py -m pytest <orphan + road-link + stage-03> -q` | 0 | 39 | 0 | 0 | no regressions |

**Mutation controls:** the PR #39 repair set includes a mutation control
that removes the OSM source proof and shows the repair test failing; the
orphan-repair set includes one that removes the shared-node proof and shows
the repair stopping. Neither test passes vacuously.

## 3. Issue disposition

| Issue | Priority | Status | Result | Owner |
|---|---|---|---|---|
| V104-PR39-001 (23 review findings) | P1 | TEST_PASSED | **PASS** | OpenCode |
| V103-O1-001 (OSM projected in the wrong CRS) | P0 | INTEGRATED_UNVERIFIED | **PASS** | OpenCode |
| V103-O3-001 (geometry-only orphan repair) | P0 | TEST_PASSED | **PASS** | OpenCode |
| V96-XMLBOUND-001 | P0 | REPRODUCED | **FAIL** | Chat 1 / Codex |
| V104-GUI-001 (6 GUI authority defects) | P0 | REPRODUCED | **FAIL** | Codex (PR #34) |
| V104-LOCK-001 (9 locking findings) | P1 | BLOCKED_OWNERSHIP | **NOT_RUN** | Codex (PR #37) |
| V103-O5-001 (unprotected production branch) | P0 | READY_FOR_IMPLEMENTATION | **FAIL** | repository owner |
| V104-RESEARCH-001 (torch extra missing) | P4 | BLOCKED_RESOURCES | **NOT_RUN** | CI / research owner |

**0 issues CLOSED.** An issue may not jump from DISCOVERED to CLOSED.

## 4. Why this is NO_GO

The V105 stop conditions are all conjunctive. The following are false or
unverified:

1. ✗ In-scope mandatory issues CLOSED with independently verified evidence —
   6 P0/P1 issues remain open (XML, GUI ×6, branch protection).
2. ✗ No unresolved release-blocking review finding — 19 on PR #30, 9 across
   PR #28/#37, 23 on PR #39 awaiting a second reviewer.
3. ✓ All required regression and adversarial tests pass (146/146 targeted).
4. ✗ All required CI workflows pass on the final candidate — no candidate
   SHA exists.
5. ✗ Mandatory quality gates pass on the final map SHA — no candidate.
6. ✗ Source-to-map OSM consistency established — the correspondence works on
   the manual reference map (44 matched) but the **production candidate map
   was not re-derived**.
7. ✗ CARLA runtime certification complete — never attempted (operator
   approval required).
8. ✗ GUI/operator certification complete — the GUI source has 6 open defects.
9. ✗ Supply-chain / branch governance met — the production branch is not
   protected and there are zero rulesets.
10. ✗ Release receipt valid and identity-bound — terminal authority is
    Codex-owned and unverified here.
11. ✗ Independent reviewer approves the final candidate — no candidate.
12. ✗ Authorized release owner approves promotion — not sought.

## 5. Pull requests produced this iteration

| PR | Branch | Base | Head |
|---|---|---|---|
| #39 | `fix/v103-o1-osm-direction-lane-counts` | production | `102a588c` |
| #40 | `fix/v103-o3-osm-road-graph-orphans` | production | `ee94abca` |
| #41 | `fix/v103-o5-ci-audit` | production | `6f0b02a2` |
| #42 | `fix/v103-opencode-coordination` | production | `6b0894b6` |
| #43 | `fix/v104-gui-authority-adversarial` | `integration/carla-gui-integration-20261015` | `bf9ba23f` |

No PR was self-merged. No branch was force-pushed. No historical ref was
removed.

## 6. Next selected actions

1. **Codex** — land the XML admission repair on PR #30 (encoding-aware,
   comment-aware, whole-document scan) and drive the four Scope 1 cases to
   *rejected*.
2. **Codex** — implement the six GUI corrections and drive
   `tests/unit/v104_gui_authority_adversarial.py` to 15/15.
3. **Codex C3** — resolve the nine locking findings under one owner; PR #28
   is reconciled into PR #37, not retired.
4. **Repository owner** — apply the branch-protection ruleset and pass the
   refusal test.
5. **OpenCode** — start **O2** (OSM legal-movement graph) against O1's now
   stable orientation contract; it is unblocked and does not touch
   acceptance policy.
6. **CI/research owner** — install the `gnn` extra or partition the 23
   torch-dependent modules so R30/R31 can run.
