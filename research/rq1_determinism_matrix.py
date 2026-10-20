# -*- coding: utf-8 -*-
"""Five-run identity comparator for RQ1 determinism evidence.

Compares, per run (identity fields read from the rq1_run_receipt/v2 child
receipts; wrapper receipts never trusted for scientific identity):

  * input identity (pinned XODR path + sha256, OSM/buildings sha)
  * raw XODR SHA256
  * canonical normalized XODR SHA256 (rq1-xodr-normalization/v1)
  * structural signature (rq1-structural-signature/v1)
  * tileset digest / map-acceptance digest / final receipt digest
  * settings digest and governed environment identity

Classifications (first match wins;, documented in
``divergence_classification``):

  RAW_DIFFERENT_NORMALIZED_EQUAL
      byte-level nondeterminism is purely non-semantic serialization.
  NORMALIZED_DIFFERENT_STRUCTURAL_EQUAL
      normalized numeric/order representation variation (or a
      structure-excluded change, see rq1_structural_signature exclusions).
  STRUCTURAL_DIFFERENCE
      true structural nondeterminism.
  NO_DIFFERENCE
      deterministic under the measured contract.

The comparator never hides mismatches: any missing/null identity or
invalid/duplicate-agreement run makes the matrix carry explicit
``identity_gaps`` entries.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

IDENTITY_FIELDS = [
    ("input_identity", "input_identity"),
    ("raw_xodr_sha256", "xodr_sha256"),
    ("normalized_xodr_sha256", "normalized_xodr_sha256"),
    ("structural_signature", "structural_signature"),
    ("tileset_digest", "tileset_digest"),
    ("map_acceptance_digest", "map_acceptance_digest"),
    ("final_receipt_digest", "final_receipt_digest"),
    ("settings_digest", "settings_digest"),
]


def _child_receipt(receipt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    child = receipt.get("child_receipt")
    if isinstance(child, dict) and child.get("schema") == "rq1_run_receipt/v2":
        return child
    return None


def _valid(child: Optional[Dict[str, Any]], receipt: Dict[str, Any]) -> bool:
    if child is None:
        return False
    validations = [
        receipt.get("return_code") == 0,
        not receipt.get("timed_out"),
        child.get("status") == "ok",
    ]
    required_fields = [
        "input_sha256",
        "xodr_sha256",
        "normalized_xodr_sha256",
        "structural_signature",
        "settings_digest",
    ]
    return all(validations) and all(child.get(f) for f in required_fields)


def _identities(child: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    toplevel: Dict[str, Any] = {
        "xodr_sha256": child.get("xodr_sha256"),
        "normalized_xodr_sha256": child.get("normalized_xodr_sha256"),
        "structural_signature": child.get("structural_signature"),
        "tileset_digest": child.get("tileset_digest"),
        "map_acceptance_digest": child.get("map_acceptance_digest"),
        "final_receipt_digest": child.get("final_receipt_digest"),
        "settings_digest": child.get("settings_digest"),
    }
    toplevel["input_identity"] = {
        "input_xodr_path": child.get("input_xodr"),
        "input_xodr_sha256": child.get("input_sha256"),
        "osm": (child.get("inputs_record") or {}).get("OSM", {}).get("sha256"),
        "buildings": (child.get("inputs_record") or {}).get("BUILDINGS", {}).get("sha256"),
        "effective_env_governed": (child.get("effective_env") or {}).get("governed"),
    }
    for name, key in [
        ("raw_xodr_sha256", "xodr_sha256"),
        ("normalized_xodr_sha256", "normalized_xodr_sha256"),
        ("structural_signature", "structural_signature"),
        ("tileset_digest", "tileset_digest"),
        ("map_acceptance_digest", "map_acceptance_digest"),
        ("final_receipt_digest", "final_receipt_digest"),
        ("settings_digest", "settings_digest"),
        ("input_identity", "input_identity"),
    ]:
        out[name] = toplevel[key]
    return out


def build_determinism_matrix(receipts: List[Dict[str, Any]], *, valid_run_count: int) -> Dict[str, Any]:
    child_receipts: List[Optional[Dict[str, Any]]] = [_child_receipt(r) for r in receipts]
    valid_flags = [
        _valid(c, r) if c is not None else False for c, r in zip(child_receipts, receipts)
    ]
    valid_children = [c for c, ok in zip(child_receipts, valid_flags) if ok]

    per_run: List[Dict[str, Any]] = []
    for idx, (r, c) in enumerate(zip(receipts, child_receipts)):
        per_run.append(
            {
                "run": r.get("run_index", idx),
                "run_id": r.get("run_id"),
                "wrapper_return_code": r.get("return_code"),
                "wrapper_timed_out": r.get("timed_out"),
                "valid": bool(c is not None and valid_flags[idx]),
                "status": (c or {}).get("status"),
                "identities": _identities(c) if c else None,
            }
        )

    all_raw_equal = all_normalized_equal = all_structural_equal = False
    first_divergent_stage: Optional[str] = None
    divergence: Optional[str] = None
    identity_gaps: List[Dict[str, Any]] = []

    raw_values = {c.get("xodr_sha256") for c in valid_children}
    normalized_values = {c.get("normalized_xodr_sha256") for c in valid_children}
    structural_values = {c.get("structural_signature") for c in valid_children}

    if valid_children:
        all_raw_equal = len(raw_values) == 1
        all_normalized_equal = len(normalized_values) == 1
        all_structural_equal = len(structural_values) == 1

        # First divergent stage in pipeline order (most-constrained last:
        # structure is the final identity stage).
        stages = [
            ("raw_xodr_sha256", all_raw_equal),
            ("normalized_xodr_sha256", all_normalized_equal),
            ("structural_signature", all_structural_equal),
        ]
        for stage, equal in stages:
            if not equal:
                first_divergent_stage = stage
                break

        if not all_raw_equal and all_normalized_equal and all_structural_equal:
            divergence = "RAW_DIFFERENT_NORMALIZED_EQUAL"
        elif not all_normalized_equal and all_structural_equal:
            divergence = "NORMALIZED_DIFFERENT_STRUCTURAL_EQUAL"
        elif not all_structural_equal:
            divergence = "STRUCTURAL_DIFFERENCE"
        else:
            divergence = "NO_DIFFERENCE"

        # Explicit gaps for any measured identity whose values disagree.
        for name in _IDENTITY_KEYS:
            values = {c.get(name) for c in valid_children}
            if len(values) > 1 or None in values:
                identity_gaps.append(
                    {
                        "identity": name,
                        "distinct_values": sorted(str(v) for v in values),
                        "distinct_count": len(values),
                    }
                )

    if divergence is None:
        divergence = "NOT_RUN" if not valid_children else divergence

    return {
        "schema": "rq1_full_determinism_matrix/v1",
        "run_count": len(receipts),
        "valid_run_count": sum(1 for p in per_run if p["valid"]),
        "all_raw_equal": all_raw_equal,
        "all_normalized_equal": all_normalized_equal,
        "all_structural_equal": all_structural_equal,
        "first_divergent_stage": first_divergent_stage,
        "divergence_classification": divergence,
        "identity_gaps": identity_gaps,
        "per_run": per_run,
    }


_IDENTITY_KEYS = [
    "input_identity",
    "raw_xodr_sha256",
    "normalized_xodr_sha256",
    "structural_signature",
    "tileset_digest",
    "map_acceptance_digest",
    "final_receipt_digest",
    "settings_digest",
]


def _field_key(name: str) -> str:
    lookup = {
        "input_identity": "input_identity",
        "raw_xodr_sha256": "xodr_sha256",
        "normalized_xodr_sha256": "normalized_xodr_sha256",
        "structural_signature": "structural_signature",
        "tileset_digest": "tileset_digest",
        "map_acceptance_digest": "map_acceptance_digest",
        "final_receipt_digest": "final_receipt_digest",
        "settings_digest": "settings_digest",
    }
    return lookup[name]
