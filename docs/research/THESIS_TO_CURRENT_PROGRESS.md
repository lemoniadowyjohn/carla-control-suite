# Thesis baseline vs. current state

This tracks what has changed in each research question's evidence since the submitted thesis
(`submission/thesis_source/`). RQ numbers match the thesis (`Chapter1/chap1.tex`, lines 24-28), which
is the authoritative source if this table and the code ever disagree — verify against
`reports/post_audit_hardening/C19_THESIS_ASSEMBLY/rq_tables.json` (regenerate via
`tools/export_thesis_tables.py`) rather than trusting this file's prose in isolation.

| RQ | Thesis baseline | Current state | What changed |
|----|-----------------|----------------|---------------|
| RQ1 — Determinism | Byte-level nondeterminism source not fully isolated | AUTHORITATIVE: Osm2Odr is structurally deterministic across repeated runs on the same pinned OSM input (identical roads/junctions/total length); only non-semantic serialization bytes vary. Explicit domain randomization (`RealismAugmentor`) confirmed wired: deterministic given a seed, varies across seeds. | Post-thesis root-causing (`C15_RQ4_DR`) and a normalized-hash test (`test_exp_osm_to_xodr_determinism_normalized.py`) isolated the exact two byte-level divergence points (a timestamp comment and a header date attribute) — closes thesis future-work item #13. |
| RQ2 — Structural domain gap | Whole-map comparison only; a delivered discrete-Fréchet number computed on an uncropped, misaligned network | BOUNDED, with a corrected **local** (manual-map-footprint) comparison as the primary result: lane-width gap is small and the maps agree; curvature/road-length ratios show a real completeness gap (~2.7-3.8x under a convex-hull footprint, revised down from an earlier 4.5-6x bbox-footprint estimate); building density is now a genuine in-footprint comparison instead of force-excluded. A recomputed local Fréchet distance is ~30-50x smaller than the thesis's original whole-network number. | `C14_RQ1_STRUCTURAL_GAP` + `C26` local-registration work; closes thesis future-work item #14 (Fréchet distance) with a corrected, scope-appropriate methodology. |
| RQ3 — Perceptual domain gap | Deferred/bounded pending the paired-capture experiment | Still DEFERRED — zero evidence exists. | No change in evidence; the blocker is now precisely characterized: a live CARLA server never becomes RPC-responsive, confirmed independent of map choice and rendering backend (`-nullrhi` isolation) and independent of the GPU driver (a chronic TDR watchdog fault was found and fixed separately, but the RPC hang persists) — see `reports/post_audit_hardening/C20_TIER1_PROBE_20260821/` and related C20 reports. |
| RQ4 — Structural variability / latent representation | Not part of the delivered thesis result set (a "future work" direction) | AUTHORITATIVE: a 5-seed GNN ensemble trained on the union of both maps' road-network graphs reports cosine_distance mean 0.6434 (95% bootstrap CI [0.616, 0.676]), CI excludes zero across all 5 seeds. Explicit domain-randomization wiring independently confirmed (see RQ1). | New work post-thesis (`C18_GNN_LATENT_GAP` → `C21_GNN_AUTHORITATIVE`); the numbers changed materially on 2026-09-01 after fixing a graph-construction bug (lane-link edges were resolving to their own lane section instead of the successor's, making ~99.8% of training edges self-loops) — always cite the ensemble's caveat (auto+manual union training resolves the single-map OOD issue, but this is still a prototype-adjacent research direction, not a delivered thesis claim). |
| RQ5 — Generalization and transfer | Not executed within thesis scope; explicitly deferred to future work | Still DEFERRED for both sub-parts. RQ5(a) (mIoU / domain-adaptation transfer to the manual map) needs the same blocked RQ3 paired-capture pipeline. RQ5(b) (real-world unlabeled shift) is separately blocked — no real-world Ingolstadt dataset exists on this machine. | No new evidence; the two sub-blockers are now independently confirmed rather than assumed. |

## Infrastructure changes not tied to a specific RQ

- **CI correctness**: fixed a global `builtins.print` monkeypatch that entrypoint modules applied at
  import time (corrupted JSON output for any test running later in the same process), a racy
  fake-sensor test helper that could cross-contaminate RGB/semseg frames, a gitignored-file test
  dependency, and a CRLF/LF cross-platform checkout mismatch in a frozen evidence manifest's hash
  check.
- **Packaging**: `pyproject.toml` previously packaged only `ultimate_pipeline`, silently excluding
  `opendrive_geometry/` and `phase_q/` (both actively imported elsewhere) from any built wheel.
- **RQ-numbering integrity**: `tools/export_thesis_tables.py` had drifted from the thesis's actual RQ
  numbers (structural gap tagged "RQ1" instead of RQ2, perceptual gap tagged "RQ2" instead of RQ3, GNN
  work tagged "RQ3/RQ5" instead of RQ4). Relabeled (values unchanged) and added
  `ultimate_pipeline/config/thesis_rq_contract.py`, an explicit metric→RQ allow-list that
  `audit_thesis_topic_contract.py` now validates against, so a future numbering drift fails the audit
  instead of passing silently.
- **`pipeline_health_summary.py`**: previously reported `overall_ok=True` when zero gate evidence was
  collected at all (e.g. no `qa_stage_reports/` directory) — indistinguishable from "every gate ran
  and passed." Now reports `overall_ok=False`, `status="NOT_RUN"` for that case.

## Still blocked, not a code-level gap

- **RQ3 live paired capture** and **RQ5(a) transfer evaluation**: both need a working CARLA runtime.
  The RPC-hang blocker is environment-level, not something further code changes here can resolve.
- **RQ5(b) real-world evaluation**: needs an operator-supplied real-world Ingolstadt dataset.
- **RQ2 thesis-vs-current controlled comparison, RQ4 multi-seed extensions**: legitimate follow-up
  research, not corrections — not attempted as part of infrastructure hardening passes.
