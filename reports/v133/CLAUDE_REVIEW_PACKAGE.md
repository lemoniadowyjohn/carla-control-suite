# Independent Claude review package

Review this exact candidate source commit: `390a2c536c0ca5bb9131f43a4aa23265cf8272c2` (plus the following evidence-only commit if present in branch history). Production base: `225ed15d0da6444cc257835ca777aba281553f3c`.

Review scope: OC-A release/scope/XML stack, PR #49 fuzzer, PR #56 feature-gap missingness, PR #57 OSM O1/O2, and PR #40/#45/#46 O3 road-graph changes. The integration/ancestry record is in `DEPENDENCY_ANCESTRY.md`; test totals and limitations are in `TEST_EVIDENCE_MATRIX.md`.

Priority adversarial checks:

- Confirm trusted map scope is upstream-bound, candidate digest is immutable across evaluation/publication, XML rejects hostile declarations, and all mandatory release gates fail closed.
- Confirm fuzzer scaling and feature-gap invalid/missing measurement behavior remain scientifically bounded.
- Confirm OSM legal-movement helpers are not represented as operational until production call sites exist; inspect O3 road membership/source evidence and negative controls.
- Confirm no regressions from the integration merges and inspect the documented exclusions.

Known excluded defects: OC-D RQ5 v2 receipt admission defects; T1 sensor-set identity regression; unwired CRS helper and OSM legal-movement helper; unverified Windows lifecycle/lease changes. Full offline CI, exact-head GitHub checks, live CARLA, RQ3 capture, and RQ5 experiments are NOT_RUN. Do not approve production readiness from focused tests.
