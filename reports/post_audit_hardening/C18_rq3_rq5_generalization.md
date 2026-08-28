# C18 (HIGH) — RQ3 + RQ5: train on auto → eval on sim-manual + real; adaptation + GNN  *(GPU ✅; real dataset ❌)*

Repo/branch/interp as C13. Plan: Phase R6. Depends on C17 captures. GPU available; real dataset DEFERRED.

## RQ3 / RQ5
RQ3: *impact of training on auto-generated maps on generalization (eval on manual-sim → mIoU)*.
RQ5: *how much generalization to simulated Ingolstadt + **unlabeled real-world** data (reported as SHIFT)*.

## Steps
1. **RQ3 train + sim eval (now):** train segmentation on the AUTO capture — **class-weighted** CE
   (`perception/min_train_segmentation.py` + `class_weights.py`, A5); eval on the MANUAL-sim capture →
   **mIoU/pixel-acc** (`perception/eval_sim_labeled.py`). Methodology: fixed splits/epochs/seed from
   `protocol.yaml`; controls (train-manual→eval-auto for symmetry). Bounded by path-A fidelity until cooked.
2. **RQ5 real eval (DEFERRED until dataset path supplied):** eval the trained model on the **unlabeled real**
   Ingolstadt images (`perception/eval_real_unlabeled.py`) → entropy/confidence/Fréchet on pooled logits.
   **Claim boundary (hard):** these measure **domain SHIFT, not accuracy** — no accuracy claim on unlabeled real.
3. **Domain adaptation (offline, now):** CORAL (`domain_gap/adaptation/coral.py`) + mean-matching (A7 renamed from
   MMD) + true `mmd_loss` — "how much does adaptation close the sim→real feature gap"; run via `adaptation_runner.py`.
4. **GNN latent gap (offline, now):** `tools/run_gnn_pipeline.py` + `domain_gap/feature_gap.py` on the pair’s
   map/feature embeddings (A2-characterized MapEncoder) → latent structural gap.
5. **Drive `run_generalization_experiments.py`** so `infer_generalization_component_statuses` emits honest
   per-component status: `simulated_manual_eval` → prototype/authoritative; `real_unlabeled_eval` → deferred (until
   #2); `paired_ingolstadt_generalization` → deferred until cooked (C16).

## Boundaries / verdict
- Real-unlabeled = SHIFT not accuracy (enforced in the report text + `run_generalization` claim_boundary string).
- Verdict: `RQ3 mIoU=<x> ; adaptation_closed=<%> ; GNN_gap=<y> ; RQ5=DEFERRED(real_dataset)`.
