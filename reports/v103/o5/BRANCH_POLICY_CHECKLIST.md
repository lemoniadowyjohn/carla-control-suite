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

| Context to require | Job | Workflow |
|---|---|---|
| `offline release gate` | `offline-release-gate` | `tests.yml` |
| `offline-tests` | `offline-tests` | `tests.yml` |
| `governance-integrity` | `governance-integrity` | `tests.yml` |
| `package-wheel-smoke` | `package-wheel-smoke` | `tests.yml` |

`offline release gate` already aggregates the other seven predecessors, so
requiring it plus the three named jobs gives defence in depth against a
future `if: always()` regression.

## 3. Owner-executable change plan

**Preferred — a ruleset** (survives branch re-creation):

```
Target:        refs/heads/integration/production-large-map-20260918
Enforcement:   Active
Bypass actors: (none — do NOT allow admins to bypass)
Rules:
  - Restrict creations                     -> no
  - Restrict updates                       -> no
  - Restrict deletions                      -> no
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

Also apply the same ruleset to `fix/v94-*`, `fix/v95-*` and
`integration/v97-staging-20261112` so a topic branch cannot be pushed
without CI either.

## 4. Verification (must pass before "enforced" is claimed)

1. `GET /branches/{b}/protection` → 200, or `GET /rulesets` → a non-empty
   list containing the production branch with `enforcement: active`.
2. **Refusal test** — push a throwaway commit to the production branch with
   the gate not run and confirm the push is **REFUSED** by GitHub, not
   merely that the badge is red.
3. Confirm the ruleset appears on the branch's protection summary
   (`GET /branches/{b}` → `protected: true`, and the ruleset list contains
   the branch).
4. Re-run the API probe and attach the output.

## 5. Also apply the CI patch proposal

`CI_PATCH_PROPOSAL.diff` (R25/R26/R28/R29) is stored outside
`.github/workflows/` and is **not applied**. It needs an explicit C08 lift
for exactly `.github/workflows/tests.yml` and
`.github/workflows/carla-runtime.yml`.
