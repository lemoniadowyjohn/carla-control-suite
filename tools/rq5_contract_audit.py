"""RQ5 experiment-contract audit: frozen-contract check with legacy fallback.

P12/NEW-218: when a machine-readable frozen protocol contract exists
(configs/rq5_protocol_freeze_v1.json, or --contract), every REQUIRED
decision must have an explicit frozen value with provenance; the audit then
reports PASS. The audit itself fills no scientific choices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED = [
    "model_architecture", "initialization_policy", "training_split", "validation_split", "test_split", "data_budget", "image_resolution", "augmentations", "optimizer", "learning_rate", "epochs", "seed_policy", "class_mapping", "metrics", "checkpoint_selection", "transfer_comparison_matrix",
]

DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "configs" / "rq5_protocol_freeze_v1.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _audit_frozen_contract(contract_path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(contract_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"schema": "rq5_experiment_contract_static_check/v1", "status": "FAIL",
                "rows": [{"decision": n, "status": "MISSING", "evidence": f"contract unreadable: {exc}"} for n in REQUIRED],
                "missing_decisions": list(REQUIRED), "ambiguous_decisions": [],
                "scientific_choices_filled": False,
                "claim_boundary": "Static audit only; no architecture, split, budget, or metric choice was invented."}
    decisions = doc.get("decisions", {}) if isinstance(doc, dict) else {}
    rows = []
    for name in REQUIRED:
        entry = decisions.get(name)
        if isinstance(entry, dict) and entry.get("value") not in (None, "") and entry.get("provenance") in ("repo_default", "campaign_frozen"):
            rows.append({"decision": name, "status": "DEFINED",
                         "evidence": f"frozen contract {contract_path.name}: provenance={entry.get('provenance')} source={entry.get('source')}"})
        else:
            rows.append({"decision": name, "status": "MISSING",
                         "evidence": "no explicit frozen value with provenance in contract"})
    missing = [r["decision"] for r in rows if r["status"] == "MISSING"]
    return {"schema": "rq5_experiment_contract_static_check/v1",
            "status": "PASS" if not missing else "FAIL",
            "rows": rows, "missing_decisions": missing, "ambiguous_decisions": [],
            "contract_path": str(contract_path),
            "contract_sha256": _sha256(contract_path),
            "contract_schema": doc.get("schema") if isinstance(doc, dict) else None,
            "contract_status": doc.get("status") if isinstance(doc, dict) else None,
            "scientific_choices_filled": False,
            "claim_boundary": "Frozen-contract audit; values are read from the versioned protocol contract, no architecture, split, budget, or metric choice was invented by the audit."}


def audit(repo: Path, contract: Path | None = None) -> dict[str, Any]:
    candidate = contract or (repo / "configs" / "rq5_protocol_freeze_v1.json")
    if candidate.is_file():
        return _audit_frozen_contract(candidate)
    if DEFAULT_CONTRACT.is_file() and DEFAULT_CONTRACT != candidate:
        return _audit_frozen_contract(DEFAULT_CONTRACT)
    return _audit_legacy(repo)


def _audit_legacy(repo: Path) -> dict[str, Any]:
    candidates = [
        repo / "ultimate_pipeline" / "config" / "settings.py",
        repo / "ultimate_pipeline" / "experiments" / "thesis" / "exp_osm_to_xodr_determinism.py",
        repo / "README.md",
    ]
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in candidates if p.is_file())
    rows = []
    for name in REQUIRED:
        tokens = name.split("_")
        evidence = any(token.lower() in text.lower() for token in tokens)
        rows.append({"decision": name, "status": "AMBIGUOUS" if evidence else "MISSING", "evidence": "keyword present but explicit frozen value not proven" if evidence else "no explicit contract evidence found"})
    missing = [r["decision"] for r in rows if r["status"] == "MISSING"]
    ambiguous = [r["decision"] for r in rows if r["status"] == "AMBIGUOUS"]
    return {"schema": "rq5_experiment_contract_static_check/v1", "status": "FAIL" if missing or ambiguous else "PASS", "rows": rows, "missing_decisions": missing, "ambiguous_decisions": ambiguous, "scientific_choices_filled": False, "claim_boundary": "Static audit only; no architecture, split, budget, or metric choice was invented."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--contract", type=Path, default=None,
                        help="explicit frozen protocol contract (default: <repo>/configs/rq5_protocol_freeze_v1.json)")
    parser.add_argument("--out", type=Path, default=Path("RQ5_EXPERIMENT_CONTRACT_AUDIT.json"))
    args = parser.parse_args()
    report = audit(args.repo, contract=args.contract)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "missing": report["missing_decisions"], "ambiguous": report["ambiguous_decisions"]}, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
