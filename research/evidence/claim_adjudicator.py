# -*- coding: utf-8 -*-
"""Research claim adjudicator — validates whether evidence can support a claim.

The adjudicator computes NO scientific metric.  It is a deterministic,
machine-readable gate that maps experiment receipts to a contract-legal
claim status (or NOT_RUN / inadmissible evidence), together with the exact
reasons.  Deterministic: identical receipts always adjudicate identically.

Key gates (fail-closed):

  * missing protocol SHA / contract drift / artifact drift -> NOT_RUN
    (invalid evidence, never authorititative);
  * dirty source without documented reason -> evidence inadmissible ->
    NOT_RUN;
  * missing required runs -> NOT_RUN;
  * Town10HD data can never be cited for an RQ3 authoritative claim
    (contract claim_boundary, enforced defensively here even though this
    adjudicator is RQ1/RQ2 scoped);
  * unlabeled RQ5B data can never support a generalization-accuracy claim
    (RQ5 contract claim_boundary);
  * RQ1 AUTHORITATIVE requires a run count declared by the governing protocol
    and all required metric identities
    (raw/normalized/structural repeatability evidence present);
  * RQ2 respects the frozen bounded local-hull claim boundary: whole-map
    scope work alone can never upgrade the claim beyond BOUNDED.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ADJUDICATOR_VERSION = "research-claim-adjudicator/v2"

# Operational guard only; the checked-in thesis contract does not declare a
# required RQ1 run count, so this value cannot authorize scientific claims.
RQ1_REQUIRED_VALID_RUNS = 5
RQ1_REQUIRED_METRIC_IDS = {
    "raw_hash_repeatability",
    "normalized_hash_repeatability",
    "structural_signature_repeatability",
    "byte_nondeterminism_source",
}
RQ2_REQUIRED_METRIC_IDS = {
    "lane_width_gap",
    "curvature_gap",
    "curvature_wasserstein_gap",
    "road_count_ratio",
    "road_length_ratio",
    "junction_ratio",
    "building_density_gap",
    "frechet_distance",
    "connectivity_gap",
    "semantic_object_gap",
}


def _contract_statuses() -> List[str]:
    from research.evidence.schemas import CLAIM_STATUSES

    return list(CLAIM_STATUSES)


def rq1_required_valid_runs_from_contract() -> Optional[int]:
    """Return an RQ1 run count only when the governing contract declares it."""
    import yaml

    from research.evidence.schemas import REPO_ROOT

    try:
        document = yaml.safe_load(
            (REPO_ROOT / "research" / "thesis_rq_contract.yaml").read_text(encoding="utf-8")
        )
        count = document["research_questions"]["RQ1"].get("required_valid_runs")
        return count if type(count) is int and count > 0 else None
    except (OSError, KeyError, TypeError, AttributeError, yaml.YAMLError):
        return None


def _check_bindings(receipt: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """Return (problem, details).  problem=None when admissible."""
    from research.evidence.schemas import validate_receipt

    try:
        # This gate admits experiment evidence to a scientific claim.  A
        # structurally valid receipt is insufficient: every receipt binding
        # must still resolve to the recorded bytes at promotion time.
        validate_receipt(receipt, verify=True)
    except ValueError as exc:
        return str(exc), {"gate": "receipt_structure"}
    if receipt["contract_sha256"] != receipt_protocol_sha_guard(receipt):
        # contract drift is checked inside validate_receipt already; kept for clarity
        return "RQ contract drift", {"gate": "contract_sha256"}
    if not receipt["protocol"].get("sha256"):
        return "missing protocol SHA256", {"gate": "protocol_sha"}
    if receipt["source_dirty"] and not receipt.get("dirty_reason"):
        return "dirty source with no documented reason", {"gate": "source_cleanliness"}
    if receipt["execution_status"] != "COMPLETED":
        return (
            f"execution_status={receipt['execution_status']} (required COMPLETED)",
            {"gate": "execution_status"},
        )
    if not receipt["inputs"]:
        return "missing input binding", {"gate": "inputs"}
    if not receipt["outputs"]:
        return "missing output binding", {"gate": "outputs"}
    if not receipt["metric_ids"]:
        return "metric ids missing", {"gate": "metric_ids"}
    return None, {"gate": "bindings_ok"}


def receipt_protocol_sha_guard(receipt: Dict[str, Any]) -> str:
    """The contract SHA the receipt itself carries (used in drift checks)."""
    return receipt.get("contract_sha256", "")


def semantic_scope_guard(rq_id: str, evidence: Dict[str, Any]) -> Optional[str]:
    """Contract boundary guard.  Returns a reason string when forbidden."""
    town = str(evidence.get("map_identity", "") or "")
    labeled = evidence.get("labeled", True)

    if rq_id == "RQ3" and "town10hd" in town.lower():
        return (
            "claim_boundary violation: Town10HD may only be used as "
            "sensor-rig smoke/control evidence, never as an RQ3 answer"
        )
    if rq_id.startswith("RQ5") and labeled is False:
        return (
            "claim_boundary violation: unlabeled distribution shift is not "
            "model-generalization accuracy (RQ5B boundary)"
        )
    return None


def adjudicate_rq1(
    run_receipts: List[Dict[str, Any]],
    determinism_matrix: Optional[Dict[str, Any]] = None,
    *,
    required_valid_runs: int = RQ1_REQUIRED_VALID_RUNS,
    current_contract_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Adjudicate the RQ1 determinism claim.

    ``run_receipts`` are per-run experiment receipts (rq_experiment_receipt/v1)
    built by the evidence assembler; ``determinism_matrix`` is the five-run
    comparator output whose repeatability booleans are the only source for
    AUTHORITATIVE (repeating identical return codes alone is never
    sufficient).
    """
    from research.evidence.schemas import (
        EXPERIMENT_RECEIPT_SCHEMA_V3,
        RESEARCH_CONTRACT_SHA256,
        load_claim_statuses,
    )
    from research.evidence.canonical import sha256_of_jsonable

    statuses = load_claim_statuses()
    contract = current_contract_sha256 or RESEARCH_CONTRACT_SHA256
    problems: List[str] = []
    detail: Dict[str, Any] = {"gate": "rq1_five_run"}

    frozen_run_count = rq1_required_valid_runs_from_contract()
    if frozen_run_count is None:
        problems.append("governing RQ1 protocol does not specify required_valid_runs")
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)
    if required_valid_runs != frozen_run_count:
        problems.append(
            f"requested run count {required_valid_runs} disagrees with governing protocol count {frozen_run_count}"
        )
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)

    if not run_receipts:
        return _claim("RQ1", "NOT_RUN", "no experiment receipts", problems, statuses, contract)

    valid: List[Dict[str, Any]] = []
    for r in run_receipts:
        problem, gate = _receipt_gate(r, contract)
        if problem:
            problems.append(f"{r.get('rq_id', '-')}: {problem} [{gate.get('gate')}]")
            continue
        missing_metrics = RQ1_REQUIRED_METRIC_IDS - set(r["metric_ids"])
        if missing_metrics:
            problems.append(f"missing RQ1 metric identities: {sorted(missing_metrics)}")
            continue
        if r.get("schema") != EXPERIMENT_RECEIPT_SCHEMA_V3:
            problems.append(
                "RQ1 receipt lacks v3 run identity; legacy schemas remain readable "
                "but cannot establish distinct campaign runs"
            )
            continue
        if r.get("source_dirty") is not False:
            problems.append("RQ1 receipt source is dirty; authoritative admission requires clean committed source")
            continue
        valid.append(r)

    detail["receipts_total"] = len(run_receipts)
    detail["receipts_valid"] = len(valid)

    if len(valid) < required_valid_runs:
        problems.append(
            f"missing required runs: {len(valid)}/{required_valid_runs} valid receipts"
        )
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)

    identities = [r["run_identity"] for r in valid]
    run_ids = [identity["run_id"] for identity in identities]
    run_indices = [identity["run_index"] for identity in identities]
    run_roots = [str(Path(identity["run_output_root"]).resolve()) for identity in identities]
    output_sets = [
        tuple(sorted(str(Path(entry["path"]).resolve()) for entry in receipt["outputs"]))
        for receipt in valid
    ]
    invocation_ids = {identity["invocation_id"] for identity in identities}
    metric_payload_bindings = {r["raw_metric_payload_sha256"] for r in valid}
    if (
        len(valid) != required_valid_runs
        or len(set(run_ids)) != required_valid_runs
        or len(set(run_indices)) != required_valid_runs
        or len(set(run_roots)) != required_valid_runs
        or len(set(output_sets)) != required_valid_runs
        or len(invocation_ids) != 1
        or len(metric_payload_bindings) != required_valid_runs
    ):
        problems.append(
            "RQ1 evidence does not bind exactly the required number of distinct runs "
            "to one invocation (run ids, indices, outputs, and payloads must be unique)"
        )
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)

    # Repeatability comes ONLY from the measured determinism matrix (raw /
    # normalized / structural identity equality across the valid runs) --
    # never from return codes or receipt presence alone.
    if not determinism_matrix:
        problems.append("five-run determinism matrix missing (invalid evidence)")
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)
    if determinism_matrix.get("schema") != "rq1_full_determinism_matrix/v2":
        problems.append("RQ1 claim requires matrix schema v2 with explicit per-run bindings")
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)

    matrix_runs = determinism_matrix.get("per_run")
    if not isinstance(matrix_runs, list) or len(matrix_runs) != required_valid_runs:
        problems.append("five-run determinism matrix lacks one entry per required run")
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)
    matrix_by_id: Dict[str, Dict[str, Any]] = {}
    for matrix_run in matrix_runs:
        if not isinstance(matrix_run, dict):
            problems.append("determinism matrix contains a malformed run entry")
            return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)
        run_id = matrix_run.get("run_id")
        if not isinstance(run_id, str) or not run_id or run_id in matrix_by_id:
            problems.append("determinism matrix run ids are missing or duplicated")
            return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)
        matrix_by_id[run_id] = matrix_run

    for receipt, identity in zip(valid, identities):
        matrix_run = matrix_by_id.get(identity["run_id"])
        expected_identity_sha = identity["output_identity_sha256"]
        matrix_identity = (matrix_run or {}).get("identities") or {}
        input_identity = matrix_identity.get("input_identity") or {}
        receipt_map_identity = receipt.get("map_identities") or {}
        if (
            matrix_run is None
            or matrix_run.get("run") != identity["run_index"]
            or matrix_run.get("valid") is not True
            or not isinstance(matrix_run.get("identities"), dict)
            or sha256_of_jsonable(matrix_run["identities"]) != expected_identity_sha
            or identity["source_sha"] != receipt.get("git_sha")
            or identity["input_sha256"]
            != receipt_map_identity.get("auto_map_of_record_sha256")
            or input_identity.get("input_xodr_sha256") != identity["input_sha256"]
            or matrix_identity.get("raw_xodr_sha256")
            != receipt_map_identity.get("final_xodr_sha256")
            or matrix_identity.get("normalized_xodr_sha256")
            != receipt_map_identity.get("normalized_xodr_sha256")
            or matrix_identity.get("structural_signature")
            != receipt_map_identity.get("structural_signature_sha256")
            or matrix_identity.get("tileset_digest") != receipt_map_identity.get("tileset_digest")
            or matrix_identity.get("map_acceptance_digest")
            != receipt_map_identity.get("map_acceptance_digest")
            or matrix_identity.get("final_receipt_digest")
            != receipt_map_identity.get("final_receipt_digest")
            or matrix_identity.get("settings_digest") != receipt.get("settings_digest")
        ):
            problems.append(
                f"RQ1 receipt/matrix run binding mismatch for {identity['run_id']}"
            )
            return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)

    identities_in_matrix = [row["identities"] for row in matrix_runs]
    measured_equal = {
        "all_raw_equal": len({r.get("raw_xodr_sha256") for r in identities_in_matrix}) == 1,
        "all_normalized_equal": len(
            {r.get("normalized_xodr_sha256") for r in identities_in_matrix}
        )
        == 1,
        "all_structural_equal": len(
            {r.get("structural_signature") for r in identities_in_matrix}
        )
        == 1,
    }
    if any(type(determinism_matrix.get(k)) is not bool for k in measured_equal) or any(
        determinism_matrix.get(k) != value for k, value in measured_equal.items()
    ):
        problems.append("determinism matrix summary contradicts its per-run identities")
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)
    all_equal = {
        "raw": measured_equal["all_raw_equal"],
        "normalized": measured_equal["all_normalized_equal"],
        "structural": measured_equal["all_structural_equal"],
    }
    raw_valid_run_count = determinism_matrix.get("valid_run_count", detail["receipts_valid"])
    if type(raw_valid_run_count) is not int:
        problems.append("matrix valid_run_count must be an integer")
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)
    valid_run_count = raw_valid_run_count
    detail["identity_repeatability"] = all_equal
    detail["matrix_valid_run_count"] = valid_run_count
    detail["divergence_classification"] = determinism_matrix.get(
        "divergence_classification"
    )

    if valid_run_count < required_valid_runs:
        problems.append(
            f"matrix valid_run_count {valid_run_count} < required {required_valid_runs}"
        )
        return _claim("RQ1", "NOT_RUN", None, problems, statuses, contract, detail)

    if not all(all_equal.values()):
        problems.append(f"identity repeatability not established: {all_equal}")
        divergence = determinism_matrix.get("divergence_classification")
        return _claim(
            "RQ1",
            "BOUNDED",
            "partial evidence: required valid runs executed, but identity "
            "repeatability across raw/normalized/structural domains is not "
            "fully established for an authoritative determinism claim "
            f"(classification={divergence})",
            problems,
            statuses,
            contract,
            detail,
        )
    if determinism_matrix.get("divergence_classification") != "NO_DIFFERENCE":
        problems.append(
            "divergence classification is not NO_DIFFERENCE: "
            f"{determinism_matrix.get('divergence_classification')}"
        )
        return _claim(
            "RQ1", "BOUNDED", None, problems, statuses, contract, detail
        )

    return _claim(
        "RQ1",
        "AUTHORITATIVE",
        "OSM->OpenDRIVE structural and topological signatures are repeatable "
        "across the required isolated runs under equal pinned inputs",
        problems,
        statuses,
        contract,
        detail,
    )


def _receipt_gate(receipt: Dict[str, Any], contract: str) -> Tuple[Optional[str], Dict[str, Any]]:
    if _contract_guard(receipt, contract):
        return "receipt contract drift (stale/unbound evidence)", {"gate": "contract_sha256"}
    return _check_bindings(receipt)


def adjudicate_rq2(
    experiment_receipts: List[Dict[str, Any]],
    *,
    current_contract_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Adjudicate the RQ2 structural-domain-gap claim.

    Boundary: the frozen thesis claim is BOUNDED (local-hull primary scope,
    same-region comparison).  A whole-map-scope-only receipt can never
    upgrade the claim; hull-scope evidence reproducing the frozen metrics
    re-establishes BOUNDED (never AUTHORITATIVE — the manual comparison is
    a single manual reference, not a population).
    """
    from research.evidence.schemas import (
        RESEARCH_CONTRACT_SHA256,
        load_claim_statuses,
    )

    statuses = load_claim_statuses()
    contract = current_contract_sha256 or RESEARCH_CONTRACT_SHA256
    problems: List[str] = []
    detail: Dict[str, Any] = {
        "gate": "rq2_structural_gap",
        "boundary": "bounded local-hull",
    }

    if not experiment_receipts:
        return _claim("RQ2", "NOT_RUN", "no experiment receipts", problems, statuses, contract)

    admissible = [
        r
        for r in experiment_receipts
        if _contract_guard(r, contract) is None
        and _receipt_gate(r, contract)[0] is None
        and not (RQ2_REQUIRED_METRIC_IDS - set(r["metric_ids"]))
    ]
    if not admissible:
        for r in experiment_receipts:
            problem, gate = _receipt_gate(r, contract)
            if problem:
                problems.append(f"{problem} [{gate.get('gate')}]")
            else:
                missing = RQ2_REQUIRED_METRIC_IDS - set(r["metric_ids"])
                problems.append(f"missing RQ2 metric identities: {sorted(missing)}")
        return _claim("RQ2", "NOT_RUN", None, problems, statuses, contract, detail)

    # Deterministic scope selection: hull-scope evidence outranks whole-map
    # context. A whole-map-only receipt set can never support the bounded
    # claim (whole-map work alone can never upgrade the claim); but whole-map
    # context must not mask admissible hull receipts that arrived earlier.
    hull_receipts = [
        r
        for r in admissible
        if (r.get("map_identities") or {}).get("scope") == "manual_hull"
    ]
    if not hull_receipts:
        scope = (admissible[0].get("map_identities") or {}).get("scope")
        detail["scope"] = scope
        problems.append(
            "whole-map scope alone cannot support the local-hull bounded claim"
        )
        return _claim("RQ2", "NOT_RUN", None, problems, statuses, contract, detail)
    scope = "manual_hull"
    detail["scope"] = scope
    identities = hull_receipts[0].get("map_identities") or {}

    frozen_reproduced = bool(identities.get("frozen_reproduction"))
    if frozen_reproduced:
        return _claim(
            "RQ2",
            "BOUNDED",
            "RQ2 structural domain gap recomputed on the current lineage under "
            "the frozen local-hull scope, reproducing the frozen metric "
            "citations; claim remains bounded to the local-hull comparison",
            problems,
            statuses,
            contract,
            detail,
        )
    return _claim("RQ2", "NOT_RUN", None, problems, statuses, contract, detail)


def _contract_guard(receipt: Dict[str, Any], contract_sha: str) -> Optional[str]:
    if receipt.get("contract_sha256") != contract_sha:
        return "receipt contract drift (stale/unbound evidence)"
    return None


def _claim(
    rq_id: str,
    status: str,
    statement: Optional[str],
    problems: List[str],
    statuses: List[str],
    contract: str,
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if status not in statuses:  # absolute fail-closed guard
        status = "NOT_RUN"
    return {
        "schema": "rq_claim_receipt/v1",
        "rq_id": rq_id,
        "claim_status": status,
        "claim_statement": statement,
        "adjudication": {
            "adjudicator_version": ADJUDICATOR_VERSION,
            "contract_sha256": contract,
            "problems": problems,
            "detail": detail or {},
        },
        "contract_sha256": contract,
    }
