# Multi-Agent Engineering Harness

Use the smallest amount of agent work that can safely answer the task. The
main agent owns scope, integration decisions, and the final result. Spawn
subagents only for independent work, and ask them to return concise findings
with file references and commands run.

## Routing

| Task level | Typical work | Agent policy |
| --- | --- | --- |
| L0 | One-file mechanical change or direct question | Main agent only. |
| L1 | Locate code, classify a failure, inspect logs | One `scout` or `test_triage` agent. |
| L2 | Bounded implementation with known ownership | One `implementer`; optionally one read-only `reviewer`. |
| L3 | Cross-module change, research evidence, map-quality gate | One `scout`, coordinator synthesis, then one `implementer`; add one `reviewer` only after a proposed diff exists. |
| L4 | Map-of-record, release gate, provenance, or runtime-risk work | One `evidence_auditor`, coordinator baseline/capacity check, one isolated writer, then one independent reviewer. |

## Coordination Rules

- Do not run concurrent writers against the same branch, worktree, or files.
- Use read-only subagents for exploration, test triage, evidence collection,
  and reviews. The main agent assigns a single implementation owner after it
  has reconciled their findings.
- A subagent may not merge, reset, delete, start CARLA, alter map-of-record
  pins, or rewrite frozen evidence.
- For L3/L4 tasks, preserve the baseline SHA, worktree, command output,
  focused-test result, and artifact hashes in the implementation report.
- Treat unavailable full-map inputs or a sparse-checkout test limitation as
  `INCOMPLETE`, never as a pass.
- Close every completed, errored, or superseded subagent immediately; completed
  threads consume the session concurrency budget.
- Do not full-history fork by default. Give agents a compact task slice: base
  SHA, owned files, one question, command budget, and expected artifact.
- Agent reports must contain at most 10 findings and use this shape:
  classification; proof (`file:line`); affected claim; recommended owner;
  focused test. Do not paste whole JSON reports into agent context.
- If a required module, artifact, or viable worktree is absent, stop with
  `BLOCKED_BASELINE`; do not search unrelated sibling worktrees or invent a
  replacement baseline.
- Before `git worktree add`, check free space and whether large tracked assets
  make a full checkout viable. Prefer sparse worktrees for code-only tasks and
  record their input limitation as `INCOMPLETE`.
- Remove a failed scratch worktree with `git worktree remove --force` and
  `git worktree prune` once its target is verified. Never remove a user or
  active-agent worktree.
- Run changed-file tests first, then impacted-package tests. Only the
  coordinator runs the full suite once per integrated batch. A known full-suite
  hang must use one bounded wrapper/log and be tracked, not repeatedly rerun.

## Model and Effort Budget

- `scout` and `test_triage`: Luna / low or medium for fast, repeatable,
  read-heavy work.
- `evidence_auditor` and `reviewer`: Terra / high for provenance, regression,
  and design-risk assessment.
- `implementer`: Terra / high for bounded edits; xhigh only for L4 work after
  the main agent has a concrete implementation plan.

For a complex task, ask agents to divide work by ownership boundary, not by
arbitrary file count. Parallel read-only agents require disjoint questions and
an explicit reason; otherwise use the sequential L3/L4 flow above.
