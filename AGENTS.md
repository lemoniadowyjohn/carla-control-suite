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
| L3 | Cross-module change, research evidence, map-quality gate | Parallel `scout` + `evidence_auditor` + `reviewer`; one implementer only after synthesis. |
| L4 | Map-of-record, release gate, provenance, or runtime-risk work | Read-only discovery first, exactly one writer in an isolated worktree, then an independent reviewer. |

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

## Model and Effort Budget

- `scout` and `test_triage`: Luna / low or medium for fast, repeatable,
  read-heavy work.
- `evidence_auditor` and `reviewer`: Terra / high for provenance, regression,
  and design-risk assessment.
- `implementer`: Terra / high for bounded edits; xhigh only for L4 work after
  the main agent has a concrete implementation plan.

For a complex task, ask agents to divide work by ownership boundary, not by
arbitrary file count. Wait for all read-only findings before starting a write.
