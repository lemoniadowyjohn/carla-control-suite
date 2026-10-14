"""Governance utilities.

Two disjoint sub-namespaces, one per concern:

* ``ultimate_pipeline.governance.single_writer`` -- the write-lock /
  supervision plane: named-mutex authority, PID + creation-time identity,
  lease store, Job Object supervision, receipt reconciliation. This is the
  single production governance layer for writer exclusivity.
* ``ultimate_pipeline.governance.reproducibility`` -- the C11
  reproducibility guards: the digest-pinned generation-inputs manifest guard
  (``reproducibility.inputs_manifest``) and the PROJ environment guard
  (``reproducibility.proj_env_guard``).

Historical note: both C11 guards used to sit directly under
``ultimate_pipeline.governance``; they were moved into
``governance.reproducibility`` when the write-lock package was adopted, to
remove the governance/ vs governance/single_writer/ naming inconsistency.
"""
