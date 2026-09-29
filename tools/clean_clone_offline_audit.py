"""Audit onboarding state of a repository checkout without network downloads."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def audit_checkout(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    def run(name: str, command: list[str]) -> None:
        try:
            proc = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=30)
            checks.append({"check": name, "status": "PASS" if proc.returncode == 0 else "INCOMPLETE", "returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]})
        except Exception as exc:
            checks.append({"check": name, "status": "INCOMPLETE", "reason": str(exc)})
    run("git_default_branch", ["git", "branch", "--show-current"])
    run("git_lineage", ["git", "rev-parse", "HEAD"])
    run("python_import", [ "python", "-c", "import ultimate_pipeline; print('ok')"])
    run("map_registry", ["python", "-c", "from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map; print(verify_pinned_map('auto_map_of_record')['sha256'])"])
    lfs = (root / ".gitattributes").read_text(encoding="utf-8", errors="ignore") if (root / ".gitattributes").is_file() else ""
    lfs_required = "filter=lfs" in lfs
    checks.append({"check": "git_lfs", "status": "INCOMPLETE" if lfs_required else "PASS", "required": lfs_required, "reason": "LFS objects must be smudged in a fresh clone" if lfs_required else "no LFS attributes detected"})
    hard = [c for c in checks if c["status"] == "INCOMPLETE"]
    return {"schema": "clean_clone_offline_audit/v1", "status": "PASS" if not hard else "INCOMPLETE", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "root": str(root), "checks": checks, "limitations": ["No CARLA/UE4 download or build attempted.", "A current checkout audit cannot prove a fresh clone unless --clone-root points to one."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clone-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, default=Path("CLEAN_CLONE_OFFLINE_AUDIT.json"))
    args = parser.parse_args()
    report = audit_checkout(args.clone_root)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
