# RQ4 inference limits

| Evidence | What it can support | What it cannot support |
|---|---|---|
| Historical 0.9207 [0.845, 0.976] (5 seeds; whole-map embeddings of Grid0821 vs candidate_connectivity_repaired) | "In five training runs, the two whole-map embeddings of this pair had cosine distance 0.77-0.99" (descriptive) | any separation test; uncertainty over places or maps; any claim about other map pairs; comparison with RQ2 (a different map pair) |
| Superseded 0.6434 [0.616, 0.676] | the history of the GAP-010 leak | any current claim |
| Thesis-era K=1000 permutation p<0.001 | that such a result was reported in thesis materials (REPORTED_NOT_REPRODUCED) | support for 0.921 or for the new design; it predates the graph-builder and GAP-010 fixes, and its unit is undocumented |
| 562 union tiles | training-data volume | the number of independent evaluation units (those are the spatial clusters of the evaluation region, n_c) |
| 5 seeds | robustness of the conclusion to training stochasticity | geographic or map-population uncertainty |
| A future pre-registered test (the draft), if it rejects H0 | "within this region, for this pair and these checkpoints, auto and manual unit embeddings differ in distribution (under the exchangeability assumption)" | "auto maps differ from manual maps in general"; causal attribution to "structure" without the composition controls; equivalence if H0 is not rejected (a non-rejection is not evidence of similarity) |
| Any result with composition controls failing | an embedding difference that may be explained by segmentation or convention | a structural-difference claim |

**Population claims** need ≥ 2 independent regions, each with its own independently authored manual
map, analysed under the same frozen protocol. None exist today.
