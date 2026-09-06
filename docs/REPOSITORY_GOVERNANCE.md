# Repository Governance

The submitted thesis questions are immutable. Changes to metric definitions, RQ mapping, frozen
hashes, map identity, or claim status require a provenance-bearing receipt and focused tests.

Historical evidence is append-only. A portability correction supersedes an interpretation without
rewriting the historical artifact. Research rows must include producer commit, evidence hash, input
hashes, method, sample size, seeds, comparability, claim boundary, and blocker.

Use atomic commits by concern. Do not force-reset or overwrite legacy branches. Offline CI cannot
certify a live CARLA runtime; it must report runtime verification as `NOT_RUN`.
