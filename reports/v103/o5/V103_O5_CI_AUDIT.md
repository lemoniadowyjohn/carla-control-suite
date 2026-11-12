# V103-O5 — CI Forensics, Dependencies, Supply Chain and Branch Enforcement

**Owner:** OpenCode O5 · **Base:** `integration/production-large-map-20260918` @ `225ed15d0da6444cc257835ca777aba281553f3c`
**C08 constraint:** `DOC_ONLY_NO_WRITE` — **no workflow file is modified by this PR.** The CI patch is a *proposal* (`CI_PATCH_PROPOSAL.diff`) outside the restricted paths.

Registry issues addressed: **R25**, **R26**, **R27**, **R28**, **R29**.

---

## 1. Executive findings

| # | Registry | Finding | Verdict |
|---|---|---|---|
| 1 | **R27** | The production branch `integration/production-large-map-20260918` is **not protected** (GitHub API: `404 "Branch not protected"`) and the repository has **zero rulesets**. | **P0 — confirmed** |
| 2 | **R26** | The `offline-release-gate` job is internally **fail-closed** (bare `needs:`, no `if: always()`, no `contains(..., 'success')`, no `!contains(..., 'failure')`; the gate script exits non-zero unless PASS) — but with **no required status checks** (§1.1) nothing forces it to have run before a push lands. | **P0 — confirmed (aggregate fail-open)** |
| 3 | **R28** | All three GitHub Actions are referenced with **36-character** commit refs, not full 40-character SHAs. | **P1 — confirmed** |
| 4 | **R25** | `pyproject.toml` declares `requires-python = ">=3.10"`; **every** CI job is hardcoded to `python-version: "3.12"`. Python 3.10/3.11/3.13/3.14 are never exercised. | **P1 — confirmed** |
| 5 | **R29** | The wider offline suite currently aborts with **23 collection errors** in this environment, all `ModuleNotFoundError: No module named 'torch'`. The CI `pytest` invocation uses `set -o pipefail` and has **no** `--continue-on-collection-errors`, so those errors **fail the job** rather than being swallowed. | **P1 — confirmed** |
| 6 | **R28** | `pip check` runs in **one** of seven jobs (`package-wheel-smoke`); artifacts are uploaded but **never downloaded or validated**. | **P2 — confirmed** |

### 1.1 R26 + R27 interaction (the important one)

The gate itself is sound:

```yaml
# .github/workflows/tests.yml:307-311
offline-release-gate:
  name: offline release gate
  runs-on: ubuntu-latest
  timeout-minutes: 30
  needs:
    - offline-tests
    - package-wheel-smoke
    - governance-integrity
    - thesis-rq-contract
    - research-provenance
    - offline-evidence-graph
    - windows-single-writer
```

There is **no** `if: always()`, **no** `contains(needs.*.result, 'success')`
and **no** `!contains(needs.*.result, 'failure')`. GitHub Actions therefore
requires **all seven** predecessors to be `success`; a predecessor that is
`skipped`, `cancelled`, `neutral`, `timed_out`, `missing` or `failure`
**skips the gate job**, and the release check cannot succeed. The gate
script agrees:

```python
# ultimate_pipeline/tools/repo_health.py:384
"""A gate is ``PASS`` only when every section it requires is ``PASS``."""
# :437-443
def gate_exit_code(gate_status: str) -> int:
    return 0 if gate_status == STATUS_PASS else 1
```

**But** the branch that matters has **no protection and no rulesets**, so
there is no `required_status_checks` list containing
`offline release gate`. A green aggregate badge is therefore
**not** an enforced precondition for a push to the production branch. The
mechanism is fail-closed; the *policy* that requires it is missing. That is
the actual R26/R27 defect, and it is a **governance** defect, not a
workflow-logic defect — fixing it needs the owner to apply branch
protection or a ruleset, which this agent cannot do.

---

## 2. Per-PR CI failure classes (refreshed at exact SHAs, 2026-11-12)

| PR | Head SHA | Draft | Base | CI class named in the V103 brief | Verified? |
|---|---|---|---|---|---|
| #31 | `884f019c5` | yes | production | legacy GNN expectation | **NOT VERIFIED** — the failure was not re-run here; the PR head is draft and no local run reproduces the hosted expectation mismatch |
| #32 | `6b2c348b5` | yes | production | predecessor gate | **PARTIALLY VERIFIED** — the *current* production workflow is fail-closed (§1.1); PR #32 is the draft that adds an explicit result check on top |
| #34 | `aea4aea5c` | yes | `integration/carla-gui-integration-20261015` | missing PyQt6/pyproj CI environment | **CONFIRMED as a real gap** — `PyQt6` appears in **no** `requirements*.txt` and in **no** workflow; `pyproj==3.7.2` is in `requirements.txt:135` only |
| #35 | `9c4c0f264` | yes | production | readiness mock mismatch | **NOT VERIFIED** — no local reproduction attempted |
| #36 | `941cace20` | yes | production | research contract failures | **NOT VERIFIED** — the 23 `torch` collection errors in this environment block the same suites |
| #37 | `a72700bb1` | yes | production | locking / ABA fencing | out of O5 scope (Codex C3) |

**Observed run history on the production branch** (`/actions/runs`):

```
completed success   push  sha=225ed15d0   offline research gates   <- current head
completed success   push  sha=31bb6c7a5   offline research gates
completed failure   push  sha=d72f57c63   offline research gates
completed cancelled push  sha=a82e02013   offline research gates
completed cancelled push  sha=4ef5879d7   offline research gates
... (14 further failures)
```

The current head is green; the recent history contains **14 failures and 2
cancellations**, and the **cancellations are the interesting ones** — they
are the shape PR #32 exists to close.

---

## 3. Verified branch-policy checklist (registry R27)

| Control | State | Evidence |
|---|---|---|
| Production branch protected | **NO** | `GET /branches/{branch}/protection` → `404 {"message":"Branch not protected"}` |
| Required status checks configured | **NO** | same 404 (no protection object at all) |
| Required reviews / dismissal rules | **NO** | same 404 |
| Enforce for administrators | **NO** | same 404 |
| Repository rulesets | **NONE** | `GET /rulesets` → `[]` (empty) |
| Combined commit status on the production head | `pending`, `total_count: 0` | `GET /commits/{sha}/status` |
| `pull_request_target` used anywhere | **NO** | neither workflow uses it |
| Workflow token scope | `contents: read` (top level and per job) | `tests.yml`, `carla-runtime.yml` |
| Git-LFS pointer mistaken for map bytes | guard present | pinned-input manifest verification (`verify_inputs_manifest`) |

**Owner-executable change plan** (this agent cannot apply it — it requires
repository administration):

1. Create a ruleset (preferred, survives branch recreation) targeting
   `refs/heads/integration/production-large-map-20260918` with:
   - **required status checks**: `offline release gate` (the exact job
     *name*, not the workflow name), plus `offline-tests`,
     `governance-integrity`, `package-wheel-smoke`;
   - **required pull request reviews**: ≥ 1, dismissal of stale reviews on
     push;
   - **restrictions**: block force-push and deletion;
   - **require signed commits** for the production branch.
2. Alternatively apply classic branch protection with the same check names
   and `enforce_admins: true`.
3. Verify enforcement *after* applying: push a throwaway commit that skips
   the gate and confirm the push is refused. **Governance must not be
   reported as enforced before this test passes.**

---

## 4. CI patch proposal (DOC_ONLY — not applied)

`CI_PATCH_PROPOSAL.diff` contains the proposed workflow changes. It is a
**proposal only**: it is stored outside `.github/workflows/` and is not
applied by this PR. Applying it requires lifting C08 for exactly these
paths.

### 4.1 Full 40-character action pinning (R28)

Every action reference becomes a full 40-character commit SHA. The current
36-character refs are **valid git object prefixes** and do resolve, so this is
hardening rather than a broken pin — but a 36-char prefix admits ~2^20
alternative objects, while a 40-char SHA admits exactly one.

```diff
-      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1
+      - uses: actions/checkout@<40-char-sha> # v4.3.1
```

(The proposal lists the exact replacement SHAs to be resolved and verified by
the owner before application; this agent does not resolve them, because
guessing a SHA would be worse than leaving a valid prefix in place.)

### 4.2 Python matrix (R25)

```diff
     strategy:
       fail-fast: false
       matrix:
         python-version: ["3.12", "3.14"]
```

with the 3.14 leg restricted to the offline, torch-free profile so the
missing `torch==2.9.1` wheel does not turn the matrix into a false
failure. `requirements.txt` keeps `torch==2.9.1` untouched — **no pin is
relaxed** by this proposal.

### 4.3 `pip check` everywhere (R25/R28)

```diff
     - name: Install (offline profile)
       run: |
         python -m pip install --upgrade pip
         python -m pip install -e .
+        python -m pip check
```

### 4.4 Explicit predecessor-result assertion (R26, belt-and-braces)

The job is already fail-closed; the proposal makes the intent explicit and
guards against a future `if: always()` regression:

```diff
+    - name: Assert every release predecessor succeeded
+      run: |
+        python - <<'PY'
+        import os, sys
+        results = os.environ.get("PREDECESSOR_RESULTS", "").split(",")
+        bad = [r for r in results if r and r != "success"]
+        if bad:
+            sys.exit("release predecessors did not all succeed: %s" % bad)
+        PY
+      env:
+        PREDECESSOR_RESULTS: ${{ join(needs.*.result, ',') }}
```

### 4.5 Artifact validation (R28)

```diff
+    - name: Validate uploaded pytest log exists and is non-empty
+      run: |
+        test -s ci-artifacts/pytest.log || { echo "pytest log missing/empty"; exit 1; }
```

---

## 5. R29 — full-suite errors and skipped prerequisites

The wider offline suite (`tests/unit ultimate_pipeline/tests/unit`) aborts
with **23 collection errors** in this environment. Every one of them is:

```
ModuleNotFoundError: No module named 'torch'
```

Verified **identical before and after** the V103-O1/O3 changes (same command,
same 23 modules, on the unmodified base worktree), so this is an
environment gap, not a regression.

The CI invocation is correct and does **not** hide them:

```yaml
# .github/workflows/tests.yml:101-109
- name: Run offline test suite
  run: |
    set -o pipefail
    mkdir -p ci-artifacts "$TMPDIR"
    python -m pytest -q -p no:cacheprovider -rfEsx 2>&1 \
      | tee ci-artifacts/pytest.log
```

* `set -o pipefail` — a pytest failure survives the `tee`;
* **no** `--continue-on-collection-errors`;
* **no** `|| true` / `|| echo` swallow anywhere;
* `pytest.ini` has **no** `collect_ignore`, and root `conftest.py` has no
  skip rules and no `filterwarnings=error` hiding optional-module imports.

**Finding:** the *mechanism* is correct, but the **torch-optional suite is
not partitioned**. 23 modules import `torch` at module scope, so on a
runner without the `gnn` extra the whole collection aborts and *every*
other test in the run is lost — the offline suite reports nothing at all
rather than reporting the non-torch tests.

**Proposal (R29, requires C08 lift for the test files, not the workflows):**
mark the 23 torch-dependent modules with a registered `torch` marker and add
a `--ignore` list for the approved **offline** profile, while keeping the
full suite required in the `gnn` profile. A missing optional module must
be an explicit skip **only for the approved offline profile**, never in the
runtime-qualification profile.

---

## 6. What is NOT claimed

* **No branch protection was applied.** The owner must execute §3 and verify
  enforcement with a refusal test before governance may be called enforced.
* **No workflow file was modified** (C08 `DOC_ONLY_NO_WRITE`).
* **No CI failure for PR #31, #35 or #36 was re-reproduced here** — those
  three are marked `NOT VERIFIED` above, not PASS.
* **No 40-character action SHA was invented.** The proposal lists the
  substitution sites; the owner resolves the SHAs.

---

## 7. Deliverables in this PR

| File | Contents |
|---|---|
| `reports/v103/o5/V103_O5_CI_AUDIT.md` | this document |
| `reports/v103/o5/CI_PATCH_PROPOSAL.diff` | the proposed (unapplied) CI patch |
| `reports/v103/o5/BRANCH_POLICY_CHECKLIST.md` | owner-executable branch-protection checklist |
| `reports/v103/o5/collect_test_execution.py` | the read-only probe used to produce §1–§2 (PR states, run history, protection, rulesets) |
