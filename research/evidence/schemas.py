# -*- coding: utf-8 -*-
"""Schemas for research evidence receipts (authority layer, no metrics).

Three receipt kinds, all hashed canonically:

``ResearchExperimentReceipt`` (schema ``rq_experiment_receipt/v1``)
    Binds ONE governed experiment execution: RQ id, metric ids, exact git
    SHA, dirty/clean status, protocol path + SHA256, input paths + SHA256,
    map/XODR identities, settings digest, runtime/environment identity,
    seeds, output artifact paths + SHA256, raw metric payload SHA256,
    statistics method, execution status and an explicit claim boundary.

``ResearchClaimReceipt`` (schema ``rq_claim_receipt/v1``)
    The adjudicated claim for one research question.  ``claim_status`` MUST
    be one of the statuses defined in ``research/thesis_rq_contract.yaml``.

``ResearchClosureMatrix`` (schema ``rq_closure_matrix/v1``)
    RQ -> claim receipt digest mapping used by the closure gate.

Fail-closed rules:
  * unknown / free-form claim status -> invalid receipt;
  * missing protocol/input/output bindings -> invalid receipt;
  * every relative artifact path is resolved against the repo root and the
    recorded SHA256 must match the bytes on disk when validated.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from research.evidence.canonical import sha256_file, sha256_of_jsonable

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "research" / "thesis_rq_contract.yaml"

RESEARCH_CONTRACT_SHA256_FALLBACK = ""

CLAIM_STATUSES_FALLBACK = [
    "AUTHORITATIVE",
    "BOUNDED",
    "PROTOTYPE",
    "DEFERRED_RUNTIME",
    "DEFERRED_EXTERNAL_DATA",
    "SUPERSEDED",
    "NOT_RUN",
]


def load_claim_statuses(contract_path: Optional[Path] = None) -> List[str]:
    """Allowed claim statuses, sourced from the frozen RQ contract.

    Parsed with a *structural* PyYAML load so range editing cannot sneak a
    new status in without an actual contract change on disk (the contract
    SHA256 is carried in every receipt via RESEARCH_CONTRACT_SHA256).
    """
    path = Path(contract_path) if contract_path else CONTRACT_PATH
    try:
        import yaml  # runtime optional dependency

        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        statuses = doc.get("statuses")
        if not isinstance(statuses, list) or not statuses:
            return list(CLAIM_STATUSES_FALLBACK)
        return [str(s) for s in statuses]
    except Exception as exc:  # pragma: no cover - defensive path
        # Fail closed to the frozen fallback list, but make the fallback
        # VISIBLE: a corrupted/unreadable contract must not silently pass
        # status validation with a stale list while receipts still carry
        # the (possibly drifted) contract hash.
        print(
            f"warning: claim-status load from {path} failed ({exc!r}); "
            "using frozen fallback status list",
            file=sys.stderr,
        )
        return list(CLAIM_STATUSES_FALLBACK)


CLAIM_STATUSES: List[str] = load_claim_statuses()

RESEARCH_CONTRACT_SHA256 = (
    sha256_file(CONTRACT_PATH) if CONTRACT_PATH.is_file() else RESEARCH_CONTRACT_SHA256_FALLBACK
)

EXPERIMENT_RECEIPT_SCHEMA = "rq_experiment_receipt/v1"
CLAIM_RECEIPT_SCHEMA = "rq_claim_receipt/v1"
CLOSURE_MATRIX_SCHEMA = "rq_closure_matrix/v1"

_EXECUTION_STATUSES = {"COMPLETED", "FAILED", "TIMED_OUT", "NOT_ATTEMPTED"}

_REQUIRED_EXPERIMENT_KEYS = [
    "schema",
    "rq_id",
    "metric_ids",
    "git_sha",
    "source_dirty",
    "protocol",
    "inputs",
    "map_identities",
    "settings_digest",
    "runtime",
    "seeds",
    "outputs",
    "raw_metric_payload_sha256",
    "statistics_method",
    "execution_status",
    "claim_boundary",
    "contract_sha256",
]


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(f"invalid research receipt: {msg}")


def validate_artifact_list(entries: List[Dict[str, Any]], label: str, verify: bool) -> None:
    _require(isinstance(entries, list) and entries, f"{label} must be a non-empty list")
    for entry in entries:
        _require("path" in entry and entry["path"], f"{label} entry missing path")
        _require("sha256" in entry and entry["sha256"], f"{label} entry missing sha256")
        if verify:
            p = Path(entry["path"])
            _require(p.is_file(), f"{label} file missing on disk: {entry['path']}")
            if p.is_file():
                actual = sha256_file(p)
                _require(
                    actual == entry["sha256"],
                    f"{label} sha drift at {entry['path']}: recorded={entry['sha256']} actual={actual}",
                )


def build_experiment_receipt(
    *,
    rq_id: str,
    metric_ids: List[str],
    git_sha: str,
    source_dirty: bool,
    dirty_reason: Optional[str],
    protocol_path: str,
    protocol_sha256: str,
    input_paths: List[Dict[str, str]],
    map_identities: Dict[str, Any],
    settings_digest: str,
    runtime: Dict[str, Any],
    seeds: List[Any],
    output_paths: List[Dict[str, str]],
    raw_metric_payload: Dict[str, Any],
    statistics_method: str,
    execution_status: str,
    claim_boundary: str,
) -> Dict[str, Any]:
    """Construct *and validate* one experiment receipt.

    ``execution_status`` is machine state (COMPLETED / FAILED / ...), while
    the scientific claim remains a separate adjudication decision.
    """
    if execution_status not in _EXECUTION_STATUSES:
        raise ValueError(
            f"execution_status '{execution_status}' not in {sorted(_EXECUTION_STATUSES)}"
        )
    for name, value in (("protocol_sha256", protocol_sha256),):
        if not isinstance(value, str) or len(value) != 64 or any(
            c not in "0123456789abcdef" for c in value.lower()
        ):
            raise ValueError(f"{name} must be a hex SHA256 digest")
    if any(
        not isinstance(e.get("sha256"), str) or len(e["sha256"]) != 64
        for e in input_paths + output_paths
    ):
        raise ValueError("input/output bindings must carry hex SHA256 digests")
    if source_dirty and not dirty_reason:
        raise ValueError(
            "dirty source requires an explicit documented reason "
            "(evidence is otherwise inadmissible)"
        )
    receipt: Dict[str, Any] = {
        "schema": EXPERIMENT_RECEIPT_SCHEMA,
        "generated_at_utc": None,  # filled by caller to keep hash stable
        "rq_id": str(rq_id),
        "metric_ids": sorted(str(m) for m in metric_ids),
        "git_sha": str(git_sha),
        "source_dirty": bool(source_dirty),
        "dirty_reason": dirty_reason,
        "protocol": {"path": str(protocol_path), "sha256": str(protocol_sha256)},
        "inputs": list(input_paths),
        "map_identities": dict(map_identities),
        "settings_digest": str(settings_digest),
        "runtime": dict(runtime),
        "seeds": list(seeds),
        "outputs": list(output_paths),
        "raw_metric_payload_sha256": sha256_of_jsonable(raw_metric_payload),
        "statistics_method": str(statistics_method),
        "execution_status": execution_status,
        "claim_boundary": str(claim_boundary),
        "contract_sha256": RESEARCH_CONTRACT_SHA256,
    }
    validate_receipt(receipt, verify=False)
    return receipt


def validate_receipt(receipt: Dict[str, Any], verify: bool = False) -> None:
    """Fail-closed validation of one experiment receipt.

    ``verify=True`` additionally checks every bound artifact against the
    bytes currently on disk (used when *promoting* evidence to a claim).
    """
    for key in _REQUIRED_EXPERIMENT_KEYS:
        _require(key in receipt, f"missing required field '{key}'")
    _require(receipt["schema"] == EXPERIMENT_RECEIPT_SCHEMA, "wrong schema")
    _require(receipt["contract_sha256"] == RESEARCH_CONTRACT_SHA256, "RQ contract drift")
    _require(receipt["protocol"].get("sha256"), "missing protocol SHA256")
    _require(bool(receipt["metric_ids"]), "metric_ids must be non-empty")
    _require(bool(receipt["git_sha"]), "missing git SHA")
    _require(
        (not receipt["source_dirty"]) or bool(receipt.get("dirty_reason")),
        "dirty source without documented reason -> inadmissible evidence",
    )
    if receipt["execution_status"] == "COMPLETED":
        _require(bool(receipt["seeds"]), "COMPLETED run must record seeds")
        _require(bool(receipt["settings_digest"]), "COMPLETED run must record settings digest")
    if verify:
        proto = receipt["protocol"]
        pp = Path(proto["path"])
        _require(pp.is_file(), f"protocol file missing: {proto['path']}")
        if pp.is_file():
            _require(sha256_file(pp) == proto["sha256"], "protocol sha mismatch")
        validate_artifact_list(receipt["inputs"], "inputs", verify)
        validate_artifact_list(receipt["outputs"], "outputs", verify)


def receipt_digest(receipt: Dict[str, Any]) -> str:
    return sha256_of_jsonable(receipt)


def build_claim_receipt(
    *,
    rq_id: str,
    claim_status: str,
    claim_statement: str,
    experiment_receipt_digests: List[str],
    adjudication: Dict[str, Any],
    contract_sha256: str,
) -> Dict[str, Any]:
    """Construct one adjudicated claim receipt (no metrics computed here)."""
    if claim_status not in CLAIM_STATUSES:
        raise ValueError(
            f"claim status '{claim_status}' is not an authorized status "
            f"(allowed from contract: {CLAIM_STATUSES})"
        )
    claim = {
        "schema": CLAIM_RECEIPT_SCHEMA,
        "rq_id": str(rq_id),
        "claim_status": claim_status,
        "claim_statement": str(claim_statement),
        "experiment_receipts_sha256": sorted(
            str(d) for d in experiment_receipt_digests if "unadjudicated" not in str(d)
        ),
        "adjudication": dict(adjudication),
        "adjudicator_version": None,  # filled by adjudicator
        "contract_sha256": contract_sha256,
    }
    return claim


def claim_digest(claim: Dict[str, Any]) -> str:
    return sha256_of_jsonable(claim)


def build_closure_matrix(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """RQ -> claim-digest mapping for the closure gate."""
    norm: Dict[str, Any] = {}
    for e in entries:
        _require({"rq_id", "claim_status", "claim_receipt_sha256"} <= set(e), "closure entry malformed")
        norm[str(e["rq_id"])] = {
            "claim_status": e["claim_status"],
            "claim_receipt_sha256": e["claim_receipt_sha256"],
        }
    return {
        "schema": CLOSURE_MATRIX_SCHEMA,
        "entries": norm,
        "contract_sha256": RESEARCH_CONTRACT_SHA256,
    }


def write_receipt(path: Path, receipt: Dict[str, Any]) -> str:
    """Write a receipt as pretty JSON and return its canonical digest."""
    path = Path(path)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return receipt_digest(receipt)
