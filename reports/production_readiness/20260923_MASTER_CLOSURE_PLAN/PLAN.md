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

- **RQ1 (determinism)**: **RE-VERIFIED, 2026-09-23** (commit `b0d134c7`, report
  `reports/production_readiness/20260923_RQ1_REVERIFICATION/RESULTS.md`). VERIFIED with the existing
  claim boundary unchanged: ran the real, unmodified, current-code harness twice as genuine fresh
  subprocesses from a fixed input XODR; stage 01 raw-byte-identical, stages 02-08_final become
  byte-identical once normalized per the established contract. One genuine refinement found (not a
  bug): `geometryFreezeHash` needs the same normalization treatment as the other timestamp-derived
  fields, since it's computed over still-timestamped content one level removed -- confirmed this makes
  04-08_final fully byte-identical too. **Honest scope gap, still open**: the newer stages most
  directly touched by the last 15 merges (xodr_validator, enrichment, tiling, the final-artifact-
  authority/receipt system) were never reached, because a single-tile fixture fails a genuine
  correctness gate (stage 08 lane connectivity) before those stages run -- this is the same
  "post-enrichment unverified" gap flagged open since 2026-08-28, not newly discovered and not closed
  by this pass. A follow-up with a complete (non-tile) seed map would be needed to extend coverage.
- **RQ2 (domain gap / hull footprint)**: **CLOSED, 2026-09-23** (commit `9d4d182b`, report
  `reports/production_readiness/20260923_RQ2_REVERIFICATION/RESULTS.md`). Correction to this plan's
  earlier framing: RQ2 had already been re-verified once before, on 2026-09-17 (commit `c3915130`) --
  this pass independently confirmed that, then re-ran the same real entrypoint
  (`scripts/regen_local_registration.py` / `regen_frechet_distance.py`) against the still-current pin
  (`370abbbb...`, unchanged since 09-16/17) and got byte-identical output to 09-17: hull ratios
  2.683x/3.782x/3.561x, curvature gap 0.2206, local Fréchet mean/median/p90 58.18/36.13/140.48m.
  Root cause of the non-movement independently confirmed by code inspection, not assumed: neither
  `local_registration.py` nor `frechet_gap.py` imports `GeoAligner` or `CurvatureGap` at all -- the
  2026-09-14/16 fixes to those modules had no code path into this metric. The figure is also now shown
  robust across 5 real map-of-record promotions (09-02 through 09-17, moved <0.5%), not an artifact of
  one snapshot. No doc edit needed -- `THESIS_TO_CURRENT_PROGRESS.md`'s RQ2 row already states the
  correct current figures.
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

## Cook readiness (2026-09-23, Codex re-confirmation -- GAP-018)

Re-confirms and sharpens the 2026-09-22 finding: G: has ~190GiB free (healthy), a real CARLA UE4
source project exists (`G:\CARLA\carla_source_probe\Unreal\CarlaUE4\CarlaUE4.uproject`), and a
packaged CARLA 0.9.16 server exists on E:. **Still missing**: the UE4.26 engine/toolchain itself
(`G:\UE4\Engine\Binaries\Win64\UE4Editor.exe` and `RunUAT.bat` both absent -- no amount of delegation
produces these, this requires an actual engine install, a human/environment action, not a code fix),
and no materialized final package on G: (no `final_artifact_receipt.json`, no `visual_grid_manifest.json`,
no complete visual tile/FBX set) -- so there is currently nothing eligible to import even if the engine
were present. The 5-step minimum cook ladder (produce+verify receipt/manifests -> strict offline
package validation -> install UE4.26 -> import synthetic->one-tile->2x2/3x3 -> cook+validate) cannot
start until both the package-materialization work (downstream of GAP-011) and a UE4.26 install happen.
**This entire path is BLOCKED_EXTERNAL for the engine-install step specifically -- flag to the user,
not something to keep re-querying Codex about until that changes.**

## Action plan (in dependency order)

1. **GAP-011 restoration** (OpenCode, currently dispatched) -- unblocks GAP-010 and RQ3/RQ4/RQ5(a)'s
   code-readiness. Highest-leverage single item in this whole plan.
2. **GAP-013/GAP-014 + branch splitting** (Codex, currently dispatched) -- independent, proceeds in
   parallel with #1.
3. **GAP-008 + fresh cross-package audit** (Gemini, currently dispatched) -- independent, proceeds in
   parallel.
4. **RQ1 re-verification** -- DONE, 2026-09-23 (commit `b0d134c7`). Verified, with an honest scope
   gap flagged (post-enrichment stages not exercised) -- see RQ-by-RQ section above.
5. **RQ2 re-verification** -- DONE, 2026-09-23 (commit `9d4d182b`). Confirmed unchanged and robust;
   see the RQ-by-RQ section above.
6. **GAP-010 completion** (Codex, queued -- do not start until #1 lands) -- retry once GAP-011's
   OC-51 restoration is confirmed on production.
7. **GAP-017 (CARLA RPC handshake) focused investigation** (Codex, queued after #2's current tasks) --
   the narrowed evidence (port listens, real init, handshake-layer specifically) makes this worth one
   real attempt; unblocks RQ3 and transitively RQ5(a) if it succeeds.
8. **RQ4 retraining** (only after #1 and #6 land) -- not yet actionable, flagged for a future pass.
9. **RQ3 live capture run** (only after #1 and #7 land, if #7 succeeds) -- not yet actionable.
10. **RQ5(a)** (only after #9 lands and a segmentation checkpoint is trained, which is itself
    unscheduled) -- not yet actionable this pass.
11. **Cook ladder (GAP-018)** -- re-confirmed 2026-09-23 BLOCKED_EXTERNAL on UE4.26 engine absence
    (requires a human/environment action: install the engine) AND on package materialization
    (downstream of #1). Do not schedule further Codex/OpenCode/Gemini prompts against this until the
    user has installed UE4.26 or the environment otherwise changes -- re-querying it produces the same
    answer and wastes a round-trip.

## Honesty checkpoint

If asked "will all RQs be fully answered after this plan executes": no. **RQ1 and RQ2 are now both
re-verified/closed** (2026-09-23). RQ1 still carries an honest, unresolved scope gap (post-enrichment
stages unexercised by any determinism check, open since 2026-08-28 -- not this pass's job to close).
RQ4's code-readiness will be reachable, but not the actual retrained result (compute-dependent). RQ3
depends entirely on whether GAP-017 turns out to be fixable -- a real, open question, not a formality.
RQ5(a) and RQ5(b) are not reachable this pass under any delegation scheme currently available. **New
2026-09-23**: the UE4 cook ladder (relevant to any eventual streaming/VRAM/runtime claims) is also
confirmed blocked specifically on engine installation -- a genuine environment gap, not something any
amount of Codex/OpenCode/Gemini prompting closes. GAP-010 remains BLOCKED_EXTERNAL too, re-confirmed
by Codex (branch fix/rq4-leakage-complete-20260923 @ 95d63b8a, no false fix claimed) -- waiting on #1
(GAP-011) exactly as this plan already stated.
