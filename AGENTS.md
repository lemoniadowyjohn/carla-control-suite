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

### OpenCode (free-model pool, `opencode.json`)

The same roles exist as OpenCode subagents, all on free models. Each role has
a primary on OpenCode Zen and an `_alt` on OpenRouter (separate quota). On a
rate-limit/provider error, re-dispatch the same task to the `_alt` agent; do
not retry the primary in a loop. Probed 2026-10-14 (chat + read-tool call).

| Role | Primary (`opencode/…`) | Fallback (`openrouter/…`) |
| --- | --- | --- |
| `scout` | `nemotron-3.5-lightning-free` | `nvidia/nemotron-3.5-lightning:free` |
| `test_triage` | `space-bunny-free` | `cohere/north-mini-code:free` |
| `evidence_auditor` | `nemotron-3-ultra-free` | `nvidia/nemotron-3-ultra-550b-a55b:free` |
| `reviewer` / `reviewer_alt` | `step-5-preview-free` | `poolside/laguna-s-2.1:free` (also the L4 second reviewer) |
| `report_reader` | `muse-spark-1.3-contributor-free` | `thinkingmachines/inkling:free` |
| `implementer` (single writer) | `big-pickle` | none — never run two writers |
| built-in `explore` / `general` | `mimo-v2.6-flash-free` / `longcat-2.5-preview-free` | — |
| `small_model` (titles/summaries) | `cat-jam-free` | — |

- The reviewer must never use the implementer's model (`big-pickle`).
- Read-only roles have `edit: deny`, `task: deny` (no nested delegation), and
  deny push/commit/reset/checkout/merge/stash/`rm` and CarlaUE4 launches.
- Reserve (working, not yet assigned): `openrouter/nvidia/nemotron-3-super-120b-a12b:free`,
  `thinkingmachines/inkling-small:free`, `dots-studio/dots-3-note-preview:free`,
  `openrouter/free` (auto-router). Unusable on 2026-10-14: `poolside/laguna-xs-2.1:free`
  (rate-limited), `google/gemma-4-*:free` (upstream rate-limited),
  `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (failed the tool-call probe).
- Non-free providers are currently unusable from OpenCode: `github-copilot/*`
  rejects the `GITHUB_TOKEN` PAT (needs `opencode auth login` → GitHub Copilot),
  and `openai/*` has no API credits. Free-model output carries the same evidence
  bar as any other: no PASS without executed commands.

## Project-Specific Rules

- Use `integration/production-large-map-20260918` as the authoritative working branch, NOT `main` (`main` is a disconnected 1-commit stub, confirmed not an ancestor of any real work -- see `docs/archive/BRANCH_ARCHIVAL_PLAN.md`, written in this same checkpoint, which correctly identifies this); feature branches only via PR
- No direct production push unless explicitly authorized
- Resolve map-of-record via registry; never select by mtime/glob guessing
- Frozen thesis material is immutable — no blind map promotion
- GAP-026 cannot be "fixed" by raising tolerance
- No final XODR cosmetic mutation
- Generator fixes occur at source stage only
- Current scientific status must be evidence-backed
- External runtime success requires actual RPC response; port listening alone is not CARLA success
- Historical artifacts must not be overwritten
- Single-writer/worktree policy is enforced
- Exact test/evidence reporting required; no claiming PASS from unexecuted commands
