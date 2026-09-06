"""Repository-level health packet for offline release gates."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_NOT_RUN = "NOT_RUN"
STATUS_BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"

RELEASE_STATUSES = {
    STATUS_PASS,
    STATUS_FAIL,
    STATUS_INCOMPLETE,
    STATUS_NOT_RUN,
    STATUS_BLOCKED_EXTERNAL,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(argv: Iterable[str], cwd: Path, *, timeout_s: float = 60.0) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cwd),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )
    except Exception as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _git_state(repo_root: Path) -> Dict[str, Any]:
    head = _run(["git", "rev-parse", "HEAD"], repo_root)
    branch = _run(["git", "branch", "--show-current"], repo_root)
    status = _run(["git", "status", "--short"], repo_root)
    remotes = _run(["git", "remote", "-v"], repo_root)
    return {
        "repo_root": repo_root.as_posix(),
        "branch": branch["stdout"] or "UNKNOWN",
        "head": head["stdout"] or "UNKNOWN",
        "dirty": bool(status["stdout"]),
        "status_short": status["stdout"].splitlines() if status["stdout"] else [],
        "remotes": remotes["stdout"].splitlines() if remotes["stdout"] else [],
    }


def _package_status() -> Dict[str, Any]:
    try:
        version = importlib.metadata.version("ultimate-pipeline")
    except importlib.metadata.PackageNotFoundError:
        version = ""
    entrypoints = [
        ep.value
        for ep in importlib.metadata.entry_points(group="console_scripts")
        if ep.name == "up"
    ]
    status = STATUS_PASS if version and "ultimate_pipeline.cli:main" in entrypoints else STATUS_INCOMPLETE
    return {
        "status": status,
        "distribution": "ultimate-pipeline",
        "version": version or "NOT_INSTALLED_AS_DISTRIBUTION",
        "console_script_up": entrypoints,
    }


def _dependency_integrity(repo_root: Path, *, run_pip_check: bool) -> Dict[str, Any]:
    if not run_pip_check:
        return {"status": STATUS_NOT_RUN, "reason": "pip check skipped"}
    result = _run([sys.executable, "-m", "pip", "check"], repo_root, timeout_s=120.0)
    return {
        "status": STATUS_PASS if result["ok"] else STATUS_FAIL,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def _research_contract_status(repo_root: Path) -> Dict[str, Any]:
    contract_path = repo_root / "research" / "thesis_rq_contract.yaml"
    text = contract_path.read_text(encoding="utf-8") if contract_path.is_file() else ""
    required = [
        "RQ1:",
        "RQ2:",
        "RQ3:",
        "RQ4:",
        "RQ5:",
        "raw_hash_repeatability",
        "paired_camera_distribution_shift",
        "DEFERRED_RUNTIME",
        "DEFERRED_EXTERNAL_DATA",
    ]
    missing = [needle for needle in required if needle not in text]
    try:
        from ultimate_pipeline.tools.audit_thesis_topic_contract import _current_rq_tables_audit

        audit = _current_rq_tables_audit(repo_root)
    except Exception as exc:
        audit = {"ok": False, "violations": [str(exc)]}
    status = STATUS_PASS if contract_path.is_file() and not missing and audit.get("ok") else STATUS_FAIL
    return {
        "status": status,
        "contract_path": contract_path.as_posix(),
        "missing_anchors": missing,
        "rq_table_audit": audit,
    }


def _research_provenance_status(repo_root: Path) -> Dict[str, Any]:
    path = repo_root / "reports" / "post_audit_hardening" / "C19_THESIS_ASSEMBLY" / "provenance_validation.json"
    payload = _read_json(path)
    if not payload:
        return {"status": STATUS_NOT_RUN, "path": path.as_posix(), "reason": "provenance_validation.json missing"}
    return {"status": STATUS_PASS if payload.get("ok") else STATUS_FAIL, "path": path.as_posix(), "ok": payload.get("ok")}


def _map_identity(repo_root: Path, *, verify_maps: bool) -> Dict[str, Any]:
    if not verify_maps:
        return {"status": STATUS_NOT_RUN, "reason": "map hash verification skipped"}
    try:
        from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

        entries = {
            "auto_map_of_record": verify_pinned_map("auto_map_of_record"),
            "manual_grid0828": verify_pinned_map("manual_grid0828"),
        }
    except Exception as exc:
        return {"status": STATUS_FAIL, "error": str(exc)}
    return {"status": STATUS_PASS, "maps": entries}


def _evidence_completeness(repo_root: Path) -> Dict[str, Any]:
    rq_tables = _read_json(
        repo_root / "reports" / "post_audit_hardening" / "C19_THESIS_ASSEMBLY" / "rq_tables.json"
    )
    progress = repo_root / "docs" / "research" / "THESIS_TO_CURRENT_PROGRESS.md"
    row_count = int(rq_tables.get("row_count") or 0)
    counts = rq_tables.get("counts_by_status", {})
    status = STATUS_PASS if row_count > 0 and progress.is_file() else STATUS_INCOMPLETE
    return {
        "status": status,
        "rq_row_count": row_count,
        "counts_by_status": counts,
        "progress_doc": progress.as_posix(),
        "progress_doc_present": progress.is_file(),
    }


def _runtime_verification(status: str, reason: str) -> Dict[str, Any]:
    if status not in RELEASE_STATUSES:
        status = STATUS_NOT_RUN
    return {
        "status": status,
        "carla_required_version": "0.9.16",
        "reason": reason or "No live CARLA runtime verification was executed in this offline health check.",
    }


def _overall_status(sections: Dict[str, Dict[str, Any]]) -> str:
    required = [
        "package",
        "dependency_integrity",
        "research_contract",
        "research_provenance",
        "map_identity",
        "evidence_completeness",
        "tests",
    ]
    if any(sections.get(key, {}).get("status") == STATUS_FAIL for key in required):
        return STATUS_FAIL
    if sections.get("runtime_verification", {}).get("status") in {STATUS_NOT_RUN, STATUS_BLOCKED_EXTERNAL}:
        return STATUS_INCOMPLETE
    if any(sections.get(key, {}).get("status") in {STATUS_NOT_RUN, STATUS_INCOMPLETE} for key in required):
        return STATUS_INCOMPLETE
    return STATUS_PASS


def build_repo_health(
    repo_root: Path | None = None,
    *,
    test_result: str = STATUS_NOT_RUN,
    run_pip_check: bool = True,
    verify_maps: bool = True,
    runtime_status: str = STATUS_NOT_RUN,
    runtime_reason: str = "",
) -> Dict[str, Any]:
    root = (repo_root or _repo_root()).resolve()
    if test_result not in RELEASE_STATUSES:
        test_result = STATUS_NOT_RUN
    sections = {
        "package": _package_status(),
        "dependency_integrity": _dependency_integrity(root, run_pip_check=run_pip_check),
        "research_contract": _research_contract_status(root),
        "research_provenance": _research_provenance_status(root),
        "map_identity": _map_identity(root, verify_maps=verify_maps),
        "evidence_completeness": _evidence_completeness(root),
        "tests": {
            "status": test_result,
            "reason": "Full offline test result must be supplied by CI/operator." if test_result == STATUS_NOT_RUN else "",
        },
        "runtime_verification": _runtime_verification(runtime_status, runtime_reason),
    }
    git_state = _git_state(root)
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo": "lemoniadowyjohn/carla-control-suite",
        # The thesis-contract lineage the RQ contract was created for
        # (research/thesis_rq_contract.yaml:created_for_lineage). This is a
        # historical label, NOT the branch currently under review -- read
        # `release_branch` (sourced live from git) for that, so the two never
        # get conflated when the release moves onto a new branch.
        "authoritative_lineage": "fix/post-audit-phase-e-junctions-roundabouts-20260803",
        "release_branch": git_state.get("branch", "UNKNOWN"),
        "git": git_state,
        "python": {"executable": sys.executable, "version": platform.python_version()},
        "sections": sections,
        "overall_status": _overall_status(sections),
        "deferred_checks": [
            {
                "check": "live_carla_runtime_verification",
                "status": sections["runtime_verification"]["status"],
                "reason": sections["runtime_verification"]["reason"],
            }
        ],
    }
    return payload


def _to_markdown(payload: Dict[str, Any]) -> str:
    git = payload["git"]
    lines = [
        "# Repository Health",
        "",
        f"- Repo: `{payload['repo']}`",
        f"- Branch: `{git['branch']}`",
        f"- HEAD: `{git['head']}`",
        f"- Dirty: `{git['dirty']}`",
        f"- Python: `{payload['python']['version']}`",
        f"- Overall status: `{payload['overall_status']}`",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for name, section in payload["sections"].items():
        detail = section.get("reason") or section.get("path") or section.get("contract_path") or ""
        lines.append(f"| {name} | `{section.get('status', 'UNKNOWN')}` | {detail} |")
    lines.append("")
    lines.append("Runtime verification is intentionally separate from GitHub-hosted offline CI.")
    return "\n".join(lines) + "\n"


def write_repo_health(out_dir: Path, payload: Dict[str, Any]) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "repo_health.json"
    md_path = out_dir / "REPO_HEALTH.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    md_path.write_text(_to_markdown(payload), encoding="utf-8")
    return {"json": json_path.as_posix(), "markdown": md_path.as_posix()}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=_repo_root() / "reports" / "repo_health" / "latest")
    parser.add_argument("--test-result", choices=sorted(RELEASE_STATUSES), default=STATUS_NOT_RUN)
    parser.add_argument("--runtime-status", choices=sorted(RELEASE_STATUSES), default=STATUS_NOT_RUN)
    parser.add_argument("--runtime-reason", default="")
    parser.add_argument("--skip-pip-check", action="store_true")
    parser.add_argument("--skip-map-hash", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit only the JSON health payload to stdout")
    parser.add_argument("--strict-release", action="store_true", help="Exit nonzero unless overall_status is PASS")
    args = parser.parse_args(argv)

    payload = build_repo_health(
        _repo_root(),
        test_result=args.test_result,
        run_pip_check=not args.skip_pip_check,
        verify_maps=not args.skip_map_hash,
        runtime_status=args.runtime_status,
        runtime_reason=args.runtime_reason,
    )
    paths = write_repo_health(args.out_dir, payload)
    payload["output_paths"] = paths

    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
    else:
        sys.stdout.write(f"[repo_health] overall_status={payload['overall_status']} -> {paths['json']}\n")
    if payload["overall_status"] == STATUS_FAIL:
        return 1
    if args.strict_release and payload["overall_status"] != STATUS_PASS:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
