# C21 (HIGH) — GNN latent gap: PROTOTYPE → AUTHORITATIVE

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803` · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1 (fully offline)
Rules: TDD for code changes; full-suite green; **EXPLICIT-PATHSPEC commit**; conservative claim boundaries.
**Model: Codex 5.5, reasoning effort xhigh.** Depends on C13 (pinned pair) + C18 (existing GNN pipeline). Independent of CARLA/UE — do not touch carla_utils.py (actively owned by a concurrent GPU-TDR investigation) or anything CARLA-runtime related.

## Why this task, and why Codex xhigh
C18's GNN latent-gap result (`cosine_distance=1.14`, `reports/post_audit_hardening/C18_GNN_LATENT_GAP/`) is real
and reproducible but stuck at **PROTOTYPE**, not AUTHORITATIVE, for two stated reasons (see
`C18_GNN_LATENT_GAP_REPORT.md`, "Follow-up to reach AUTHORITATIVE"):
1. The encoder trained on the auto map's 529 tiles ONLY — Grid0828 (manual) was never tiled, so it's
   out-of-distribution for the encoder, and the −0.14 cosine similarity conflates true structural
   gap with distribution shift.
2. Single training run, single seed (42) — reproducible ≠ valid; no CI, no seed-ensemble.

This is exactly the shape of work Codex at high reasoning effort is well suited for: a long, mechanical,
carefully-specified sequence (tile a new map through an existing pipeline, run N training seeds, aggregate
statistics with a CI) that needs patience and precision more than architectural judgment — the design
decisions are already made below; execution needs to be careful and thorough across ~5+ training runs.

## Inputs (verified present)
- Auto map tiles (529): `campaigns/ingolstadt_cooked_perception_v1/regen/20260819T153954Z/pipeline_out/tiles`
- Manual map (untiled): `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr` (sha256 `5eaece23...`, pinned — verify via `ultimate_pipeline.carla_tools.map_registry.verify_pinned_map("Grid0828")` before touching it)
- GNN training entrypoint: `ultimate_pipeline/tools/run_gnn_pipeline.py` (produced the existing C18 checkpoints/report)
- Tile dataset loader: `ultimate_pipeline/domain_gap_gnn/map_tile_dataset.py::MapTileDataset`
- Latent gap combiner: `ultimate_pipeline/domain_gap_gnn/latent_gap_utils.py::combine_latent_gaps`
- Existing tiling infrastructure (reuse, don't reinvent): `ultimate_pipeline/domain_gap/tile_grid_meta.py`, `tile_matcher.py`, `per_tile_gap.py` — whichever one actually produced the 529 auto tiles; trace `campaigns/.../regen/20260819T153954Z/pipeline_out/tiles`'s generating stage in the pipeline log before writing new tiling code.

## Steps (TDD for any new code; the training runs themselves are not unit tests)
1. **Tile Grid0828.** Find and reuse whatever pipeline stage produced the 529 auto tiles (do not write a
   parallel/divergent tiling implementation) and run it against the pinned manual map. Record: tile count,
   tile grid alignment/frame relative to the auto tiles (Grid0828 is UTM-32N, auto is a rebased local frame
   — the tile grid must be self-consistent per-map, it does NOT need to spatially align auto-to-manual for
   this task, since this is encoder training data, not a paired spatial comparison).
2. **Train on the UNION of both maps' tiles.** Extend/parameterize `run_gnn_pipeline.py` (or `MapTileDataset`)
   to accept multiple tile directories and train one `MapEncoder` on the pooled auto+manual tile set. Keep
   the existing hyperparameters (50 epochs, batch 16, lr 1e-4, `torch_deterministic=true`, device=cpu) unless
   you have a specific, documented reason to change one — note any deviation explicitly in the report.
3. **Seed-ensemble (≥5 seeds).** Train ≥5 independent runs (seeds e.g. 42, 43, 44, 45, 46), each producing its
   own checkpoint + `combine_latent_gaps` result on the auto/manual pair. This is the expensive, long-running
   part — each run is comparable in cost to the existing 50-epoch/529-tile run that produced
   `map_encoder_epoch50.pt`; budget for ≥5x that wall-clock time.
4. **Aggregate with a CI.** Report mean ± 95% CI (or bootstrap CI, document which) for `cosine_distance` and
   `cosine_similarity` across the 5 seeds. A tight CI that excludes 0 (no-gap) supports AUTHORITATIVE; a wide
   CI spanning across sign changes does not — report honestly either way, do NOT round a borderline CI into a
   clean-sounding claim.
5. **Cross-validate against RQ1.** C14's per-aspect structural gaps (`reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/curvature_recompute.json`'s `all_scores`) found `lane_width_gap=0.042` (small, maps agree) vs `curvature_gap≈0.09-0.27` (moderate) vs `road_length/traffic_light/building` (large, but flagged as construction artifacts, not domain gap). Check whether the GNN's learned latent axis correlates more with the genuine small/moderate structural aspects or with the construction-artifact aspects — if it's dominated by the same construction artifacts RQ1 already flagged (road count, object density), say so explicitly; that would mean the GNN number is NOT adding independent signal beyond RQ1, which is itself an important, honest finding.
6. **Update the honesty-gate tooling.** `tools/export_thesis_tables.py::_rq3_rq5_rows` currently hardcodes the
   GNN row as PROTOTYPE with a fixed note. If your result genuinely clears both follow-up items (union
   training + seed-ensemble CI), update that row's status to AUTHORITATIVE with the new mean/CI values and
   note — do NOT hand-edit `rq_tables.json` directly, change the exporter so re-running it reproduces your
   claim. Then re-run `ultimate_pipeline/tools/audit_thesis_topic_contract.py` and
   `tools/validate_thesis_claim_provenance.py` (both already exist, C19) and confirm they still pass — if your
   change makes either fail, the change is wrong, fix it, don't loosen the gate.

## Boundaries
- Do NOT touch `ultimate_pipeline/core/carla_utils.py` or anything CARLA-runtime-related — a concurrent
  session owns the GPU/TDR investigation there.
- Do NOT alter C14's structural-gap numbers or C6/C9's checker code — this task only adds a new, better GNN
  measurement; it does not revisit prior RQ1/continuity findings.
- If the CI is wide/inconclusive, report `PARTIAL` honestly rather than a clean AUTHORITATIVE claim — the
  entire point of this task is a *validated* number, not just a *bigger* one.
- Deterministic per-seed (torch_deterministic=true); document any nondeterminism you can't eliminate (e.g.
  known PyTorch CPU nondeterminism gaps) rather than silently ignoring it.

## Deliverables / verdict
- Tiled `Grid0828` tile set (path + count recorded).
- 5+ trained checkpoints (or however many seeds you ran) + per-seed `combine_latent_gaps` results.
- `reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/` — aggregated stats (mean/CI), the RQ1 cross-validation
  finding, and the per-seed raw results.
- `tools/export_thesis_tables.py` updated (if warranted) + `contract_audit.json` / `provenance_validation.json`
  re-run clean.
- Push (explicit pathspec); local==remote; full suite green.
- **Verdict:** `RQ3_GNN_UPGRADED cosine_distance_mean=<x> ci=[<lo>,<hi>] status=<AUTHORITATIVE|PARTIAL> corroborates_rq1=<yes|no|partial>` | BLOCKED.
