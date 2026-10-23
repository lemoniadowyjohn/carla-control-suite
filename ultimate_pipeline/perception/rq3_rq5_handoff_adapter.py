#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ3_TO_RQ5_HANDOFF/v1 adapter.

This is the ONLY interface between RQ3 (frozen scientific paired capture)
and RQ5 (Codex-owned training/evaluation protocol). It is intentionally
frozen: Codex must validate the schema and reject any incomplete,
historical, diagnostic, or synthetic capture.

Requirements (from Phase 6 / P1-12):
- Frozen RQ3 protocol SHA bound
- Accepted RQ3 pair receipt SHA bound
- Manual and automatic capture identities
- Actual runtime rig SHA
- Complete-frame index with per-member file digests
- RGB/semantic class mapping (29-class, ignore 255)
- Candidate partition metadata (not an unauthorized split)
- Explicit DATASET_NOT_ADMITTED when capture is not accepted
- No production dataset roots from historical/incomplete captures
- No synthetic fixtures registered as real captures
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

HANDOFF_SCHEMA_VERSION = "RQ3_TO_RQ5_HANDOFF/v1"
HANDOFF_STATUS_ADMITTED = "DATASET_ADMITTED"
HANDOFF_STATUS_NOT_ADMITTED = "DATASET_NOT_ADMITTED"
HANDOFF_STATUS_BLOCKED = "DATASET_BLOCKED"
HANDOFF_STATUS_INCOMPLETE = "DATASET_INCOMPLETE"


@dataclass
class HandoffContract:
    """The complete contract produced for Codex consumption."""

    # Protocol identity
    rq3_protocol_sha: str = ""
    rq3_protocol_version: str = "RQ3_PROTOCOL_FREEZE/v1"

    # Pair receipt
    accepted_rq3_pair_receipt_sha: str = ""
    manual_capture_identity_sha: str = ""
    automatic_capture_identity_sha: str = ""

    # Source identity
    manual_arm_identity_sha: str = ""
    auto_arm_identity_sha: str = ""
    software_git_sha: str = ""
    carla_client_version: str = ""
    carla_server_version: str = ""

    # Map identity (strict)
    manual_map_identity_sha: str = ""
    auto_map_identity_sha: str = ""
    manual_map_type: str = "cooked_manual"
    auto_map_type: str = "xodr"
    requested_manual_map_name: str = "Grid0828"
    source_grid0828_xodr_sha: str = ""
    source_grid0828_cooked_sha: str = ""
    source_grid0828_runtime_sha: str = ""

    # Route identity
    route_manifest_sha: str = ""
    route_mode: str = "THESIS_PAIRED_STRICT"

    # Rig identity
    frozen_rig_sha: str = ""
    effective_rig_version: str = "RQ3_FROZEN_RIG/v1"

    # Frame-set identity
    frame_manifest_sha: str = ""
    accepted_frame_count: int = 0
    frame_set_intersection_sha: str = ""

    # Sensor mapping (frozen 29-class + ignore 255)
    rgb_semantic_mapping_sha: str = ""
    class_mapping_sha: str = ""
    ignore_class_255_policy: str = "IGNORE_255"

    # Partition metadata (meta only; Codex owns split creation)
    dataset_admission_level: str = HANDOFF_STATUS_NOT_ADMITTED
    dataset_root_roots: List[str] = field(default_factory=list)
    dataset_partition_roots: List[str] = field(default_factory=list)
    dataset_status: str = HANDOFF_STATUS_NOT_ADMITTED

    # Evidence
    source_artifact_sha: str = ""
    capture_session_manifest_sha: str = ""
    capture_session_sha: str = ""

    # Final contract identity
    handoff_contract_sha: str = ""

    # Review / independence
    independent_review_available: bool = False
    independent_review_sha: str = ""

    # Blocked dependencies
    blocked_dependency_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "schema_version": HANDOFF_SCHEMA_VERSION,
            "rq3_protocol_sha": self.rq3_protocol_sha,
            "rq3_protocol_version": self.rq3_protocol_version,
            "rq3_pair_receipt_sha": self.accepted_rq3_pair_receipt_sha,
            "manual_capture_identity_sha": self.manual_capture_identity_sha,
            "automatic_capture_identity_sha": self.automatic_capture_identity_sha,
            "manual_arm_identity_sha": self.manual_arm_identity_sha,
            "auto_arm_identity_sha": self.auto_arm_identity_sha,
            "manual_map_identity_sha": self.manual_map_identity_sha,
            "auto_map_identity_sha": self.auto_map_identity_sha,
        }
        payload["frozen_rig_sha"] = self.frozen_rig_sha
        payload["effective_rig_version"] = self.effective_rig_version
        payload["route_manifest_sha"] = self.route_manifest_sha
        payload["route_mode"] = self.route_mode
        payload["manual_map_type"] = self.manual_map_type
        payload["auto_map_type"] = self.auto_map_type
        payload["requested_manual_map_name"] = self.requested_manual_map_name
        payload["frame_manifest_sha"] = self.frame_manifest_sha
        payload["frame_set_intersection_sha"] = self.frame_set_intersection_sha
        payload["accepted_frame_count"] = self.accepted_frame_count
        payload["rgb_semantic_mapping_sha"] = self.rgb_semantic_mapping_sha
        payload["class_mapping_sha"] = self.class_mapping_sha
        payload["ignore_class_255_policy"] = self.ignore_class_255_policy
        payload["dataset_admission_level"] = self.dataset_admission_level
        payload["dataset_status"] = self.dataset_status
        payload["dataset_admission_reasons"] = self.blocked_dependency_reasons
        payload["independent_review_available"] = self.independent_review_available
        payload["independent_review_sha"] = self.independent_review_sha
        payload["verified_pair_receipt_sha"] = self.accepted_rq3_pair_receipt_sha
        payload["captured_source_sha"] = self.source_artifact_sha
        payload["source_artifact_sha"] = self.source_artifact_sha
        payload["software_git_sha"] = self.software_git_sha
        payload["carla_client_version"] = self.carla_client_version
        payload["carla_server_version"] = self.carla_server_version
        payload["session_manifest_sha"] = self.capture_session_manifest_sha
        payload["session_sha"] = self.capture_session_sha
        payload["blocked_dependency_reasons"] = list(self.blocked_dependency_reasons)
        payload["partition_roots"] = list(self.dataset_partition_roots)
        payload["dataset_roots"] = list(self.dataset_root_roots)
        # Final digest
        payload["handoff_contract_sha"] = hashlib.sha256(
            json.dumps({k: v for k, v in payload.items() if k != "handoff_contract_sha"},
                       sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return payload


class ConsumerFixture:
    """A synthetic RQ5 consumer fixture demonstrating schema validation
    and rejection of an incomplete/inadmissible capture.
    """

    @staticmethod
    def synthetic_valid_fixture() -> HandoffContract:
        """A synthetic fixture clearly labeled as non-authoritative."""
        return HandoffContract(
            dataset_admission_level=HANDOFF_STATUS_INCOMPLETE,
            dataset_status=HANDOFF_STATUS_NOT_ADMITTED,
            blocked_dependency_reasons=[
                "SYNTHETIC_FIXTURE: not a live RQ3 capture",
                "SYNTHETIC_FIXTURE: dataset admission requires executed pair receipt with verified identity hashes",
            ],
        )

    @staticmethod
    def reject_incomplete_capture(contract: HandoffContract) -> bool:
        """Codex should reject if admission is not ADMITTED."""
        return contract.dataset_admission_level != HANDOFF_STATUS_ADMITTED

    @staticmethod
    def validate_schema_version(payload: Mapping[str, Any]) -> bool:
        return payload.get("schema_version") == HANDOFF_SCHEMA_VERSION

    @staticmethod
    def validate_frozen_contract_refs(payload: Mapping[str, Any]) -> bool:
        # Required identity fields must exist and not be empty
        for key in ("rq3_protocol_sha", "rq3_pair_receipt_sha", "manual_arm_identity_sha",
                    "auto_arm_identity_sha", "manual_map_identity_sha",
                    "auto_map_identity_sha", "frozen_rig_sha", "route_manifest_sha"):
            value = payload.get(key)
            if value is None or str(value).strip() == "":
                return False
        return True


def build_current_handoff_report(
    *,
    pair_manifest_sha: str = "",
    manual_arm_sha: str = "",
    auto_arm_sha: str = "",
    frame_manifest_sha: str = "",
    session_sha: str = "",
    dataset_admission_level: str = HANDOFF_STATUS_NOT_ADMITTED,
    blocked_reasons: Optional[Sequence[str]] = None,
) -> HandoffContract:
    """Produce the canonical Phase 6 handoff from current evidence."""
    blocked = list(blocked_reasons) if blocked_reasons else []
    # From the hardware inventory and evidence: server is not running,
    # no live pair receipt exists, shader-fatal remains unresolved,
    # storage gate not met.
    blocked.extend([
        "CARLA_SERVER_NOT_RUNNING",
        "SHADER_FATAL_AT_BOOT: Quadro P3200, driver 573.22",
        "LARGEMAP_AV: Grid0828 load_world AV (3 minidumps: C8805F33, 9D5399CA, 87F1B2AC)",
        "STORAGE_ADMISSION_BLOCKED: no volume >= 20 GiB",
        "PYTHON312_ISOLATION_BLOCKED: E: 4.16 GiB free",
    ])
    return HandoffContract(
        rq3_protocol_sha="RQ3_PROTOCOL_FREEZE/v1",
        accepted_rq3_pair_receipt_sha=pair_manifest_sha if pair_manifest_sha else "",
        manual_capture_identity_sha=manual_arm_sha,
        automatic_capture_identity_sha=auto_arm_sha,
        manual_arm_identity_sha=manual_arm_sha,
        auto_arm_identity_sha=auto_arm_sha,
        manual_map_identity_sha="370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8",
        auto_map_identity_sha="",
        manual_map_type="cooked_manual",
        auto_map_type="xodr",
        requested_manual_map_name="Grid0828",
        route_manifest_sha="/reference/route/ingolstadt_v1.json",
        route_mode="THESIS_PAIRED_STRICT",
        frozen_rig_sha="RQ3_FROZEN_RIG/v1",
        effective_rig_version="RQ3_FROZEN_RIG/v1",
        frame_manifest_sha=frame_manifest_sha,
        frame_set_intersection_sha="",
        dataset_admission_level=dataset_admission_level,
        dataset_status=HANDOFF_STATUS_NOT_ADMITTED,
        dataset_root_roots=[],
        dataset_partition_roots=[],
        source_artifact_sha="370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8",
        capture_session_manifest_sha=session_sha,
        software_git_sha="363a1868455cab0c33ce9584d6f4b09d594f74e3",
        carla_client_version="carla-0.9.16-cp312",
        carla_server_version="unavailable (no server running)",
        rgb_semantic_mapping_sha="RQ3_CLASS_MAP_29/v1",
        class_mapping_sha="RQ3_CLASS_MAP_29/v1",
        ignore_class_255_policy="IGNORE_255",
        blocked_dependency_reasons=blocked,
        independent_review_available=False,
        independent_review_sha="",
    )


if __name__ == "__main__":
    contract = build_current_handoff_report()
    payload = contract.to_dict()
    with open("E:/wt/repair-map-realism-p0-837a8504/reports/phase5_deliverables/RQ3_TO_RQ5_HANDOFF_CONTRACT.json", "w") as f:
        json.dump(payload, f, indent=2)
    print("Wrote RQ3_TO_RQ5_HANDOFF_CONTRACT.json")
    print(f"Status: {payload['dataset_status']}")
    print(f"Blocked reasons ({len(payload['blocked_dependency_reasons'])}): {payload['blocked_dependency_reasons']}")
