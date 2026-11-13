# V104 — Independent Security and Authority Review: Final Report

**Reviewer:** OpenCode (independent of the implementer of PR #39's reviewed head)
**Date:** 2026-11-12
**Production base:** `integration/production-large-map-20260918` @ `225ed15d0da6444cc257835ca777aba281553f3c`
**Isolation:** dedicated clone `F:\v103\base` with its own Git common directory
(`F:\v103\_gitdirs\base.git`); separate worktrees per scope. No live worktree
was mutated. `E:\wt-v97\staging` was not read or modified.

---

## 0. Verdict

| Scope | Verdict | Blocking defects reproduced |
|---|---|---|
| 1 — XML admission | **FAIL — finding still reproduced; no repaired implementation exists** | 3 (1 live parse) |
| 2 — GUI authority | **FAIL — 6 defects reproduced; 9 properties already hold** | 6 |
| 3 — Locking | **NOT_RUN** — Codex single-writer ownership (PR #28/#37) | 0 (not attempted) |
| 4 — Evidence reconciliation | **PASS** — all 6 V97 archive refs published and verified | 0 |
| PR #39 review response | **COMPLETE** — 23/23 findings addressed with per-finding regression tests | 0 |

**No production release is certified by this review.** The XML and GUI
false-success paths are still open.

---

## 1. Scope 1 — XML admission

### 1.1 V96-XMLBOUND-001 is still reproduced on PR #30

**Historical affected SHA:** `4d38a1fc1ebdf47bb308fa80c4fc1a0d78a9b86f`
(PR #30 head, re-fetched and confirmed unchanged during this review)

**Corrected candidate SHA:** **none exists.** The repair has not been made.

**Reproducer:** `reports/v104/v104_xml_scope1_repro.py` (also executed
ad-hoc against the PR #30 worktree `F:\wt\v86-acceptance-strict`).

**Test command:**
```
py reports/v104/v104_xml_scope1_repro.py
```

**Expected vs observed:**

| Case | Expected | Observed | Verdict |
|---|---|---|---|
| A — UTF-16 encoded DOCTYPE + internal entity | rejected | **ACCEPTED**, and `parse_xodr_bytes` **PARSED it** (`root.tag == "OpenDRIVE"`) — the attack is live | **BYPASS** |
| B — DOCTYPE placed beyond the 64 KiB prefix window | rejected | **ACCEPTED** by `check_xml_boundary` (the parser later refused for an unrelated well-formedness reason, so the *boundary* is still bypassed) | **BYPASS** |
| C — fake `<OpenDRIVE` token inside a comment, then a DOCTYPE after 64 KiB of padding | rejected | **ACCEPTED** by `check_xml_boundary` | **BYPASS** |
| control — plain document | accepted | accepted | OK |
| control — literal `<!DOCTYPE` text inside a comment | accepted | **REJECTED** (over-strict false positive) | FALSE POSITIVE |

**Mutation test:** not applicable — there is no corrected implementation to
mutate.

**Result:** **FAIL.** The vulnerable code is still on the PR #30 head:

```python
# ultimate_pipeline/quality/final_artifact_gates.py:142-145  (PR #30 head)
root_at = data.find(b"<OpenDRIVE")
prolog = data if root_at < 0 else data[:root_at]
if _PROLOG_DECL.search(prolog) or _PROLOG_DECL.search(data[: 1 << 16]):
    raise UnsafeXMLError("DOCTYPE/ENTITY declarations are not permitted ...")
```

The `data[: 1 << 16]` window is the 64 KiB limit; the ASCII byte pattern
cannot match a UTF-16 declaration; and a `<OpenDRIVE` token inside a comment
moves the inferred prolog boundary.

**Independent review disposition:** **CONFIRMED by a second reviewer.** Codex
review thread `4543949125` on PR #30 (P2, *"Reject XML declarations
regardless of encoding or prefix layout"*) independently reproduces the same
UTF-16 and fake-token bypasses and states that both *"expanded the entity"*.
The thread is **unresolved**. The finding is therefore not merely mine — it is
confirmed by two independent reviewers and remains open.

**Required correction (Chat 1 / Codex-owned file):**
`ultimate_pipeline/quality/final_artifact_gates.py::check_xml_boundary` must
use an encoding-aware, whole-document scan that ignores comment and CDATA
sections — the same shape as the guard now shipped in
`reports/v103/o1/safe_xml.py` on PR #39 (see §6). That guard is
**not** a drop-in replacement for Chat 1's file (it is a report-side tool,
not the production admission path), but it demonstrates the required
semantics and is covered by 8 executable tests.

---

## 2. Scope 2 — GUI authority

**Historical affected SHA:** `3d7665fc361e17156c6552c83b98982fdfbeee4e`
(GUI lineage base; PR #34's base, re-fetched and confirmed)

**Corrected candidate SHA:** **none** — the GUI source is Codex-owned. This
review adds only independent reproducing tests, as Phase 6 permits.

**Reproducer / test file:** `tests/unit/v104_gui_authority_adversarial.py`
(independently owned; **PR #43**)

**Test command:**
```
py -m pytest tests/unit/v104_gui_authority_adversarial.py -q
-> 6 failed, 9 passed
```

**Expected vs observed — properties that already hold (9, green):**

| Property | Observed |
|---|---|
| Missing verdict | `NOT_EVALUATED`, `present=False` |
| Malformed verdict (bad JSON, empty, list, no status field, null) | `NOT_EVALUATED` |
| Forged `SUCCESS.txt`, no verdict | `NOT_EVALUATED` |
| Forged `SUCCESS.txt` + malformed verdict | `NOT_EVALUATED` |
| **Zero-exit subprocess + forged `SUCCESS.txt`** | `NOT_EVALUATED` — a subprocess exit code is never certification evidence |

**Expected vs observed — defects reproduced (6, red):**

| # | Attack | Expected | Observed |
|---|---|---|---|
| 1 | Unbound PASS — bare `{"status": "PASS"}`, no release identity | not certified | `RunVerdict(status='PASS', present=True, malformed=False)` |
| 2 | Unbound PASS + forged `SUCCESS.txt` | not certified | `status='PASS'` |
| 3 | Stale verdict (different `run_uuid`, ancient timestamp) | not certified | `status='PASS'` |
| 4 | Contradictory verdict (PASS + `blocking_failures` / `evidence_persistence_failures` / `run_status_ok=false`) | not certified | `status='PASS'` |
| 5 | PASS with missing acceptance receipt | not certified | `status='PASS'` |
| 6 | PASS whose declared `final_artifact_sha256` ≠ artifact bytes on disk | not certified | `status='PASS'` |

**Root cause:** `ultimate_pipeline/gui/jobs/governance.py::read_final_verdict`
normalises the raw `status` label and nothing else. It refuses a *missing*
or *malformed* verdict, but a present, well-formed verdict is trusted on its
label alone — there is no run-identity binding, no freshness check, no
self-consistency inspection, no receipt requirement and no artifact-digest
check. `RunStatus` already contains `STALE` and `INCONCLUSIVE` and
`AUTHORITATIVE_ONLY` already states the principle; the reader simply does
not enforce it.

**Mutation test:** not applicable — no corrected implementation exists.

**Result:** **FAIL** for defects 1–6; **PASS** for the 9 properties that
already hold. The fix is Codex-owned; the exact reproduction and the
required corrections are handed over in PR #43.

**Not covered here:** live-mode unavailability and the cancellation race need
the GUI's own fixtures; repeated run directories are partially covered by the
stale-verdict case.

---

## 3. Scope 3 — Locking

**Status: NOT_RUN** — and deliberately so.

PR #28 carries **7** unresolved review findings and PR #37 carries **2**
(the brief's "nine open PR #28/#37 review issues"):

| PR | Finding id | Location | Title |
|---|---|---|---|
| #28 | 4541439400 | `worktree_lock.py:1077` | Skip no-op… (P2) |
| #28 | 4541457823 | `worktree_lock.py:560` | Stale generations can be republished |
| #28 | 4541457844 | `worktree_lock.py:1036` | Malformed lease evidence gets deleted |
| #28 | 4541457859 | `worktree_lock.py:1120` | Retired lease recovery misses record |
| #28 | 4541457868 | `worktree_lock.py:1078` | Malformed leases stop cleanup |
| #28 | 4541457885 | `test_worktree_lock_f1_claim.py:199` | Renewal no-op goes undetected |
| #28 | 4541457903 | `test_worktree_lock_f1_claim.py:228` | Disabled cleanup passes recheck test |
| #37 | 4544467025 | `worktree_lock.py:1183` | Continu… (P2) |
| #37 | 4544467037 | `worktree_lock.py:1218` | Persist… (P2) |

**Why not run:** `ultimate_pipeline/governance/single_writer/worktree_lock.py`
is **Codex-owned single-writer** (Phase 6 / the V103 dispatch: *"Codex is the
sole writer for locks"*). Phase 6 permits read-only auditing and
*"independent reproducing tests in separately owned files"* — but the locking
contract is a single shared module and the review questions (disabled
cleanup, no-op renewal, generation rollback) require **instrumenting that
module's internals**, which risks a second writer against Codex's live PR #37
work. The dispatch also forbids *"competing with Codex for writes"*.

**What was done instead (no mutation):**
* the nine findings were **enumerated and correlated** from the GitHub API;
* the three the brief calls out are confirmed to exist as review findings:
  * *"Disabled cleanup passes recheck test"* (#28, 4541457903),
  * *"Renewal no-op goes undetected"* (#28, 4541457885),
  * *"Stale generations can be republished"* (#28, 4541457823) — the
    generation-rollback class;
* **no live worktree was mutated**, no lease was taken, no cleanup was
  triggered.

**Required action:** Codex (PR #37 owner) resolves the nine findings under a
single owner and an approved dependency order. **PR #28 must not be retired
automatically** — it is the reviewed implementation and PR #37 supersedes
it.

**Result:** **NOT_RUN** with a precise ownership reason. This is *not* a pass.

---

## 4. Scope 4 — Evidence reconciliation

**Result: PASS.** All six V97 archive refs are published on the GitHub remote
and re-verified during this review:

| Archive ref | SHA | Local branch | Match |
|---|---|---|---|
| `refs/archive/opencode-v97/v94-lifecycle-v97-20261112` | `b043d5763` | `fix/v94-lifecycle-v97-20261112` | yes |
| `refs/archive/opencode-v97/v94-terminal-authority-v97-20261112` | `974b81c91` | `fix/v94-terminal-authority-v97-20261112` | yes |
| `refs/archive/opencode-v97/v95-geometry-strict-v97-20261112` | `6d18b6c44` | `fix/v95-geometry-strict-v97-20261112` | yes |
| `refs/archive/opencode-v97/v95-gui-authority-v97-20261112` | `e40cda318` | `fix/v95-gui-authority-v97-20261112` | yes |
| `refs/archive/opencode-v97/v95-research-guarded-v97-20261112` | `bb6915771` | `fix/v95-research-guarded-v97-20261112` | yes |
| `refs/archive/opencode-v97/v97-staging-20261112` | `89b2b22b2` | `integration/v97-staging-20261112` | yes |

**Local archive evidence is kept separate from remote publication.** The
local worktrees under `E:\wt-v97\` remain **quarantined and untouched**; the
remote refs are the only recovery path relied upon, and every SHA above was
read from `git ls-remote` (remote truth), not from a local branch.

**No historical ref was removed.** The count is 6 before and 6 after.

**Recovered implementation commits** (reachable from the archive refs):

| Lane | Recovered commits |
|---|---|
| terminal-authority | `974b81c9`, `790ce5e6`, `b6e8cbf2`, `4d38a1fc` |
| geometry-strict | `6d18b6c4`, `a9541949`, `cf24666e` |
| gui-authority | `e40cda31`, `0704d565`, `3d7665fc` (+12 GUI baseline commits) |
| lifecycle | `b043d576` (+13 commits) |
| research-guarded | `bb691577` (+23 commits) |
| staging | `89b2b22b` (+61 commits, mixed-author history) |

---

## 5. Scope 5 — Per-defect disposition

### 5.1 PR #39 — 23 review findings (OpenCode-owned, now fixed)

Head before this review: `7d21e476`. Head after: `102a588c`.

| Review id | Sev | Defect | Corrected SHA | Test | Expected → Observed | Mutation | Result | Review disposition |
|---|---|---|---|---|---|---|---|---|
| 4551555409 | P1 | Odd lane totals reversed the historical side assignment | `102a588c` | `test_4551555409_odd_lane_total_keeps_the_historical_side_assignment` | `(1,2)` → `(1,2)` | covered by the resolver test | **PASS** | applied |
| 4551555419 | P2 | Unsupported resolutions counted as authoritative coverage | `102a588c` | `test_4551555419_unsupported_oneway_does_not_pass_coverage` | `authoritative=0` → `authoritative=0` | n/a | **PASS** | applied |
| 4551555425 | P2 | `junction` dropped by the structural extractor | `102a588c` | `test_4551555425_structural_extractor_keeps_junction_and_conditional` | kept → kept | n/a | **PASS** | applied |
| 4551582230 | Med | `DirectionalState.AMBIGUOUS` undefined → AttributeError | `102a588c` | `test_4551582230_ambiguous_match_returns_an_ambiguous_association` | ambiguous → ambiguous | n/a | **PASS** | applied |
| 4551582252 | High | Unknown orientation applied as aligned | `102a588c` | `test_4551582252_unknown_orientation_is_not_authoritative` (+2) | non-authoritative → non-authoritative | n/a | **PASS** | applied |
| 4551582276 | High | Conditional oneway reported as static authority | `102a588c` | `test_4551582276_conditional_oneway_conflict_is_not_authoritative` | unsupported → unsupported | n/a | **PASS** | applied |
| 4551582287 | High | Roundabouts gained counterflow lanes | `102a588c` | `test_4551582287_roundabout_default_reaches_the_resolver` | `(2,0)` → `(2,0)` | n/a | **PASS** | applied |
| 4551582303 | High | Motorways gained counterflow lanes | `102a588c` | `test_4551582303_motorway_has_an_implicit_oneway_default` | `(2,0)` → `(2,0)` | n/a | **PASS** | applied |
| 4551582316 | High | One-way fallback added counterflow | `102a588c` | `test_4551582316_oneway_without_lane_tags_keeps_one_direction` | `(1,0)` → `(1,0)` | n/a | **PASS** | applied |
| 4551582330 | High | Partial directional counts dropped lanes | `102a588c` | `test_4551582330_partial_directional_count_is_resolved_from_the_total` | `(2,1)` → `(2,1)` | n/a | **PASS** | applied |
| 4551582349 | High | Opposite matches controlled lane direction | `102a588c` | `test_4551582349_opposite_matches_do_not_yield_an_authoritative_direction` | no authoritative direction → none | n/a | **PASS** | applied |
| 4551582370 | Med | Ambiguous matches disappeared from coverage | `102a588c` | `test_4551582370_ambiguous_correspondence_reaches_the_coverage_report` | counted → counted | n/a | **PASS** | applied |
| 4551582385 | Med | Missing OSM had no blocked coverage | `102a588c` | `test_4551582385_missing_osm_source_emits_blocked_input_coverage` | BLOCKED_INPUT → BLOCKED_INPUT | n/a | **PASS** | applied |
| 4551582396 | Med | Unverified matches counted as authoritative | `102a588c` | `test_4551582396_missing_match_class_is_not_authoritative` | `authoritative=0` → `authoritative=0` | n/a | **PASS** | applied |
| 4551582407 | Med | Fallback roads passed coverage | `102a588c` | `test_4551582407_fallback_road_does_not_pass_coverage` | INCOMPLETE → INCOMPLETE | n/a | **PASS** | applied |
| 4551582421 | Med | Zero confidence trusted | `102a588c` | `test_4551582421_zero_confidence_is_not_trusted` | not trusted → not trusted | n/a | **PASS** | applied |
| 4551582442 | Med | Per-road contract never reached geometry | `102a588c` | `test_4551582442_versioned_association_reaches_the_geometry_hand_off` | schema+state+sha present → present | n/a | **PASS** | applied |
| 4551582458 | Med | Interrupted writes corrupted the contract artifact | `102a588c` | `test_4551582458_interrupted_write_leaves_no_truncated_artifact` | intact → intact | interruption simulated → raises, artifact intact | **PASS** | applied |
| 4551582473 | Med | Retries left cycle lanes on both sides | `102a588c` | `test_4551582473_retry_does_not_duplicate_the_cycle_lane` (+1) | one side → one side | n/a | **PASS** | applied |
| 4551582490 | Med | Reversed matches could be forced forward | `102a588c` | `test_4551582490_reversed_correspondence_survives_the_stage_hand_off` | `reverse` → `reverse` | n/a | **PASS** | applied |
| 4551582504 | Med | Coverage lost source identity | `102a588c` | `test_4551582504_coverage_carries_the_osm_source_identity` | sha present → present | n/a | **PASS** | applied |
| 4551601346 / 4551601397 | sec | CodeQL: `xml.etree` used on untrusted bytes | `102a588c` | `tests/unit/test_v104_safe_xml_boundary.py` (8 tests) | rejected → rejected | n/a | **PASS** | applied |

**Regression evidence at `102a588c`:**
* **146 passed** across the V94/V103 lane, correspondence, stage-07,
  turn/cycle-lane, lane-count and acceptance suites;
* the wider offline run (`tests/unit ultimate_pipeline/tests/unit`) reports
  the **identical 23 pre-existing collection errors** (`No module named
  'torch'`) as the unmodified base — no new failures;
* real-map coverage (pinned OSM, digest-verified against
  `INPUTS_MANIFEST.json`) now reports **44 matched, 35 authoritative, 246
  ambiguous, 2743 unmatched** source ways. Before the fix the ambiguous and
  unmatched populations were invisible to the coverage report.

**No threshold, gate membership or acceptance policy was weakened.**
The odd-lane-total fix *restores* the pre-existing behaviour.

### 5.2 V96-XMLBOUND-001 (Scope 1)

| Field | Value |
|---|---|
| Historical affected SHA | `4d38a1fc1ebdf47bb308fa80c4fc1a0d78a9b86f` (PR #30 head) |
| Reproducer | `reports/v104/v104_xml_scope1_repro.py` |
| Corrected candidate SHA | **none — the repair has not been made** |
| Test command | `py reports/v104/v104_xml_scope1_repro.py` |
| Expected vs observed | expected *rejected*; observed **ACCEPTED** (×3) and **PARSED** (×1, live) |
| Mutation-test result | n/a (no corrected implementation) |
| Result | **FAIL** |
| Independent review disposition | **CONFIRMED** by Codex thread `4543949125` (unresolved) |

### 5.3 GUI release authority (Scope 2)

| Field | Value |
|---|---|
| Historical affected SHA | `3d7665fc361e17156c6552c83b98982fdfbeee4e` (GUI lineage) |
| Reproducer | `tests/unit/v104_gui_authority_adversarial.py` (**PR #43**) |
| Corrected candidate SHA | **none — Codex-owned source** |
| Test command | `py -m pytest tests/unit/v104_gui_authority_adversarial.py -q` |
| Expected vs observed | 9 properties hold; **6 defects observed** (unbound PASS ×2, stale, contradictory, missing receipt, digest mismatch) |
| Mutation-test result | n/a (no corrected implementation) |
| Result | **FAIL** for the 6 defects; **PASS** for the 9 held properties |
| Independent review disposition | **NEWLY REPORTED** — 6 defects, 3 of which the PR #34 body already flags |

### 5.4 Locking (Scope 3)

| Field | Value |
|---|---|
| Historical affected SHA | PR #28 `b8a93e72…`, PR #37 `a72700bb1…` |
| Reproducer | not written (ownership) |
| Corrected candidate SHA | n/a |
| Test command | n/a |
| Expected vs observed | 9 open findings enumerated from the GitHub API |
| Mutation-test result | n/a |
| Result | **NOT_RUN** — Codex single-writer ownership of `worktree_lock.py` |
| Independent review disposition | **DEFERRED to Codex**; PR #28 must not be retired automatically |

---

## 6. Codex handoff — every required correction

### 6.1 P0 — XML admission (Chat 1 / PR #30) — **BLOCKING**

`ultimate_pipeline/quality/final_artifact_gates.py::check_xml_boundary`
must:

1. scan the **whole** document, not `data[: 1 << 16]`;
2. be **encoding-aware** — a UTF-16 declaration must be detected (an ASCII
   byte pattern cannot);
3. **ignore comment and CDATA sections** — literal `<!DOCTYPE` text inside a
   comment is not a declaration and must be allowed (the current
   implementation rejects it);
4. **fail closed** on an undecodable document;
5. keep the size cap.

A reference implementation of exactly these semantics now exists in this
repository at `reports/v103/o1/safe_xml.py` (PR #39) with 8 executable tests
(`tests/unit/test_v104_safe_xml_boundary.py`) covering ASCII DTD, UTF-16 with
and without BOM, a declaration beyond a length window, an oversized document,
literal text in comments/CDATA and a plain document. It is a *report-side*
tool, not the production admission path — Chat 1 must port the semantics
into its own file.

**Verification the owner must run:** the four V104 Scope 1 cases must be
rejected **before** `parse_xodr_bytes` is reached, and the two legitimate
controls (plain document; literal `<!DOCTYPE` text inside a comment) must
still be accepted.

### 6.2 P0 — GUI release authority (PR #34 / GUI lineage) — **BLOCKING**

`ultimate_pipeline/gui/jobs/governance.py::read_final_verdict` must:

1. require a **release identity** on a PASS verdict and compare it against
   the current run directory;
2. refuse a verdict whose declared `final_artifact_sha256` does not match
   the artifact bytes on disk;
3. treat a verdict with a non-empty `blocking_failures` or
   `evidence_persistence_failures`, or with `run_status_ok` false, as **not**
   a PASS (`RunStatus.INCONCLUSIVE` or `FAIL`);
4. require the acceptance receipt to be present for a PASS;
5. return `RunStatus.STALE` for a verdict belonging to a different run or an
   older run directory;
6. keep `SUCCESS.txt` and a subprocess exit code out of the certification
   path (already true — PR #43 locks it in).

**Verification the owner must run:** `py -m pytest
tests/unit/v104_gui_authority_adversarial.py -q` must go from
`6 failed, 9 passed` to `15 passed`.

### 6.3 P1 — Locking convergence (PR #28 + PR #37) — **CODEX-OWNED**

Resolve the nine findings under a **single** owner and an approved dependency
order. **PR #28 must not be retired automatically** — it is the reviewed
implementation; PR #37 supersedes it. The three findings the brief names
specifically are:

* *"Disabled cleanup passes recheck test"* (#28 `4541457903`) — cleanup that
  is disabled must be detected, not silently treated as a pass;
* *"Renewal no-op goes undetected"* (#28 `4541457885`) — a renewal that
  changes nothing must be observable;
* *"Stale generations can be republished"* (#28 `4541457823`) — the
  generation-rollback / ABA class.

### 6.4 P1 — PR #39 review threads

All 23 threads now have a source correction and an executable regression
test at `102a588c` (table in §5.1). The threads may be resolved once the
reviewer confirms the fix at that SHA. **No thread was resolved by this
reviewer** — only the author (or the reviewer) may resolve them.

### 6.5 Process note

`scripts/record_test_execution.py` does not exist in this repository, and
`gh` is not installed on this host. The read-only GitHub probe used for this
review is `reports/v104/collect_test_execution.py` (public API only, no
credential handling).

---

## 7. Not claimed

* **No production release is certified.** The XML and GUI false-success
  paths are open.
* **No Codex-owned module was modified.** PR #43 adds tests only.
* **The locking scope was not independently reproduced** (NOT_RUN, with the
  ownership reason in §3).
* **No review thread was resolved.**
* **The 23 `torch` collection errors remain** — pre-existing and verified
  identical on the unmodified base; they are not a pass and they still block
  the research workstream.
* **No CARLA runtime, no GUI launch, no operator authorization was used.**
