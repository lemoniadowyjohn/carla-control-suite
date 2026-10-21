#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the governed RQ1 evidence receipt from the five-run campaign.

Binds (rq1_evidence_receipt/v1):
  * convergence/source SHA (integration/production-convergence-20261020 tip)
  * research execution SHA (HEAD of this research branch)
  * RQ contract SHA
  * RQ1 normalization version + rules hash
  * all five run receipt hashes
  * final comparison matrix hash
  * final adjudicated status

The claim status is produced by the research claim adjudicator ONLY; the
assembler never upgrades a claim by itself.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.evidence.canonical import (
    git_head_sha,
    is_dirty_worktree,
    sha256_file,
    sha256_of_jsonable,
)
from research.evidence.claim_adjudicator import ADJUDICATOR_VERSION, adjudicate_rq1
from research.evidence.schemas import (
    RESEARCH_CONTRACT_SHA256,
    build_experiment_receipt,
    load_claim_statuses,
)
from research.rq1_normalization import NORMALIZATION_VERSION, normalization_rules

CONVERGENCE_SOURCE_SHA = "a9c9b6c167497893ccf97e86ec1858deaf69b306"
CONVERGENCE_SOURCE_BRANCH = "integration/production-convergence-20261020"

RQ1_FROZEN_METRIC_IDS = [
    "raw_hash_repeatability",
    "normalized_hash_repeatability",
    "structural_signature_repeatability",
    "byte_nondeterminism_source",
]

STATISTICS_METHOD = (
    "exact identity comparison: five isolated cold runs at equal pinned "
    "inputs compared field-by-field via the five-run determinism matrix "
    "(no sampling statistics involved)"
)

CLAIM_BOUNDARY = (
    "RQ1 determinism measured on the pinned ingolstadt OSM->OpenDRIVE "
    "lineage in offline (UP_OFFLINE_ONLY) mode on Windows; classified "
    "byte_nondeterminism_source per the five-run comparator"
)


def _runtime_identity() -> Dict[str, Any]:
    import xml.etree.ElementTree  # noqa: F401  (stdlib parse backend identity)

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "xml_backend": "stdlib xml.etree.ElementTree (deterministic parse/serialize)",
        "xml_backend_version": __import__("sys").hexversion,
    }


def _protocol_bindings() -> Dict[str, Any]:
    protocol_files = {
        "research/thesis_rq_contract.yaml": REPO / "research/thesis_rq_contract.yaml",
        "docs/research/EXPERIMENT_PROTOCOLS.md": REPO
        / "docs/research/EXPERIMENT_PROTOCOLS.md",
        "configs/rq5_protocol_freeze_v1.json": REPO
        / "configs/rq5_protocol_freeze_v1.json",
    }
    out = {}
    for rel, p in protocol_files.items():
        out[rel] = {"path": str(p), "sha256": sha256_file(p)}
    return out


def build_artifact(path: Path) -> Dict[str, str]:
    return {"path": str(path), "sha256": sha256_file(path)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble RQ1 evidence receipt")
    ap.add_argument("--matrix", type=Path, default=REPO / "reports/rq1b_runs/RQ1_FULL_DETERMINISM_MATRIX.json")
    ap.add_argument("--runs-base", type=Path, default=REPO / "reports/rq1b_runs")
    ap.add_argument("--out", type=Path, default=REPO / "RQ1_EVIDENCE_RECEIPT.json")
    args = ap.parse_args()

    full_matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    determinism: Dict[str, Any] = full_matrix["determinism"]
    wrappers: List[Dict[str, Any]] = full_matrix["receipts"]

    protocol_bindings = _protocol_bindings()
    contract_binding = protocol_bindings["research/thesis_rq_contract.yaml"]

    # ---- one experiment receipt per valid run --------------------------------
    run_receipts: List[Dict[str, Any]] = []
    run_receipt_hashes: List[Dict[str, str]] = []
    claim_reusable: Dict[str, Any] = {}
    for wrapper in wrappers:
        child = wrapper.get("child_receipt") or {}
        if not (wrapper.get("return_code") == 0 and child.get("status") == "ok"):
            continue
        execution_status = "COMPLETED"
        seeds = ["deterministic-no-seed"]
        git_sha = child.get("git_sha") or git_head_sha(REPO)
        dirty = bool(child.get("source_dirty", is_dirty_worktree(REPO)))

        inputs = [
            {
                "path": child.get("input_xodr", ""),
                "sha256": child.get("input_sha256", ""),
            }
        ]
        for label, rec in (child.get("inputs_record") or {}).items():
            if rec.get("sha256"):
                inputs.append({"path": rec["path"], "sha256": rec["sha256"], "role": label})

        outputs: List[Dict[str, str]] = []
        receipt_path = wrapper.get("child_receipt_path") or ""
        if receipt_path:
            outputs.append(build_artifact(Path(receipt_path)))
        meta = child.get("structural_meta") or {}
        if meta.get("payload_path"):
            outputs.append(build_artifact(Path(meta["payload_path"])))
        ma = child.get("map_acceptance") or {}
        final_xodr_path = ma.get("final_xodr_path")
        final_disk = (
            Path(final_xodr_path)
            if final_xodr_path and Path(final_xodr_path).is_file()
            else None
        )
        if final_disk is None:
            out_dir_c = Path(child.get("out_dir") or "")
            candidates = sorted(out_dir_c.rglob("*.xodr")) if out_dir_c.is_dir() else []
            final_disk = candidates[-1] if candidates else None
        if final_disk is not None and final_disk.is_file():
            outputs.append(build_artifact(final_disk))

        raw_metric_payload = {
            "run_index": child.get("run"),
            "identities": {
                "input_sha256": child.get("input_sha256"),
                "xodr_sha256": child.get("xodr_sha256"),
                "normalized_xodr_sha256": child.get("normalized_xodr_sha256"),
                "structural_signature": child.get("structural_signature"),
                "tileset_digest": child.get("tileset_digest"),
                "map_acceptance_digest": child.get("map_acceptance_digest"),
                "final_receipt_digest": child.get("final_receipt_digest"),
            },
            "feature_counts": child.get("feature_counts"),
            "topology_counts": child.get("topology_counts"),
        }

        receipt = build_experiment_receipt(
            rq_id="RQ1",
            metric_ids=RQ1_FROZEN_METRIC_IDS,
            git_sha=git_sha,
            source_dirty=dirty,
            dirty_reason=(f"in-research-branch worktree: {dirty}" if dirty else None),
            protocol_path=contract_binding["path"],
            protocol_sha256=contract_binding["sha256"],
            input_paths=inputs,
            map_identities={
                "auto_map_of_record_sha256": child.get("input_sha256"),
                "final_xodr_sha256": child.get("xodr_sha256"),
                "normalized_xodr_sha256": child.get("normalized_xodr_sha256"),
                "structural_signature_sha256": child.get("structural_signature"),
                "determinism_classification": determinism.get(
                    "divergence_classification"
                ),
                "frozen_reproduction": True,
            },
            settings_digest=child.get("settings_digest", ""),
            runtime=_runtime_identity(),
            seeds=seeds,
            output_paths=outputs,
            raw_metric_payload=raw_metric_payload,
            statistics_method=STATISTICS_METHOD,
            execution_status=execution_status,
            claim_boundary=CLAIM_BOUNDARY,
        )
        receipt["generated_at_utc"] = wrapper.get("generated_at_utc")
        run_receipts.append(receipt)
        run_receipt_hashes.append(
            {
                "run": str(child.get("run")),
                "wrapper_receipt_sha256": sha256_of_jsonable(wrapper),
                "child_receipt_path": receipt_path,
                "child_receipt_digest": sha256_of_jsonable(child),
            }
        )

    claim = adjudicate_rq1(
        run_receipts, determinism, current_contract_sha256=RESEARCH_CONTRACT_SHA256
    )
    claim["adjudication"]["adjudicator_version"] = ADJUDICATOR_VERSION

    evidence = {
        "schema": "rq1_evidence_receipt/v1",
        "generated_at_utc": full_matrix.get("generated_at_utc"),
        "rq_id": "RQ1",
        "convergence_source": {
            "branch": CONVERGENCE_SOURCE_BRANCH,
            "sha256": CONVERGENCE_SOURCE_SHA,
        },
        "research_execution": {
            "branch": "research/rq1-rq2-evidence-closure-20261020",
            "sha256": git_head_sha(REPO),
            "source_dirty": is_dirty_worktree(REPO),
        },
        "rq_contract_sha256": RESEARCH_CONTRACT_SHA256,
        "protocol_bindings": protocol_bindings,
        "normalization": {
            "version": NORMALIZATION_VERSION,
            "rules": normalization_rules(),
            "rules_hash": sha256_of_jsonable(normalization_rules()),
        },
        "run_receipts": run_receipt_hashes,
        "five_run_matrix": {
            "path": str(args.matrix),
            "sha256": sha256_file(args.matrix),
        },
        "determinism_summary": {
            "run_count": determinism.get("run_count"),
            "valid_run_count": determinism.get("valid_run_count"),
            "all_raw_equal": determinism.get("all_raw_equal"),
            "all_normalized_equal": determinism.get("all_normalized_equal"),
            "all_structural_equal": determinism.get("all_structural_equal"),
            "first_divergent_stage": determinism.get("first_divergent_stage"),
            "divergence_classification": determinism.get("divergence_classification"),
        },
        "adjudication": claim["adjudication"],
        "final_status": claim["claim_status"],
        "claim_statement": claim.get("claim_statement"),
        "statistics_method": STATISTICS_METHOD,
    }
    args.out.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"final_status": evidence["final_status"], "out": str(args.out)}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
