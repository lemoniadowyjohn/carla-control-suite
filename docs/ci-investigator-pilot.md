# CARLA CI Failure Investigator — pilot deployment guide

## Scope

This is a **manual-only, advisory, read-only** GitHub Agentic Workflow source.

Source: `.github/workflows/carla-ci-investigator.md`

Generated executable workflow (pending compiler output and human review):
`.github/workflows/carla-ci-investigator.lock.yml`

Validation: `.github/workflows/carla-ci-investigator-compile-check.yml`

It does **not** replace `tests.yml`, `carla-runtime.yml`, CARLA release quality gates, existing OpenCode audits, or independent human approval.

## Reconciled branch baseline

- The authoritative research CI branch inspected before creation was `integration/post-pr16-final-20261102`, starting from `1a36b560a69286841d4c42973cf00258a38f56c1`.
- That branch contained `tests.yml` and `carla-runtime.yml`, not an existing CI investigator.
- `main` has a separate portfolio-quality workflow. This pilot targets the research integration branch deliberately.

## Read-only policy

- Explicit `contents: read` and `actions: read` permissions.
- Manual `workflow_dispatch` only; no `push`, `schedule`, `workflow_run` or `pull_request_target` trigger in the agent workflow.
- GitHub read tools limited to the named repository and approved integrity; no edit, shell, runtime testing or independent network tools enabled.
- Disables automatic issue creation and automatic failure-issue reporting. The only terminal safe output is `noop`.
- No custom secrets are created or modified by this PR.
- No merging or branch mutation permitted.

## Build and verification

The validation workflow installs a pinned GitHub Agentic Workflows CLI extension, compiles the Markdown with strict and validation flags, and uploads the generated `.lock.yml` as an artifact to facilitate exact review.

After the **validator succeeds**, compare the generated compiled workflow to the security policy; confirm no effective write permissions, unexpected safe-output jobs, side-effect jobs, or automatic triggers. Commit the verified compiled artifact on the isolated branch and re-run CI. Do not substitute a hand-written `.lock.yml`.

The GitHub Actions source compiler can check syntax; a successful compile **does not** prove live AI engine authentication, successful diagnostic execution or effective no-write behavior. These need separate acceptance tests.

## Copilot engine prerequisite

The source specifies `engine: copilot`. The workflow does not grant `copilot-requests: write`, avoiding that additional permission in the pilot. It therefore requires a separately configured eligible **personal Copilot authentication path** (typically `COPILOT_GITHUB_TOKEN`) before activation. Verify account access without printing secrets. If not available, select another supported engine and recompile on the feature branch before merging.

## How to activate later (not performed by this PR)

1. Review and merge an approved implementation that includes both the Markdown source and compiler-generated `.lock.yml`.
2. GitHub may require the executable workflow file to exist on the default branch before a manual dispatch can be registered, even when running against an integration branch. Use a reviewed inert bootstrap or a separate trial repo if necessary. Do not silently alter default-branch governance.
3. With credentials and registration verified, manually invoke the compiled workflow against a **known historical failing run ID** and inspect the evidence in its GitHub Actions summary.
4. Verify `NO_FAILURE_FOUND` for a successful run, `INCOMPLETE` for inaccessible/missing evidence, and no issues/comments/PRs created in all cases.
5. Keep automatic triggers disabled until an independent security review accepts a future change.

## Acceptance checklist

- [ ] Strict gh-aw compile completed successfully
- [ ] Compiled artifact reviewed and committed
- [ ] Read-only and no-auto-output contract checked against compiled job graph
- [ ] Workflow authentication verified without exposing credentials
- [ ] Exact run ID and candidate SHA provenance preserved
- [ ] No other CI workflow or release gate weakened
- [ ] Manual end-to-end diagnosis independently observed
- [ ] No unauthorized writes or duplicate notices
- [ ] Independent review approved deployment

Unmet checks are `NOT_VERIFIED`, not `PASS`.
