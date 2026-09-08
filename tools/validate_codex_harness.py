"""Validate the repository-scoped Codex multi-agent configuration."""
from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / ".codex" / "agents"
REQUIRED = {"scout", "test_triage", "evidence_auditor", "reviewer", "implementer"}
READ_ONLY = REQUIRED - {"implementer"}


def main() -> int:
    config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
    agents_config = config.get("agents", {})
    errors: list[str] = []
    if agents_config.get("enabled") is not True:
        errors.append("agents.enabled must be true")
    if not isinstance(agents_config.get("max_concurrent_threads_per_session"), int):
        errors.append("agents.max_concurrent_threads_per_session must be an integer")

    found = {path.stem for path in AGENTS_DIR.glob("*.toml")}
    for name in sorted(REQUIRED - found):
        errors.append(f"missing agent: {name}")
    for name in sorted(REQUIRED & found):
        data = tomllib.loads((AGENTS_DIR / f"{name}.toml").read_text(encoding="utf-8"))
        for field in ("name", "description", "developer_instructions", "model", "model_reasoning_effort"):
            if not data.get(field):
                errors.append(f"{name}: missing {field}")
        if data.get("name") != name:
            errors.append(f"{name}: name must match filename")
        if name in READ_ONLY and data.get("sandbox_mode") != "read-only":
            errors.append(f"{name}: must be read-only")
        if name == "implementer" and data.get("sandbox_mode") != "workspace-write":
            errors.append("implementer: must use workspace-write")

    if errors:
        print("CODEX_HARNESS_INVALID")
        print("\n".join(sorted(errors)))
        return 1
    print("CODEX_HARNESS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
