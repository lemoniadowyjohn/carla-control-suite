# RQ4 statistical evaluation specification (design only; nothing has been run, and no p-values exist)

## Question
Do auto-generated and manually authored maps of the same region occupy **distinguishable** regions of
the learned map-embedding space, beyond what is expected between two samples of the **same**
domain?

## 1. Sampling unit and spatial autocorrelation
- **Unit:** a spatial **block**, not a tile. Neighbouring tiles share roads and junctions and are
  strongly autocorrelated.
  - Partition the region into blocks of size **B** (pre-register it, e.g. 500 m × 500 m).
  - Choose B such that the correlation of embedding similarity between adjacent blocks is below a
    stated level (measure it with a variogram of tile embeddings in the pilot, before the main test).
- **Block embedding:** the mean of its tile embeddings (or a set-level statistic). Each block has an
  auto version and a manual version only where **both maps cover it**: Grid0821/Grid0828 coverage
  defines the eligible blocks.
- **Effective n:** the number of eligible blocks, not the number of tiles. Report it. If n is less
  than about 10, report descriptive statistics only, with no inference.

## 2. Test statistic (corrected 2026-11-04)
The earlier draft used `T = mean_b d(a_b, m_b) − mean_{b≠b'} d(m_b, m_b')`. Its first term is
**invariant** under a within-block label swap: cosine distance is symmetric, so swapping the labels
of block b leaves `d(a_b, m_b)` unchanged. That statistic is withdrawn.

**Primary statistic (pre-register one):** the energy distance between the two block-embedding sets
A = {a_b} and M = {m_b},

`E = 2·mean_{b,b'} d(a_b, m_b') − mean_{b,b'} d(a_b, a_b') − mean_{b,b'} d(m_b, m_b')`.

Swapping a_b ↔ m_b moves an embedding between the sets, so E changes. Use d = the cosine distance on
L2-normalized embeddings (or Euclidean; pre-register which).

**Secondary statistic:** the held-out accuracy of a linear domain-label probe, trained and tested on
disjoint, spatially separated block sets.

## 3. Null, permutation and exchangeability (corrected 2026-11-04)
- **H0 (strong form):** within each eligible block, the pair (a_b, m_b) is exchangeable: the two
  maps' representations of the same place come from the same distribution. Independent per-block
  swaps are exact only if this holds **conditionally, independently across blocks**.
- **Why blocking alone is not enough:** roads and junctions cross block borders, neighbouring tile
  embeddings share content, the GNN receptive field spans blocks, and authoring conventions vary
  smoothly over space. Any of these creates dependence that per-block independent swaps ignore.
- **Mitigations (all required):**
  1. **Border buffer:** drop tiles within the GNN receptive-field radius (in metres, derived from the
     message-passing depth and edge lengths) of every block border, before forming block
     embeddings.
  2. **Restricted (cluster) permutation as sensitivity:** swap labels jointly for clusters of k × k
     adjacent blocks (k = 1, 2, 3), and report E's permutation p for each k. A result that holds
     only at k = 1 is not robust.
  3. **Block-size sensitivity:** pre-register a primary B and report ≥ 3 sizes.
  4. **Pilot variogram** of the block-level statistic, used only to choose B and the buffer; the
     pilot data is not reused for the test.
- **Permutation procedure:** per block (or cluster), swap the labels with probability ½. Enumerate
  exactly if the number of units n ≤ 20; otherwise use 10,000 random swaps. Recompute E. Report the
  p-value as `(1 + #{E_perm ≥ E_obs}) / (1 + N_perm)`.
- **Coverage:** restrict to blocks covered by **both** maps, and report the coverage of each map.
  Swapping is undefined where one domain is absent.
- **Scope, stated next to the result:** with one region and one map per domain, the p-value is
  **conditional on this region's realization**. It tests within-region structure, not a population
  of map pairs.
- **Not allowed:** tile-level permutation, because it would inflate significance.
- **Historical test:** the thesis-era K=1000 permutation (p<0.001;
  `docs/research/THESIS_TO_CURRENT_PROGRESS.md:14`) has an undocumented unit and statistic, and
  predates the graph-builder and GAP-010 fixes. It is not a substitute for this design.

## 4. Within-domain null (required controls)
- **Manual vs manual:** two disjoint halves of the manual map (by blocks), giving the
  `d_within_manual` distribution.
- **Auto vs auto:** two disjoint halves of the auto map; and **auto vs auto re-generation** (two
  structurally identical runs) as a sanity control, where d should be ≈ 0.
- **Identity control:** a map against itself, where d must be 0. If not, the pipeline is broken.
- **Shuffled-feature control:** permute node features within the graph; the embedding must change
  (guards against the model ignoring features).

## 5. Training-seed vs geographic uncertainty
- Seeds (≥ 5) and blocks are **separate** sources of variance.
- For each seed s, compute E_s and its permutation p_s. Report:
  - (a) the median and range of E_s over seeds;
  - (b) the fraction of seeds with p_s < α.
- For an aggregate, use a hierarchical bootstrap: resample seeds, then blocks within each seed.
- Never pool seeds as if they were extra data points.

## 6. Feature-schema identity
- Record `graph_schema_hash(width_mode=…)` (`graph_builder.py:272`) for training and evaluation;
  they must be equal.
- Use one pre-registered width mode (`polynomial` is preferred; `legacy` ignores width polynomials).
- Record the junction-edge policy (`no_edge_when_junction_mediated`), and state that the embeddings
  carry no junction topology.

## 7. Normalization
- Per-feature standardization is fitted on the **training** split only, and applied to both
  domains.
- L2-normalize embeddings before the cosine distance, and record it.
- No domain-specific normalization; it would remove the effect being measured.

## 8. Representation collapse and degenerate-separation controls
- Report the embedding rank and effective dimension (the participation ratio of the covariance
  eigenvalues), and the mean pairwise cosine within each domain.
- **Collapse:** if within-domain cosine is about 1 for all blocks, the space has collapsed, and any
  cross-domain distance is uninformative.
- **Trivial separation:** train a linear probe for the domain label on a held-out block split. If it
  reaches ~100% using only trivially domain-specific features (e.g. a node-count scale), report this
  as an authoring-convention artefact, not a structural difference. Repeat with size-normalized
  features.

## 9. Multiple comparisons
If several statistics (cosine, Euclidean, probe accuracy) or several block sizes B are tested,
pre-register **one** primary test. Treat the others as secondary, with Holm–Bonferroni correction
across the secondary family.

## 10. Population scope
A single region (Ingolstadt) with one map per domain supports **no population claim**. A population
statement needs ≥ 2 independent regions, each with its own manual map. The 5-seed interval
0.921 [0.845, 0.976] is reported as historical seed variability, with the value unchanged.

## 11. Pre-registration checklist
Fix all of the following before running:
- B;
- d;
- the statistic (E, energy distance);
- α;
- the primary test;
- N_perm;
- the width mode;
- the seeds;
- the eligible-block rule.
Commit them as a protocol file and hash it. Results computed without a frozen protocol are
exploratory.
