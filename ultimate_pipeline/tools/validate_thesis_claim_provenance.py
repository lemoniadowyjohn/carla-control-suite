from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_CLAIM_KEYS = {
    "thesis_claim",
    "authority_run",
    "artifact_path",
    "json_fields",
    "status",
    "notes",
}


def _tokenize(path: str) -> list[Any]:
    tokens: list[Any] = []
    i = 0
    while i < len(path):
        if path[i] == '.':
            i += 1
            continue
        if path[i] == '[':
            j = path.index(']', i)
            tokens.append(int(path[i + 1:j]))
            i = j + 1
            continue
        j = i
        while j < len(path) and path[j] not in '.[':
            j += 1
        tokens.append(path[i:j])
        i = j
    return tokens


def _resolve_json_field(payload: Any, path: str) -> Any:
    cur = payload
    for token in _tokenize(path):
        if isinstance(token, int):
            if not isinstance(cur, list):
                raise KeyError(f"Expected list before index [{token}] in {path}")
            cur = cur[token]
        else:
            if not isinstance(cur, dict) or token not in cur:
                raise KeyError(f"Missing key '{token}' in {path}")
            cur = cur[token]
    return cur


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the thesis-claim provenance ledger.")
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("docs/submission/THESIS_CLAIM_PROVENANCE_LEDGER.json"),
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    ledger_path = args.ledger.resolve()
    if not ledger_path.is_file():
        raise SystemExit(f"Ledger not found: {ledger_path}")

    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    claims = ledger.get("claims")
    if not isinstance(claims, list) or not claims:
        raise SystemExit("Ledger must contain a non-empty 'claims' list")

    errors: list[str] = []
    validated_fields = 0
    for idx, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claim[{idx}] is not an object")
            continue
        missing = sorted(REQUIRED_CLAIM_KEYS - set(claim.keys()))
        if missing:
            errors.append(f"claim[{idx}] missing required keys: {missing}")
            continue
        artifact_path = repo_root / str(claim["artifact_path"])
        if not artifact_path.exists():
            errors.append(f"claim[{idx}] artifact missing: {artifact_path}")
            continue
        json_fields = claim.get("json_fields")
        if not isinstance(json_fields, list) or not json_fields:
            errors.append(f"claim[{idx}] json_fields must be a non-empty list")
            continue
        if artifact_path.suffix.lower() != ".json":
            errors.append(f"claim[{idx}] artifact is not JSON: {artifact_path}")
            continue
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"claim[{idx}] failed to parse JSON {artifact_path}: {exc}")
            continue
        for field in json_fields:
            if not isinstance(field, str) or not field:
                errors.append(f"claim[{idx}] invalid json field entry: {field!r}")
                continue
            try:
                _resolve_json_field(payload, field)
                validated_fields += 1
            except Exception as exc:
                errors.append(f"claim[{idx}] missing field {field} in {artifact_path}: {exc}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)

    print(
        json.dumps(
            {
                "ledger": str(ledger_path.relative_to(repo_root)).replace('\\', '/'),
                "claim_count": len(claims),
                "validated_json_fields": validated_fields,
                "status": "ok",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
