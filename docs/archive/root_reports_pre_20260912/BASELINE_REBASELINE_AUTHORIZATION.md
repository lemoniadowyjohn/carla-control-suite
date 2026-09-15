# Baseline Re-Baseline Authorization

This is a standalone, explicit human-authorization record for the baseline discrepancy found during
the MQ-A production map-quality architecture audit, written specifically so that MQ-B (or any
downstream agent, including Codex) does not have to rely on any single AI agent's own self-declared
authority to resolve it.

## The discrepancy

- **Originally stated baseline** (in both the MQ-A and MQ-B task briefs): branch
  `stabilize/research-release-20260905` @ SHA `f195ba0b5d6df3f085573c5e996ff9d0f11a975f`.
- **Verification result**: this SHA does not exist in the repository. `git cat-file -t
  f195ba0b5d6df3f085573c5e996ff9d0f11a975f` fails (object not found); `git log --all` finds no
  matching commit anywhere in the repository's history. This was independently verified twice, in
  two separate audit passes (a Stage-A runtime-admission audit and this MQ-A architecture audit),
  by two independently-derived investigations reaching the same conclusion.
- `stabilize/research-release-20260905` **is** a real branch; its actual tip is `33d5d815b1d7cec9052157cb03ef2f7c9a7204dc`.

## The authorization

**The human operator (repository owner, working directly in this Claude Code session) was presented
with this discrepancy and explicitly selected the re-baseline option**, via a direct multi-choice
question, choosing:

> "Use review/claude-independent-audit-20260906 @ 2e020d9b (Recommended) — Current HEAD, a direct
> descendant of stabilize/research-release-20260905 with 4 additional commits, and the exact SHA
> with the fully-green 6-job CI run I verified last turn. Treat this as the corrected baseline and
> proceed."

over the alternative options offered ("use stabilize/research-release-20260905 @ 33d5d815b1d7cec9052157cb03ef2f7c9a7204dc itself" or "stop here, just report the mismatch").

This is a direct, first-person human decision — not an inference, assumption, or AI-to-AI handoff.

## What is authorized

`review/claude-independent-audit-20260906` @ `2e020d9b8ed5e21ae0a2e4a93ef1e71116082eef` is the
authoritative baseline for both:
- **MQ-A** (the read-only architecture/gap audit — already complete, this branch/commit)
- **MQ-B** (the implementation phase that follows, per `PRODUCTION_MAP_TASK_GRAPH.json`, starting
  with task `T-001`)

This authorization is scoped to resolving the baseline-identity question only. It does not itself
authorize any specific code change — MQ-B implementation work is still subject to its own task-level
stop conditions, tests, and review as defined in `PRODUCTION_MAP_TASK_GRAPH.json` and
`PRODUCTION_MAP_REMEDIATION_PLAN.md`.

## Supporting evidence (independently verifiable, not just asserted)

- `reports/production_readiness/20260906T170000Z/A0_AUTHORITY.json` — the full mechanical
  verification trail (git commands, CI run lookup, expected-state cross-check).
- CI run `34044481507` on `review/claude-independent-audit-20260906` @ `2e020d9b`: 6/6 jobs green
  (package/wheel smoke, offline tests, research provenance, thesis RQ contract, governance
  integrity, repository health), `pull_request`-triggered, completed 2026-09-06T16:08:15Z —
  independently re-confirmable via `gh run view 34044481507`.
- `git merge-base stabilize/research-release-20260905 HEAD` returns `33d5d815b1d7cec9052157cb03ef2f7c9a7204dc`
  with exit code 0, confirming `2e020d9b` is a direct descendant (not a divergent/unrelated branch).

## If a downstream agent still cannot accept this

If MQ-B's own admission logic requires an authorization channel this document doesn't satisfy (e.g.
a cryptographic signature, a specific ticket/issue reference, or a GitHub-native approval), that is a
legitimate reason to still stop and ask — this document is the best available durable record of the
actual human decision, not a claim that it satisfies every possible admission policy. In that case,
the operator should be asked directly (again) rather than any agent proceeding on an assumption.
