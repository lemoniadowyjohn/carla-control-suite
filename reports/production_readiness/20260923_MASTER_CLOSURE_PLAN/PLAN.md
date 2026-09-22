# Master closure plan — 2026-09-23

Production tip as of writing: `cc82a2ea` on `origin/integration/production-large-map-20260918`.
Gap register: `reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.json`
(18 tracked: 10 fixed, 1 in_progress, 1 deferred, 4 open/blocked-on-prerequisite, 1 blocked_external, 1 in active investigation).

## Dependency chain (this is the actual critical path, not a flat list)

```
GAP-011 (OC-51/58/59 + RQ3 contract + Semantic Organizer restoration)
   |
   +--> GAP-010 (RQ4 leakage fix) --> RQ4 retraining --> RQ4 answered
   |
   +--> RQ3 capture-protocol code ready --> GAP-017 (live CARLA RPC) --> RQ3 answered
                                                              |
                                                              +--> RQ5(a) (needs RQ3 data + a trained
                                                                    segmentation checkpoint that doesn't exist)

RQ2 (domain gap) -- INDEPENDENT of the above, offline-doable now, last computed 2026-08-21/26,
   before this session's GeoAligner/CurvatureGap bug fixes (2026-09-14/16) -- genuinely stale,
   never re-verified. No blocker except doing the work.

RQ1 (determinism) -- INDEPENDENT, believed still valid, never re-smoke-tested against the huge
   volume of merges since 2026-09-18. Cheap to re-confirm, expensive to leave silently unverified.

GAP-008 (geometry consolidation) -- INDEPENDENT architectural decision, no RQ depends on it directly,
   but GAP-004/006's fixes both cited it as an open question.

GAP-013/GAP-014 (duplicate-module / test-pollution) -- INDEPENDENT, code-quality/CI-integrity only,
   no RQ depends on it.

Disk space (C:) -- RESOLVED 2026-09-23 (98%->85% used). F: still critical (741MB free), a separate
   structural issue (too many live worktrees), not yet addressed.
```

## RQ-by-RQ status and closure path

- **RQ1 (determinism)**: Last verified valid pre-2026-09-18. Never re-smoke-tested against ~15 merges
  since. Action: offline re-verification (Claude subagent, dispatched today).
- **RQ2 (domain gap / hull footprint)**: Authoritative number (~2.7-3.8x) computed 2026-08-21/26,
  BEFORE the GeoAligner schema-order fix, alignment-extractor point-duplication fix, stale-header-bbox
  fix, and CurvatureGap KL density-vs-mass fix (all 2026-09-14/16) -- all in the exact code path this
  number depends on. `THESIS_TO_CURRENT_PROGRESS.md` explicitly declined to re-verify, calling it "a
  human call, not an automatic swap." That call has never been made. Action: offline re-computation
  against the current map-of-record with current code (Claude subagent, dispatched today).
- **RQ3 (paired perception capture)**: Code-ready (rq3_capture_contract.py fixes the frame/rig
  mismatch bug), but (a) that code isn't on production yet (GAP-011), and (b) even once it is, live
  CARLA is required and GAP-017's RPC handshake bug blocks it. Action: GAP-011 must land (OpenCode, in
  progress); GAP-017 needs the focused Codex investigation queued below. Cannot be closed by
  delegation alone if GAP-017 turns out to be a genuine environment wall.
- **RQ4 (GNN structural-latent)**: Blocked by GAP-010, which is blocked by GAP-011 (see dependency
  chain). Once GAP-011 lands: GAP-010's exclusion fix can be completed, dataset rebuilt, retrained.
  Retraining is CPU-only on this machine (Torch 2.9.1+cpu, no CUDA) -- may itself need to be flagged
  BLOCKED_EXTERNAL depending on dataset size and time budget; this must be stated honestly when it's
  attempted, not glossed over.
- **RQ5(a) (map-transfer, 4-way auto/manual train x auto/manual test)**: Needs RQ3 data (blocked, see
  above) AND a trained segmentation checkpoint that does not exist anywhere in the repo. Cannot be
  started until RQ3 is unblocked. Not achievable this pass regardless of delegation.
- **RQ5(b) (real-world evaluation)**: No real-world dataset exists. Permanently BLOCKED_EXTERNAL until
  new data is acquired -- out of scope for any prompt below.

## Action plan (in dependency order)

1. **GAP-011 restoration** (OpenCode, currently dispatched) -- unblocks GAP-010 and RQ3/RQ4/RQ5(a)'s
   code-readiness. Highest-leverage single item in this whole plan.
2. **GAP-013/GAP-014 + branch splitting** (Codex, currently dispatched) -- independent, proceeds in
   parallel with #1.
3. **GAP-008 + fresh cross-package audit** (Gemini, currently dispatched) -- independent, proceeds in
   parallel.
4. **RQ1 re-verification** (Claude subagent, dispatching now) -- independent, cheap, offline.
5. **RQ2 re-verification** (Claude subagent, dispatching now) -- independent, offline, the single
   biggest RQ-answering action available right now that doesn't depend on anything else landing first.
6. **GAP-010 completion** (Codex, queued -- do not start until #1 lands) -- retry once GAP-011's
   OC-51 restoration is confirmed on production.
7. **GAP-017 (CARLA RPC handshake) focused investigation** (Codex, queued after #2's current tasks) --
   the narrowed evidence (port listens, real init, handshake-layer specifically) makes this worth one
   real attempt; unblocks RQ3 and transitively RQ5(a) if it succeeds.
8. **RQ4 retraining** (only after #1 and #6 land) -- not yet actionable, flagged for a future pass.
9. **RQ3 live capture run** (only after #1 and #7 land, if #7 succeeds) -- not yet actionable.
10. **RQ5(a)** (only after #9 lands and a segmentation checkpoint is trained, which is itself
    unscheduled) -- not yet actionable this pass.

## Honesty checkpoint

If asked "will all RQs be fully answered after this plan executes": no. RQ1 and RQ2 will be. RQ4's
code-readiness will be, but not the actual retrained result (compute-dependent). RQ3 depends entirely
on whether GAP-017 turns out to be fixable -- a real, open question, not a formality. RQ5(a) and
RQ5(b) are not reachable this pass under any delegation scheme currently available.
