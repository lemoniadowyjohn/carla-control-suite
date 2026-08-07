"""Phase Q - Final Perception-Release Hardening controls (Q0..Q16).

Pure-Python, offline-capable modules that implement the perception-release
hardening addendum:

Q0  provenance           - clean/dirty worktree evidence capture
Q1  certifier_decision   - injectable Phase N verdict engine + negative controls
Q2  semantic_policy      - STRUCTURAL_XODR / PACKAGED_MAP / PERCEPTION_RELEASE
Q3  semantic_evidence    - full semantic source/runtime/package equivalence
Q4  governed_payload     - governed load-payload artifact (Strategy B)
Q5  server_attestation   - runtime process / server identity attestation
Q6  actor_binding        - packaged-map signal/crosswalk actor binding (fail-closed)
Q7  spawn_nav_gate       - spawn-point and navigation-quality gate
Q8  label_ontology       - frozen semantic label ontology + QA contract
Q9  protocols            - evaluation protocol + hold-out registry
Q10 thresholds           - frozen threshold registry
Q11 package_build        - reproducible-cook comparison harness
Q12 clean_replay         - second-installation replay harness
Q13 resource_profiles    - governed hardware profiles
Q14 watchdog             - crash supervision, evidence preservation
Q15 manifests            - run-local / external / archive manifests
Q16 audit                - independent final review gating
"""

from phase_q.common import (
    sha256_bytes,
    sha256_file,
    sha256_text,
    load_json,
    save_json,
    load_text,
    save_text,
    utcnow_iso,
    make_run_id,
    XodrTree,
    ensure_encoding,
)

__all__ = [
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "load_json",
    "save_json",
    "load_text",
    "save_text",
    "utcnow_iso",
    "make_run_id",
    "XodrTree",
    "ensure_encoding",
]
