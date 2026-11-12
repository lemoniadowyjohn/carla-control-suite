# V103-O5 — Branch-Policy Checklist (registry R27)

**Status: NOT ENFORCED.** Every box below is currently unchecked. This
agent cannot apply branch protection or rulesets — it requires repository
administration. Governance must not be reported as enforced until the
verification step in §4 passes.

Baseline: `integration/production-large-map-20260918` @ `225ed15d0da6444cc257835ca777aba281553f3c`
Checked: 2026-11-12 via the GitHub REST API.

## 1. Current measured state

| # | Control | Required | Measured | OK |
|---|---|---|---|---|
| 1.1 | Production branch protected | yes | `GET /branches/{b}/protection` → **404 "Branch not protected"** | ✗ |
| 1.2 | Required status checks present | yes | same 404 — no protection object exists | ✗ |
| 1.3 | Required pull-request reviews (≥1) | yes | same 404 | ✗ |
| 1.4 | Stale approvals dismissed on push | yes | same 404 | ✗ |
| 1.5 | Force-push blocked | yes | same 404 | ✗ |
| 1.6 | Branch deletion blocked | yes | same 404 | ✗ |
| 1.7 | Enforced for administrators | yes | same 404 | ✗ |
| 1.8 | Repository rulesets | ≥1 for the production branch | `GET /rulesets` → **`[]` (empty)** | ✗ |
| 1.9 | Combined commit status on the production head | non-pending | `GET /commits/{sha}/status` → `state=pending`, `total_count=0` | ✗ |
| 1.10 | `pull_request_target` not used | true | true — neither workflow uses it | ✓ |
| 1.11 | Workflow token scope is read-only | true | true — `permissions: contents: read` at top level and per job | ✓ |
| 1.12 | Release gate is internally fail-closed | true | true — bare `needs:`, no `if: always()`, `gate_exit_code` returns 0 only on PASS | ✓ |

## 2. Required check names (exact)

The required-status-check context must be the **job name**, not the workflow
name:

| Context to require (the job **display name**) | Job id | Workflow |
|---|---|---|
| `offline release gate` | `offline-release-gate` | `tests.yml` |
| `offline tests` | `offline-tests` | `tests.yml` |
| `governance integrity` | `governance-integrity` | `tests.yml` |
| `package / wheel smoke` | `package-wheel-smoke` | `tests.yml` |
| `thesis rq contract` | `thesis-rq-contract` | `tests.yml` |
| `research provenance` | `research-provenance` | `tests.yml` |
| `offline evidence graph` | `offline-evidence-graph` | `tests.yml` |
| `windows single writer` | `windows-single-writer` | `tests.yml` |

**Two corrections (2026-11-12, reviews 4551933335 / 4551961563):**

1. GitHub emits a check under the job's configured **display name**, not its
   hyphenated job id. The earlier list used the job ids
   (`offline-tests`, `governance-integrity`, `package-wheel-smoke`), and no
   workflow emits those contexts, so requiring them would have blocked
   **every** merge. The names above are the display names declared in
   `.github/workflows/tests.yml`.
2. **All seven predecessors must be required, not three.** GitHub documents
   that a required status check is satisfied by a **successful, skipped or
   neutral** conclusion. When a predecessor fails, the bare `needs:` list
   makes the release-gate job *skipped* — and a skipped required check still
   satisfies the requirement. Requiring only the gate plus three
   predecessors would therefore let a failed predecessor through (review
   4551933349).

The predecessor contexts are what actually enforce the gate; the gate
context is kept so the gate stays visible and cannot be dropped from the
workflow.

## 3. Owner-executable change plan

**Preferred — a ruleset** (survives branch re-creation):

```
Target:        refs/heads/integration/production-large-map-20260918
Enforcement:   Active
Bypass actors: (none — do NOT allow admins to bypass)
Rules:
  - Restrict creations                     -> no
  - Restrict updates                       -> no
  - Restrict deletions                      -> YES
  - Restrict force pushes                  -> YES
  - Block force pushes                     -> YES
  - Require a pull request before merging   -> yes
  - Require status checks to pass:
        required contexts: offline release gate, offline-tests,
                           governance-integrity, package-wheel-smoke
        strict: yes
  - Require review: 1 approving review, dismiss stale on push
  - Require signed commits
  - Require linear history
```

**Alternative — classic branch protection** with the same check contexts,
`required_approving_review_count: 1`, `dismiss_stale_reviews: true`,
`enforce_admins: true`, `restrictions` blocking force-push and deletion.

**Correction (2026-11-12, reviews 4551933388 / 4551961571).** The ruleset
above originally set *Restrict deletions* to `no` and did not block force
pushes, so following the plan would have left the production branch
deletable and force-pushable — and the classic alternative's `restrictions`
setting does not disable either operation on its own. Both operations must
now be blocked explicitly, as shown.

Also apply the same ruleset to `fix/v94-*`, `fix/v95-*` and
`integration/v97-staging-20261112` so a topic branch cannot be pushed
without CI either.

## 4. Verification (must pass before "enforced" is claimed)

1. `GET /branches/{b}/protection` → 200, or `GET /rulesets` → a non-empty
   list containing the production branch with `enforcement: active`.
2. **Refusal test**

   **Correction (2026-11-12, review 4551961577).** When the ruleset requires
   a pull request, this test can *pass* for the wrong reason: the
   pull-request rule refuses the push even when the release gate is not
   required at all. The verification must therefore also prove, from the API,
   that the applied ruleset **lists the gate context** (and the seven
   predecessor contexts) among its required status checks. Only a direct push
   attempt proves the pull-request rule, and only the ruleset content proves
   the gate is required.

   **Correction (2026-11-12, review 4551961622).** The refusal test must not
   be able to modify production. Run it against a **throwaway branch with
   the same ruleset applied**, never against the production branch; if the
   production ruleset is absent or misconfigured, the push would succeed and
   the test would itself rewrite production history. — push a throwaway commit to the production branch with
   the gate not run and confirm the push is **REFUSED** by GitHub, not
   merely that the badge is red.
3. Confirm the ruleset appears on the branch's protection summary, **and**
   that the ruleset's required status checks contain the gate display name and
   all seven predecessor display names. Note that the branch name contains
   "/" and must be URL-encoded as one path segment in the API path, and that
   the check-run conclusions must be read from the check-runs endpoint rather
   than the legacy commit-status endpoint (both corrections come from the
   V104 review of `collect_test_execution.py`).
   Confirm the ruleset appears on the branch's protection summary
   (`GET /branches/{b}` → `protected: true`, and the ruleset list contains
   the branch).
4. Re-run the API probe and attach the output.

## 5. Also apply the CI patch proposal

`CI_PATCH_PROPOSAL.diff` (R25/R26/R28/R29) is stored outside
`.github/workflows/` and is **not applied**. It needs an explicit C08 lift
for exactly `.github/workflows/tests.yml` and
`.github/workflows/carla-runtime.yml`.
