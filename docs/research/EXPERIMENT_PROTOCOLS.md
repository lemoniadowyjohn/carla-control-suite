# Experiment Protocols

Every experiment records pinned input hashes, software versions, settings hash, producer commit,
seed(s), sample size, output hashes, and a claim boundary.

RQ1 uses committed timestamp-only XODR fixtures plus optional governed large-artifact integration.
RQ2 uses the same CRS, manual Grid0828 footprint, registration, sampling, threshold, and metric
implementation for thesis/current comparisons. RQ4 requires multi-seed, leakage-free splits,
bootstrap intervals, permutation statistics, k-sweeps, feature ablations, and a natural-vs-explicit
domain-randomization comparison. RQ3 requires valid generated and manual captures under identical
synchronous sensor and route contracts. RQ5 trains only on generated data before evaluating generated
holdout and manual holdout; real-world evaluation requires an approved external dataset.
