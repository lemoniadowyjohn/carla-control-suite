"""Repository-level health packet for offline release gates."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
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
STATUS_WAIVED = "WAIVED"

RELEASE_STATUSES = {
    STATUS_PASS,
    STATUS_FAIL,
    STATUS_INCOMPLETE,
    STATUS_NOT_RUN,
    STATUS_BLOCKED_EXTERNAL,
    STATUS_WAIVED,
}

# V5 / NEW-208 (closure D19).
#
# The historical single `overall_status` conflated two independent questions:
#   * is the *offline* release evidence complete?   (GitHub-hosted CI can answer)
#   * has a *live CARLA runtime* certified the artifact? (only a real server can)
# `overall_status = INCOMPLETE` with process exit 0 is therefore ambiguous: green
# CI was not equivalent to release PASS. These are now separate, named gates.
GATE_DIAGNOSTIC = "diagnostic"
GATE_OFFLINE_RELEASE = "offline-release-gate"
GATE_RUNTIME_CERTIFICATION = "runtime-certification-gate"
GATES = (GATE_DIAGNOSTIC, GATE_OFFLINE_RELEASE, GATE_RUNTIME_CERTIFICATION)

#: Sections that the offline release gate requires to be PASS.
OFFLINE_REQUIRED_SECTIONS = (
    "package",
    "dependency_integrity",
    "dependency_conflicts",
    "research_contract",
    "research_provenance",
    "map_identity",
    "evidence_completeness",
    "tests",
)

#: Section that the runtime certification gate requires to be PASS.
RUNTIME_REQUIRED_SECTIONS = ("runtime_verification",)


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


# V5 / NEW-205 (J10): mutually exclusive distribution providers.
#
# These are distinct PyPI distributions that install the SAME top-level import
# namespace. Installing two of them in one environment yields a shadowed module
# whose contents depend on install order, and `pip check` does not report it
# because the distributions do not declare a conflict.
EXCLUSIVE_PROVIDER_GROUPS: Dict[str, tuple] = {
    "cv2": ("opencv-python", "opencv-python-headless"),
}


def _installed_distributions() -> Dict[str, str]:
    """Map normalized distribution name -> version for the active environment."""
    found: Dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        try:
            name = (dist.metadata["Name"] or "").strip()
        except Exception:  # pragma: no cover - malformed metadata
            continue
        if not name:
            continue
        key = re.sub(r"[-_.]+", "-", name).lower()
        found[key] = getattr(dist, "version", "") or ""
    return found


def dependency_conflicts() -> Dict[str, Any]:
    """Detect co-installed mutually exclusive namespace providers.

    Returns FAIL when more than one distribution in any exclusive group is
    present, naming the group and the offending distributions. This is a
    dependency-integrity defect, not a style preference: the resulting module
    shadowing is order-dependent and therefore non-deterministic.
    """
    installed = _installed_distributions()
    conflicts: List[Dict[str, Any]] = []
    for namespace, members in sorted(EXCLUSIVE_PROVIDER_GROUPS.items()):
        present = [m for m in members if re.sub(r"[-_.]+", "-", m).lower() in installed]
        if len(present) > 1:
            conflicts.append(
                {
                    "namespace": namespace,
                    "distributions": present,
                    "versions": {
                        m: installed[re.sub(r"[-_.]+", "-", m).lower()] for m in present
                    },
                    "message": (
                        f"mutually exclusive distributions share the {namespace!r} namespace: "
                        + ", ".join(present)
                    ),
                }
            )
    return {
        "status": STATUS_FAIL if conflicts else STATUS_PASS,
        "conflicts": conflicts,
        "groups": {ns: list(m) for ns, m in sorted(EXCLUSIVE_PROVIDER_GROUPS.items())},
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
    """Combined diagnostic status (retained for backward compatibility).

    This is a *diagnostic* roll-up only. It must never be used to decide whether
    a release may be promoted -- use :func:`resolve_gate` instead.
    """
    required = list(OFFLINE_REQUIRED_SECTIONS)
    if any(sections.get(key, {}).get("status") == STATUS_FAIL for key in required):
        return STATUS_FAIL
    if sections.get("runtime_verification", {}).get("status") in {STATUS_NOT_RUN, STATUS_BLOCKED_EXTERNAL}:
        return STATUS_INCOMPLETE
    if any(sections.get(key, {}).get("status") in {STATUS_NOT_RUN, STATUS_INCOMPLETE} for key in required):
        return STATUS_INCOMPLETE
    return STATUS_PASS


# ---------------------------------------------------------------------------
# V5 / NEW-208: explicit gate semantics
# ---------------------------------------------------------------------------


def resolve_gate(
    sections: Dict[str, Dict[str, Any]], gate: str
) -> Dict[str, Any]:
    """Resolve a named release gate into an explicit, non-ambiguous status.

    A gate is ``PASS`` only when every section it requires is ``PASS``.
    Everything else -- ``FAIL``, ``INCOMPLETE``, ``NOT_RUN``,
    ``BLOCKED_EXTERNAL``, ``WAIVED`` -- is not a pass, and the blocking sections
    are named so a reader can see exactly what is missing.
    """
    if gate == GATE_DIAGNOSTIC:
        return {
            "gate": gate,
            "status": _overall_status(sections),
            "required_sections": [],
            "blocking_sections": [],
            "reason": "diagnostic roll-up; not a release decision",
        }

    if gate == GATE_OFFLINE_RELEASE:
        required = list(OFFLINE_REQUIRED_SECTIONS)
    elif gate == GATE_RUNTIME_CERTIFICATION:
        required = list(RUNTIME_REQUIRED_SECTIONS)
    else:
        raise ValueError(f"unknown gate: {gate!r}")

    blocking: List[Dict[str, str]] = []
    saw_fail = False
    for name in required:
        status = sections.get(name, {}).get("status", STATUS_NOT_RUN)
        if status == STATUS_PASS:
            continue
        if status == STATUS_FAIL:
            saw_fail = True
        blocking.append({"section": name, "status": status})

    if not blocking:
        status = STATUS_PASS
        reason = f"all {len(required)} required sections are PASS"
    elif saw_fail:
        status = STATUS_FAIL
        reason = "one or more required sections failed"
    else:
        # INCOMPLETE / NOT_RUN / BLOCKED_EXTERNAL / WAIVED are all "not a pass",
        # but the aggregate is INCOMPLETE rather than FAIL because no required
        # section actively reported a failure.
        status = STATUS_INCOMPLETE
        reason = "one or more required sections are not PASS"

    return {
        "gate": gate,
        "status": status,
        "required_sections": required,
        "blocking_sections": blocking,
        "reason": reason,
    }


def gate_exit_code(gate_status: str) -> int:
    """Map a resolved gate status to a process exit code.

    Only ``PASS`` yields 0. This is the D19 fix: a green required check can no
    longer coexist with an INCOMPLETE or NOT_RUN release contract.
    """
    return 0 if gate_status == STATUS_PASS else 1


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
        "dependency_conflicts": dependency_conflicts(),
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
    gates = {name: resolve_gate(sections, name) for name in GATES}
    payload = {
        "schema_version": 2,
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
        # Diagnostic roll-up only. Release decisions use `gates`.
        "overall_status": _overall_status(sections),
        "gates": gates,
        "deferred_checks": [
            {
                "check": "live_carla_runtime_verification",
                "status": sections["runtime_verification"]["status"],
                "reason": sections["runtime_verification"]["reason"],
            }
        ],
    }
    return payload


# ---------------------------------------------------------------------------
# V5 / NEW-207 (E24): exact-candidate runtime identity contract
# ---------------------------------------------------------------------------

#: Fields a candidate release manifest must carry before any CARLA runtime work
#: may be certified. A missing field is a FAIL, never a warning: an unbound
#: runtime PASS is exactly the defect E24 closes.
CANDIDATE_MANIFEST_SCHEMA = "CARLA_CANDIDATE_RELEASE_MANIFEST/v1"
CANDIDATE_REQUIRED_FIELDS = (
    "repo_sha",
    "candidate_id",
    "xodr_path",
    "xodr_sha256",
    "map_registry_id",
    "carla_client_version",
    "carla_server_version",
    "ue_build",
    "import_package_sha256",
    "cooked_package_sha256",
    "cook_manifest_sha256",
    "runtime_map",
)

#: Overall states for a runtime certification receipt. BLOCKED_EXTERNAL and
#: NOT_RUN are explicitly NOT passes.
RUNTIME_CERT_STATES = (
    STATUS_PASS,
    STATUS_FAIL,
    "BLOCKED_EXTERNAL",
    "IDENTITY_MISMATCH",
    STATUS_NOT_RUN,
)


def _manifest_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_candidate_manifest(
    manifest_path: Path,
    *,
    expected_repo_sha: Optional[str] = None,
    expected_carla_version: str = "0.9.16",
    xodr_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate a candidate release manifest against the checked-out identity.

    This is the PRE-RUNTIME gate for E24. It runs before a CARLA server is even
    contacted, and any mismatch is a hard FAIL -- the workflow must not spend a
    live certification run against the wrong artifact.

    Checks: manifest exists; schema is the expected one; every required identity
    field is present and non-empty; the repository SHA matches the checked-out
    SHA; the XODR named by the manifest exists and hashes to the manifest's
    value; the CARLA build identity matches the accepted build.
    """
    problems: List[Dict[str, str]] = []
    result: Dict[str, Any] = {
        "schema": "CANDIDATE_IDENTITY_GATE/v1",
        "manifest_path": manifest_path.as_posix(),
        "expected_repo_sha": expected_repo_sha,
        "expected_carla_version": expected_carla_version,
        "state": "IDENTITY_MISMATCH",
        "problems": problems,
        "identity": {},
    }

    if not manifest_path.is_file():
        problems.append({"field": "manifest", "reason": f"manifest not found: {manifest_path.as_posix()}"})
        result["state"] = "IDENTITY_MISMATCH"
        return result

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append({"field": "manifest", "reason": f"manifest is unreadable/corrupt: {exc}"})
        return result
    if not isinstance(payload, dict):
        problems.append({"field": "manifest", "reason": "manifest is not a JSON object"})
        return result

    result["identity"] = payload
    result["manifest_sha256"] = _manifest_sha256(manifest_path)

    schema = str(payload.get("schema") or "")
    if schema != CANDIDATE_MANIFEST_SCHEMA:
        problems.append(
            {"field": "schema",
             "reason": f"expected {CANDIDATE_MANIFEST_SCHEMA!r}, manifest declares {schema!r}"}
        )

    for name in CANDIDATE_REQUIRED_FIELDS:
        value = payload.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append({"field": name, "reason": "required identity field is missing or empty"})

    # repository SHA binding
    if expected_repo_sha:
        actual = str(payload.get("repo_sha") or "").lower()
        if actual and actual != expected_repo_sha.lower():
            problems.append(
                {"field": "repo_sha",
                 "reason": f"manifest repo_sha {actual} does not match checked-out SHA {expected_repo_sha.lower()}"}
            )

    # XODR identity binding
    xodr_sha = str(payload.get("xodr_sha256") or "").strip().lower()
    xodr_rel = str(payload.get("xodr_path") or "").strip()
    if xodr_rel:
        base = xodr_root or manifest_path.parent
        candidate_xodr = Path(xodr_rel)
        if not candidate_xodr.is_absolute():
            candidate_xodr = base / candidate_xodr
        if not candidate_xodr.is_file():
            problems.append(
                {"field": "xodr_path", "reason": f"XODR named by the manifest does not exist: {xodr_rel}"}
            )
        else:
            actual_xodr = _manifest_sha256(candidate_xodr)
            result["xodr_sha256_recomputed"] = actual_xodr
            if xodr_sha and actual_xodr != xodr_sha:
                problems.append(
                    {"field": "xodr_sha256",
                     "reason": f"XODR hash mismatch: manifest {xodr_sha}, actual {actual_xodr}"}
                )

    # CARLA build identity
    if expected_carla_version:
        for field in ("carla_client_version", "carla_server_version"):
            value = str(payload.get(field) or "").strip()
            if value and expected_carla_version not in value:
                problems.append(
                    {"field": field,
                     "reason": f"{field} {value!r} does not match the accepted CARLA build {expected_carla_version}"}
                )

    result["state"] = STATUS_PASS if not problems else "IDENTITY_MISMATCH"
    return result


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
    # E24: pre-runtime candidate identity gate.
    parser.add_argument(
        "--validate-candidate",
        type=Path,
        default=None,
        metavar="MANIFEST",
        help="Validate a candidate release manifest against the checked-out identity "
             "(pre-runtime gate) and exit 0 only on PASS. Skips health-packet output.",
    )
    parser.add_argument(
        "--expected-repo-sha",
        default="",
        help="Checked-out repository SHA the candidate manifest must bind to",
    )
    parser.add_argument(
        "--expected-carla-version",
        default="0.9.16",
        help="Accepted CARLA build identity the candidate must declare",
    )
    parser.add_argument(
        "--xodr-root",
        type=Path,
        default=None,
        help="Base directory used to resolve a relative xodr_path from the manifest",
    )
    parser.add_argument(
        "--gate",
        choices=sorted(GATES),
        default=None,
        help=(
            "Release gate whose status determines the process exit code. Only PASS exits 0. "
            "'offline-release-gate' is satisfiable by GitHub-hosted CI; "
            "'runtime-certification-gate' requires a live CARLA server."
        ),
    )
    parser.add_argument(
        "--strict-release",
        action="store_true",
        help="Exit nonzero unless the diagnostic overall_status is PASS (legacy; prefer --gate)",
    )
    args = parser.parse_args(argv)

    # E24 pre-runtime identity gate: runs before any health-packet work so a
    # mismatch is reported as a distinct IDENTITY_MISMATCH state.
    if args.validate_candidate is not None:
        identity = validate_candidate_manifest(
            args.validate_candidate,
            expected_repo_sha=args.expected_repo_sha or None,
            expected_carla_version=args.expected_carla_version,
            xodr_root=args.xodr_root,
        )
        if args.json:
            sys.stdout.write(json.dumps(identity, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(
                f"[repo_health] candidate identity state={identity['state']} "
                f"problems={len(identity['problems'])}\n"
            )
            for problem in identity["problems"]:
                sys.stdout.write(f"  - {problem['field']}: {problem['reason']}\n")
        return 0 if identity["state"] == STATUS_PASS else 1

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
        for name in GATES:
            gate = payload["gates"][name]
            sys.stdout.write(
                f"[repo_health] gate={name} status={gate['status']} ({gate['reason']})\n"
            )

    # V5/NEW-208: an explicit --gate is authoritative. Fall back to the legacy
    # behaviour only when no gate was requested.
    if args.gate:
        gate = payload["gates"][args.gate]
        return gate_exit_code(gate["status"])

    if payload["overall_status"] == STATUS_FAIL:
        return 1
    if args.strict_release and payload["overall_status"] != STATUS_PASS:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
