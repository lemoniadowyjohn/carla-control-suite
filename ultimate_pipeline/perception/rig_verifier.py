# ultimate_pipeline/perception/rig_verifier.py
"""
Named entry point for sensor-rig verification and sync-settings evidence.

Re-exports the rig and manifest gate helpers from tools/run_perception_safe
so that reviewers have a stable, importable reference to the rig-verification
boundary.

Full extraction deferred (T-MODULARIZE-RUN-PERCEPTION-SAFE-001).
"""

from __future__ import annotations

from ultimate_pipeline.tools.run_perception_safe import (  # noqa: F401 — public re-export
    _derive_sync_settings_evidence as derive_sync_settings_evidence,
    _enforce_manifest_gate_for_capture as enforce_manifest_gate_for_capture,
    _refresh_thesis_contract_artifacts as refresh_thesis_contract_artifacts,
    _classify_record_route_failure as classify_record_route_failure,
)

__all__ = [
    "derive_sync_settings_evidence",
    "enforce_manifest_gate_for_capture",
    "refresh_thesis_contract_artifacts",
    "classify_record_route_failure",
]
