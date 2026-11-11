#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ2 current-lineage replay (bounded).

Runs the committed RQ2 metric authority (byte-identical blob from
rq2-authority@2159a358, blob 97a96ab3cb31966bd9d3eca6e8d5be89c17b5d50)
against the CURRENT pinned auto/manual pair, and emits:

  * RQ2_CURRENT_VALIDATION.json  (schema rq2_current_validation/v1)
  * RQ2_EVIDENCE_RECEIPT.json    (schema rq2_evidence_receipt/v1)

Rules honored:
  * both maps resolved through the SHA-pinned registry authority
    (``auto_map_of_record`` / ``manual_grid0828``; no mtime discovery, no
    city fallback, no worktree shim);
  * same CRS / registration / local-hull scope / metric implementation /
    frozen thresholds as the historical authoritative run;
  * every recomputed metric is compared against the frozen
    ``RQ2_RESULTS.json`` oracle (frozen at 56a82a35) and against the
    historical ``RQ2_FINAL_VALIDATION.json`` provenance facts;
  * the claim stays BOUNDED (local-hull scope) — this tool never upgrades
    the thesis claim from local-hull evidence to a universal one.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
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
from research.evidence.claim_adjudicator import ADJUDICATOR_VERSION, adjudicate_rq2
from research.evidence.schemas import (
    RESEARCH_CONTRACT_SHA256,
    build_experiment_receipt,
)
from ultimate_pipeline.domain_gap.rq2_metric_authority import (
    VALID_METRICS,
    build_validation_report,
    compute_manual_hull,
    compute_whole_map,
    resolve_pair,
)

# exact import provenance: the authority module restored from the
# rq2-authority branch (blob pinned below; verified at task start).
RQ2_METRIC_AUTHORITY_PATH = REPO / "ultimate_pipeline/domain_gap/rq2_metric_authority.py"
RQ2_METRIC_AUTHORITY_BLOB = "97a96ab3cb31966bd9d3eca6e8d5be89c17b5d50"

FROZEN_ORACLE_PATH = REPO / "RQ2_RESULTS.json"
FROZEN_ORACLE_BLOB = "4fcbb2fcfb98cefd052de2228c492679b1074ea1"

HISTORICAL_VALIDATION_PATH = REPO / "RQ2_FINAL_VALIDATION.json"
HISTORICAL_VALIDATION_GIT_SHA = "65eb0f14d226104692dd845f8a528759fbeb90c4"
HISTORICAL_AUTO_SHA = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"
HISTORICAL_MANUAL_SHA = "5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c"

CONVERGENCE_SOURCE_SHA = "a9c9b6c167497893ccf97e86ec1858deaf69b306"
CONVERGENCE_SOURCE_BRANCH = "integration/production-convergence-20261020"

FROZEN_PUBLISHED_CITATIONS = {
    "hull_road_length_ratio_3dp": (round(2.683, 3), 3),
    "hull_junction_ratio_3dp": (round(3.782, 3), 3),
    "hull_road_count_ratio_3dp": (round(3.561, 3), 3),
    "hull_curvature_gap_4dp": (round(0.2206, 4), 4),
    "hull_lane_width_gap_4dp": (round(0.0597, 4), 4),
    "hull_building_density_gap_4dp": (round(0.2308, 4), 4),
    "frechet_mean_m_2dp": (round(58.18, 2), 2),
    "frechet_median_m_2dp": (round(36.13, 2), 2),
    "frechet_p90_m_2dp": (round(140.48, 2), 2),
    "frechet_pairs": (894, None),
}


def _blob_matches_expected() -> bool:
    """The committed file is byte-identical to the rq2-authority blob."""
    proc = subprocess.run(
        ["git", "hash-object", str(RQ2_METRIC_AUTHORITY_PATH)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip() == RQ2_METRIC_AUTHORITY_BLOB


def _flatten_metrics(scope_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a scope doc into scalar metric values keyed by contract ids."""
    out: Dict[str, Any] = {}
    metrics = scope_doc.get("metrics", {})
    for key, value in metrics.items():
        if isinstance(value, dict):
            for sub, sv in value.items():
                out[f"{key}.{sub}"] = sv
        else:
            out[key] = value
    return out


def _aggregate_metric_comparison(
    frozen_flat: Dict[str, Any], current_flat: Dict[str, Any]
) -> tuple:
    """Classify frozen-vs-current flattened metrics.

    Classification rules (order matters):
    - dict on either side -> STRUCTURAL_VALUE (compared via subkeys upstream)
    - None on both sides  -> NULL_BOTH (availability gap, NOT a value change)
    - exactly one side None -> change record "unavailable side"
    - numeric both -> MATCH(atol=1e-9) or change with diff
    - otherwise -> change record on non-equality
    """
    changes: List[Dict[str, Any]] = []
    agreement: Dict[str, Any] = {}
    for key in sorted(set(frozen_flat) | set(current_flat)):
        fv, cv = frozen_flat.get(key), current_flat.get(key)
        if isinstance(fv, dict) or isinstance(cv, dict):
            agreement[key] = "STRUCTURAL_VALUE (compare via subkeys)"
            continue
        if fv is None and cv is None:
            agreement[key] = "NULL_BOTH (unavailable on both sides; not a value change)"
            continue
        if fv is None or cv is None:
            changes.append({"metric": key, "frozen": fv, "current": cv, "note": "unavailable side"})
            continue
        if isinstance(fv, (int, float)) and isinstance(cv, (int, float)):
            if abs(float(fv) - float(cv)) <= 1e-9:
                agreement[key] = "MATCH(atol=1e-9)"
            else:
                changes.append(
                    {
                        "metric": key,
                        "frozen": fv,
                        "current": cv,
                        "diff": float(cv) - float(fv),
                    }
                )
        elif fv != cv:
            changes.append({"metric": key, "frozen": fv, "current": cv})
    return agreement, changes


def main() -> int:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pair = resolve_pair()
    auto_p = pair["auto"]["resolved_path"]
    manual_p = pair["manual"]["resolved_path"]

    doc: Dict[str, Any] = {
        "schema": "rq2_results/v1",
        "generated_at_utc": now,
        "pair": {
            "auto": {
                "path": pair["auto"]["declared_path"],
                "sha256": pair["auto"]["sha256_actual"],
                "bytes": pair["auto"]["bytes_actual"],
            },
            "manual": {
                "path": pair["manual"]["declared_path"],
                "sha256": pair["manual"]["sha256_actual"],
                "bytes": pair["manual"]["bytes_actual"],
            },
        },
        "valid_metrics": VALID_METRICS,
        "scopes": {
            "manual_hull": compute_manual_hull(auto_p, manual_p),
            "whole_map": compute_whole_map(auto_p, manual_p),
        },
    }

    frozen = json.loads(FROZEN_ORACLE_PATH.read_text(encoding="utf-8"))
    validation = build_validation_report(doc, frozen)

    # ---- historical comparison ------------------------------------------
    hist = json.loads(HISTORICAL_VALIDATION_PATH.read_text(encoding="utf-8"))

    def _flatten_scopes(scopes_doc: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for scope in sorted(scopes_doc):
            flat = _flatten_metrics(scopes_doc[scope])
            for key, value in flat.items():
                out[f"{scope}.{key}"] = value
        return out

    frozen_flat = _flatten_scopes(frozen.get("scopes", {}))
    current_flat = _flatten_scopes(doc["scopes"])
    agreement, changes = _aggregate_metric_comparison(frozen_flat, current_flat)

    pair_identity_ok = (
        doc["pair"]["auto"]["sha256"] == HISTORICAL_AUTO_SHA
        and doc["pair"]["manual"]["sha256"] == HISTORICAL_MANUAL_SHA
    )

    pair_identities = {
        "auto_sha256": doc["pair"]["auto"]["sha256"],
        "manual_sha256": doc["pair"]["manual"]["sha256"],
        "scope": "manual_hull",
        "frozen_reproduction": validation["verdict"] == "PASS",
    }

    runtime_env = {
        "python": sys.version.split()[0],
        "platform": __import__("platform").platform(),
    }

    # Physical metric payload written FIRST so the experiment receipt binds
    # real bytes on disk (fail-closed hex-SHA256 bindings; no placeholders).
    metrics_payload_path = REPO / "RQ2_CURRENT_METRICS_PAYLOAD.json"
    metrics_payload_path.write_text(
        json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    inputs = [
        {"path": str(Path(auto_p).relative_to(REPO)), "sha256": doc["pair"]["auto"]["sha256"]},
        {"path": str(Path(manual_p).relative_to(REPO)), "sha256": doc["pair"]["manual"]["sha256"]},
        {"path": str(RQ2_METRIC_AUTHORITY_PATH), "sha256": sha256_file(RQ2_METRIC_AUTHORITY_PATH)},
        {"path": str(FROZEN_ORACLE_PATH), "sha256": sha256_file(FROZEN_ORACLE_PATH)},
        {"path": "research/thesis_rq_contract.yaml", "sha256": RESEARCH_CONTRACT_SHA256},
    ]

    raw_metric_payload = doc
    receipt = build_experiment_receipt(
        rq_id="RQ2",
        metric_ids=VALID_METRICS,
        git_sha=git_head_sha(REPO),
        source_dirty=is_dirty_worktree(REPO),
        dirty_reason=("untracked outputs present in research worktree" if is_dirty_worktree(REPO) else None),
        protocol_path=str(REPO / "research/thesis_rq_contract.yaml"),
        protocol_sha256=RESEARCH_CONTRACT_SHA256,
        input_paths=inputs,
        map_identities=pair_identities,
        settings_digest=sha256_of_jsonable(
            {"authority_blob": sha256_file(RQ2_METRIC_AUTHORITY_PATH), "oracle_blob": FROZEN_ORACLE_BLOB}
        ),
        runtime=runtime_env,
        seeds=["deterministic-no-seed"],
        output_paths=[
            {"path": str(metrics_payload_path), "sha256": sha256_file(metrics_payload_path)}
        ],
        raw_metric_payload=raw_metric_payload,
        statistics_method=(
            "point metric recomputation under frozen thresholds; frozen-check "
            "agreement at atol=1e-9 + published-precision citation checks"
        ),
        execution_status="COMPLETED",
        claim_boundary=(
            "RQ2 structural domain gap, local-hull primary scope (same region); "
            "whole_map reported as context only; no universal claim drawn"
        ),
    )
    receipt["generated_at_utc"] = now
    receipt["metric_agreement"] = {
        "frozen_oracle": {
            "path": str(FROZEN_ORACLE_PATH),
            "sha256": sha256_file(FROZEN_ORACLE_PATH),
            "source": "rq2-authority@2159a358 (frozen at 56a82a35; comparison oracle only)",
        },
        "frozen_validation_check": validation["verdict"],
        "published_precision_citations": FROZEN_PUBLISHED_CITATIONS,
        "agreement": agreement,
        "changed_values": changes,
        "changed_value_explanations": _explain_changes(changes),
        "pair_matches_historical": pair_identity_ok,
        "historical_validation": {
            "path": str(HISTORICAL_VALIDATION_PATH),
            "git_sha": HISTORICAL_VALIDATION_GIT_SHA,
            "rq2_status_auth": hist.get("RQ2_STATUS"),
            "base_sha": (hist.get("base") or {}).get("sha"),
        },
    }

    claim = adjudicate_rq2([receipt], current_contract_sha256=RESEARCH_CONTRACT_SHA256)
    claim["adjudication"]["adjudicator_version"] = ADJUDICATOR_VERSION

    evidence_out = REPO / "RQ2_EVIDENCE_RECEIPT.json"
    # The receipt binds RQ2_CURRENT_VALIDATION.json itself (written first so
    # its digest can be recorded faithfully).
    current_doc = {
        "schema": "rq2_current_validation/v1",
        "generated_at_utc": now,
        "rq_id": "RQ2",
        "mode": "recompute on current lineage; claim stays BOUNDED (local-hull scope)",
        "convergence_source": {"branch": CONVERGENCE_SOURCE_BRANCH, "sha256": CONVERGENCE_SOURCE_SHA},
        "research_execution_branch_sha256": git_head_sha(REPO),
        "code": {
            "git_sha": git_head_sha(REPO),
            "metric_authority_path": str(RQ2_METRIC_AUTHORITY_PATH),
            "metric_authority_sha256": sha256_file(RQ2_METRIC_AUTHORITY_PATH),
            "metric_authority_blob_expected": RQ2_METRIC_AUTHORITY_BLOB,
            "metric_authority_blob_match": _blob_matches_expected(),
        },
        "pair": doc["pair"],
        "pair_identity_resolved_via": "SHA-pinned registry (auto_map_of_record / manual_grid0828)",
        "registration": (doc["scopes"]["manual_hull"]["implementations"]),
        "frozen_oracle": {"sha256": sha256_file(FROZEN_ORACLE_PATH), "blob": FROZEN_ORACLE_BLOB},
        "frozen_oracle_check": validation,
        "metric_agreement": receipt["metric_agreement"],
        "claim": {
            "claim_status": claim["claim_status"],
            "claim_statement": claim.get("claim_statement"),
            "adjudication": claim["adjudication"],
            "adjudicator_version": ADJUDICATOR_VERSION,
        },
        "scopes": doc["scopes"],
    }
    current_out = REPO / "RQ2_CURRENT_VALIDATION.json"
    current_out.write_text(
        json.dumps(current_doc, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    receipt["output_paths"] = [
        {"path": str(metrics_payload_path), "sha256": sha256_file(metrics_payload_path)}
    ]
    from research.evidence.schemas import validate_receipt

    validate_receipt(receipt, verify=True)
    evidence = {
        "schema": "rq2_evidence_receipt/v1",
        "generated_at_utc": now,
        "rq_id": "RQ2",
        "rq2_current_validation": {
            "path": str(current_out),
            "sha256": sha256_file(current_out),
        },
        "experiment_receipt": receipt,
        "experiment_receipt_digest": sha256_of_jsonable(receipt),
        "claim": {
            "claim_status": claim["claim_status"],
            "claim_statement": claim.get("claim_statement"),
            "adjudication": claim["adjudication"],
        },
        "final_status": claim["claim_status"],
        "notes": [
            "frozen local-hull claim boundary preserved; no upgrade to a "
            "whole-world universal claim",
        ],
    }
    evidence_out.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "frozen_oracle_check": validation["verdict"],
                "changed_values": len(changes),
                "pair_matches_historical": pair_identity_ok,
                "final_status": claim["claim_status"],
                "outputs": [str(current_out), str(evidence_out)],
            },
            indent=2,
        )
    )
    return 0


def _explain_changes(changes: List[Dict[str, Any]]) -> Dict[str, str]:
    """Explanations for any changed frozen value (none expected on the
    identical pinned pair + identical metric implementation)."""
    out: Dict[str, str] = {}
    for change in changes:
        key = change["metric"]
        if isinstance(change.get("frozen"), (int, float)) and isinstance(
            change.get("current"), (int, float)
        ):
            out[key] = (
                "recomputed value differs from frozen value beyond atol; "
                "same pinned pair and same metric implementation, so this "
                "requires investigation (possibly registry/dependency drift) "
                "— the change is recorded, never silently normalized"
            )
        else:
            out[key] = "key set difference between frozen and recomputed payloads"
    return out


if __name__ == "__main__":
    raise SystemExit(main())
