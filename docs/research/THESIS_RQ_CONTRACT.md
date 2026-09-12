# Thesis RQ Contract

The authoritative machine-readable contract is [thesis_rq_contract.yaml](../../research/thesis_rq_contract.yaml).
The exact questions are preserved there and must not be renumbered to match implementation history.

| RQ | Authority | Current boundary |
|---|---|---|
| RQ1 | Determinism | Structural result authoritative; normalized bytes bounded |
| RQ2 | Structural domain gap | Bounded local comparison |
| RQ3 | Perceptual domain gap | Deferred runtime |
| RQ4 | Variability and latent representation | Thesis baseline preserved; current extension authoritative where evidenced |
| RQ5 | Generalization and transfer | Deferred runtime/external data |

Run `python -m ultimate_pipeline.tools.audit_thesis_topic_contract` to detect invalid metric-to-RQ
associations.
