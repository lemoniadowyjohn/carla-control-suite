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

### Delegation and quota policy

- Match agent count to independent ownership boundaries, not file count. Keep L0 on the main agent; use one specialist for L1; one writer for L2; parallel read-only discovery for L3; and staged discovery, one isolated writer, then independent review for L4.
- For L3, parallelize only independent questions (such as code-path discovery, test triage, and evidence audit). Reconcile findings before assigning the single writer; avoid duplicate reads.
- For L4, use separate model families for implementation and review. Add a second reviewer only when the release/evidence gate requires dual review.
- Reserve strong-model quota for design risk, provenance, adversarial review, and complex implementation. Route searches and bounded triage to the least costly suitable model. The evidence bar is unchanged by model tier.
- On provider quota/rate-limit errors, rotate to the next configured fallback for that role; never retry the same model in a loop. A fallback must be a separately dispatchable configured agent. Exhausted attempts are `NOT_RUN`, never a pass.
- Before dispatch, state task level, role, model tier/family, ownership boundary, permissions, and expected output. Reuse an active agent only when its role and ownership still fit.

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

- Codex `scout`, `test_triage`, and `report_reader`: use `gpt-6-luna` at low
  effort for straightforward lookup/triage; raise to medium only when the task
  needs multi-file tracing or test-failure classification.
- Codex `evidence_auditor`: use `gpt-6.1-terra` at high effort for hashes,
  provenance, baseline comparisons, and governed claims. Use medium effort for
  a narrow, mechanically verifiable evidence inventory.
- Codex `reviewer`: use `gpt-6.1-terra` at high effort for regression,
  security, provenance, and release-gate reviews. Use `gpt-6-astra` at high
  effort only when the main agent identifies unresolved cross-system or
  high-consequence design risk; do not use frontier effort for routine review.
- Codex `implementer`: use `gpt-6.1-terra` at medium effort for bounded,
  pre-mapped changes; high effort for cross-module changes. Reserve
  `gpt-6-astra` at high effort for L4 work only after read-only findings and a
  concrete implementation plan exist.
- Keep Codex subagent counts to the routing table: cheap read-only agents may
  work in parallel on independent questions, but implementation remains one
  writer per branch/worktree and review is a separate model family. Do not
  spend quota duplicating the same search or running redundant agents.
- Choose the lowest effort that can satisfy the task's evidence bar, then
  escalate once if findings show the task exceeds that tier. Record model and
  effort for delegated L3/L4 work so review independence and quota use are
  auditable.
- For non-Codex harnesses, use their own model guidance below; these Codex
  model/effort assignments do not change Claude or OpenCode configuration.
- Runtime/CARLA sessions (e.g. Grid0821 load, sensor sweeps) are never
  delegated: subagents may not start CARLA. The main agent or operator runs them.

For a complex task, ask agents to divide work by ownership boundary, not by
arbitrary file count. Wait for all read-only findings before starting a write.

### OpenCode (free-model pool, `opencode.json`)

The same roles exist as OpenCode subagents, all on free models. Each role has
a primary on OpenCode Zen and **multiple fallbacks on OpenRouter** (separate
quotas). On rate-limit/provider error, re-dispatch to the next fallback in order;
do not retry the same model in a loop. Probed 2026-10-14; re-probed 2026-10-22
(chat + read-tool call) after catalog churn removed 5 wired models: the
primaries re-assigned on 2026-10-22 were live-probed before wiring, unchanged
roles keep the 2026-10-14 probe plus a fresh catalog-presence check.

OpenCode's task tool dispatches by **agent name**, not by model, so a fallback
is only usable if it exists as its own agent in `opencode.json`. The chain is
`<role>` → `<role>_alt` → `<role>_alt2`; there is no third fallback agent.
All 16 wired models were confirmed present in `opencode models` on 2026-10-22
(catalog check only; the `_alt2` agents have not been live-probed).

| Role | `<role>` (primary) | `<role>_alt` (fallback 1) | `<role>_alt2` (fallback 2) |
| --- | --- | --- | --- |
| `scout` | `opencode/nemotron-3.5-lightning-free` | `openrouter/nvidia/nemotron-3.5-lightning:free` | `openrouter/liquid/lfm-2.5-2.6b:free` |
| `test_triage` | `opencode/minimax-m3.1-flash-free` | `openrouter/cohere/north-mini-code:free` | `openrouter/minimax/minimax-m3.1-flash:free` |
| `evidence_auditor` | `opencode/nemotron-3-ultra-free` | `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free` | `openrouter/nvidia/nemotron-3-super-120b-a12b:free` |
| `reviewer` (`_alt` = L4 2nd reviewer) | `opencode/deepseek-v4.1-flash-free` | `openrouter/minimax/minimax-m3.1-flash:free` | `openrouter/nvidia/nemotron-3.5-lightning:free` |
| `report_reader` | `opencode/beam-free` | `openrouter/thinkingmachines/inkling:free` | `openrouter/nvidia/nemotron-3.5-lightning:free` |
| `implementer` (single writer) | `opencode/big-pickle` | *none* — never run two writers | *none* |
| built-in `explore` / `general` | `opencode/mimo-v2.6-flash-free` / `opencode/longcat-2.5-preview-free` | — | — |
| `small_model` (titles/summaries) | `opencode/flint-40b-free` | — | — |

**Fallback rotation rule**: when a subagent returns a quota/rate-limit or
provider error, re-dispatch the *same task* to the next agent in the row
(`<role>` → `<role>_alt` → `<role>_alt2`). Do **not** retry the same agent; do
**not** skip ahead more than one step per failure. If `_alt2` also fails, report
the review/triage as `NOT_RUN` with the three error messages — never as a pass.
An exhausted free pool is not "agents unavailable" for gate purposes until all
three were actually tried.

### Claude Code (`.claude/agents/`)

The same roles exist as Claude Code subagents with identical prompts and
rules: `scout`, `test_triage`, `report_reader` (Haiku) and `evidence_auditor`,
`reviewer`, `implementer` (Sonnet). Claude Code does not read `opencode.json` or
`.codex/`; `AGENTS.md` is the only file all three harnesses share. The
read-only roles have no Edit/Write tool, but their Bash limits (no CARLA, no git
writes) are enforced by prompt, not by a permission rule. A Claude Code reviewer
counts as independent of an OpenCode/Codex implementer (different model family).
Never run a Claude Code `implementer` while an OpenCode or Codex writer is
active on the same branch.

- The reviewer must never use the implementer's model (`big-pickle`).
- Read-only roles have `edit: deny`, `task: deny` (no nested delegation), and
  deny push/commit/reset/checkout/merge/stash/`rm` and CarlaUE4 launches.
- Reserve (working, not yet assigned): `opencode/nemotron-3.5-super-vl-free`
  (probed 2026-10-22),
  `openrouter/nvidia/nemotron-3-super-120b-a12b:free`,
  `thinkingmachines/inkling-small:free`, `dots-studio/dots-3-note-preview:free`,
  `openrouter/free` (auto-router). Unusable: `google/gemma-4-*:free` (upstream
  rate-limited), `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (failed
  the tool-call probe). Removed from the catalog after 2026-10-14 (hard
  "not available" on the 2026-10-22 probe, not rate-limits — do not reference):
  `opencode/cat-jam-free`, `opencode/space-bunny-free`,
  `opencode/step-5-preview-free`, `opencode/muse-spark-1.3-contributor-free`,
  and on OpenRouter `poolside/laguna-s-2.1:free` and
  `poolside/laguna-xs-2.1:free`.
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
