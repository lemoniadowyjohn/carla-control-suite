"""Static RQ5 experiment-contract audit; no scientific choices are filled."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED = [
    "model_architecture", "initialization_policy", "training_split", "validation_split", "test_split", "data_budget", "image_resolution", "augmentations", "optimizer", "learning_rate", "epochs", "seed_policy", "class_mapping", "metrics", "checkpoint_selection", "transfer_comparison_matrix",
]


def audit(repo: Path) -> dict[str, Any]:
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
    parser.add_argument("--out", type=Path, default=Path("RQ5_EXPERIMENT_CONTRACT_AUDIT.json"))
    args = parser.parse_args()
    report = audit(args.repo)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "missing": report["missing_decisions"], "ambiguous": report["ambiguous_decisions"]}, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
