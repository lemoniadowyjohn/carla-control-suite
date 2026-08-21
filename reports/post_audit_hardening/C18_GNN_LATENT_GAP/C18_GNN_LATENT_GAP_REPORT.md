# C18 — GNN latent domain gap (auto ↔ manual), trained MapEncoder

**Cross-cutting RQ item:** learned-representation (GNN) latent gap between the pinned auto map of record and the
manual Grid0828, complementing the raw structural gap (RQ1 / C14).

## Setup
- **Encoder:** `ultimate_pipeline/domain_gap_gnn/map_encoder.py::MapEncoder` (128-dim, unit-normalized output).
- **Training:** `train_map_encoder` — **50 epochs**, batch 16, lr 1e-4, **seed 42**, `torch_deterministic=true`, **device=cpu**
  (torch 2.9.1+cpu / PyG 2.7.0). Trained on the auto map's **529 tiles**
  (`campaigns/…/regen/20260819T153954Z/pipeline_out/tiles`). final_loss = **2.4536**.
  Checkpoint `map_encoder_epoch50.pt` (md5 `0f9cc638da2030eea4cf8657dac0a663`).
- **Latent gap:** encode auto (`69b1f520…`) + manual Grid0828 (`5eaece23…`) → `combine_latent_gaps`.

## Latent gap (`combine_latent_gaps`)
| metric | value | meaning |
|---|---|---|
| **cosine_distance** | **1.1423** | substantial latent separation |
| cosine_similarity | **−0.1423** | embeddings nearly orthogonal, slightly anti-correlated |
| l2 | 1.5115 | (consistent with 128-dim unit vectors, cos −0.14) |
| l1_mean | 0.1097 | |
| mse | 0.01785 | |

A similar-map pair would sit near cosine **+0.8–0.95**; these two sit at **−0.14** → the learned encoder sees the
maps as strongly dissimilar. This **corroborates RQ1** (C14): the maps differ substantially in structure.

## Claim boundaries (mandatory — carried per the thesis contract)
1. **One-sided training → OOD confound (the big one).** The encoder was trained on the **auto map's tiles only**, so
   Grid0828 is **out-of-distribution** for it. The −0.14 cosine therefore **conflates genuine structural difference
   with the manual map being unlike the training distribution**. It cannot be cleanly decomposed from a one-sided run.
   → **PROTOTYPE / structural-projection**, NOT an authoritative learned domain-gap.
2. **Reproducible ≠ valid.** `seed=42` + `torch_deterministic=true` → identical checkpoint (md5 above) and identical
   numbers on re-run. That is reproducibility, not validity. No held-out validation, single training run (no
   seed-ensemble / CI on the metric).
3. **CPU-trained, self-supervised pretext, loss scale uncontextualized** (final_loss 2.45 has no held-out baseline to
   judge convergence).
4. **Consistent-with, not independent-of RQ1.** This echoes RQ1's structural separation using a learned encoder; it is
   corroboration, not an independent second measurement (both read the same underlying structural difference).

## Honest answer
The learned map encoder places the auto and manual maps **far apart** in latent space (cosine −0.14, distance 1.14),
**corroborating the RQ1 structural gap**. Treat this as a **bounded, reproducible PROTOTYPE** latent-gap number, not an
authoritative learned domain-gap — the one-sided (auto-only) training makes the manual map OOD, so the magnitude mixes
true gap with distribution-shift. A symmetric/authoritative version requires training on **both** maps' tiles (or a
held-out split) and a seed-ensemble CI.

## Follow-up to reach AUTHORITATIVE (deferred)
- Train on the **union** of auto + manual tiles (needs Grid0828 tiled — the manual side is currently un-tiled).
- Seed-ensemble (≥5 seeds) → report cosine-distance mean ± CI.
- Cross-validate against RQ1 per-aspect gaps (does the latent axis align with lane-width / curvature / topology?).

Machine-readable: `gnn_training_report.json` (checkpoint md5, determinism flags, metrics).
