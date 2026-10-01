#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static dead-signal auditor for the governed pipeline signal registry (NEW-338).

A "dead signal" is a registry entry that no production code can ever satisfy:
its producer does not resolve, nothing writes its artifact, or its enablement
predicate names a setting/env var that exists nowhere.  Such a signal would be
read forever as ``MISSING`` (or worse, silently ``NOT_APPLICABLE``), which is
exactly the class of defect this campaign exists to eliminate.

The auditor is static: it never starts CARLA and never runs the pipeline, so it
can gate a change before any runtime verification is attempted.  It may be
pointed at a run directory with ``--out-dir`` to additionally report each
signal's *runtime* status there (missing artifacts, failing artifacts).

Exit codes
----------
0   no dead signals (advisories may still be listed)
1   at least one dead signal (or a malformed registry) was found
2   the registry itself could not be loaded/audited

Usage
-----
    python tools/audit_pipeline_signal_graph.py
    python tools/audit_pipeline_signal_graph.py --out-dir reports/<run>/final
    python tools/audit_pipeline_signal_graph.py --json-out audit.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

#: Production roots that may legitimately write a signal artifact.  Tests,
#: reports, archives, vendored copies (build/, submission/, work/) are excluded:
#: an artifact only referenced there is dead for the running pipeline.
PRODUCTION_ROOTS = ("ultimate_pipeline", "tools")

#: Modules that *describe* signals but never produce their evidence.  A
#: filename that appears only in these is not a writer.
NON_WRITER_MODULES = (
    os.path.join("ultimate_pipeline", "signals"),
    os.path.join("ultimate_pipeline", "contracts", "stage_capabilities.py"),
)

#: ``enabled_by`` tokens this auditor accepts without a settings/env lookup.
_PSEUDO_PREDICATES = {"windows"}


def _iter_production_sources() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for root_name in PRODUCTION_ROOTS:
        root = WORKTREE / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = str(path.relative_to(WORKTREE))
            if any(rel.startswith(n) for n in NON_WRITER_MODULES):
                continue
            try:
                out.append((rel, path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return out


def _resolve_producer(producer: str) -> tuple[str, str | None]:
    """Return ``(status, detail)`` for a registry producer string.

    ``status`` is one of ``callable`` / ``module`` / ``unresolved``.
    """
    core = (producer or "").strip()
    if not core:
        return "unresolved", "producer string is empty"
    # Producers historically carried a human note in parentheses; strip it so
    # the resolvable path is unambiguous.
    core = re.sub(r"\s*\([^)]*\)$", "", core).strip()
    mod_name, _, attr = core.rpartition(".")
    if not mod_name:
        return "unresolved", f"no module in producer path: {core!r}"
    try:
        module = importlib.import_module(mod_name)
    except Exception as exc:  # noqa: BLE001
        return "unresolved", f"import failed for {mod_name}: {type(exc).__name__}: {exc}"
    if not attr:
        return "module", mod_name
    target = getattr(module, attr, None)
    if callable(target):
        return "callable", core
    # Methods on a pipeline class declared in that module.
    for name in dir(module):
        obj = getattr(module, name, None)
        if isinstance(obj, type) and getattr(obj, attr, None) is not None:
            return "callable", f"{mod_name}.{name}.{attr}"
    return "unresolved", f"{core} not found in {mod_name}"


def _writer_needles(artifact_relpath: str) -> list[str]:
    """Filename needles a writer source may reasonably contain.

    The exact basename is always used.  Artifacts with a numeric component
    (``receipt_run_00.json``) are written through an f-string, so the numeric
    part is additionally stripped to a prefix -- but only for such names, so a
    bare stem can never make an unrelated module look like a writer.
    """
    base = artifact_relpath.replace("\\", "/").split("/")[-1]
    needles = {base}
    stem = base.split(".")[0]
    if stem and re.search(r"\d", stem):
        stripped = re.sub(r"\d+", "", stem)
        if len(stripped) >= 4:
            needles.add(stripped)
    return [n for n in needles if len(n) >= 4]


def _writer_sites(artifact: str, sources: list[tuple[str, str]]) -> list[str]:
    needles = _writer_needles(artifact)
    hits: list[str] = []
    for rel, text in sources:
        if any(needle in text for needle in needles):
            hits.append(rel)
    return hits


def _predicate_names(entry: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for raw in entry.get("enabled_by") or []:
        text = str(raw).strip()
        if text.lower().startswith("not "):
            text = text[4:].strip()
        if "=" in text:
            text = text.split("=", 1)[0].strip()
        if text:
            names.append(text)
    return names


def _known_predicate(name: str, settings_attrs: set[str], sources: list[tuple[str, str]]) -> tuple[bool, str]:
    if name in _PSEUDO_PREDICATES:
        return True, "pseudo predicate"
    if name in settings_attrs:
        return True, "settings attribute"
    # Environment contracts are read through os.getenv/os.environ somewhere in
    # production code, or follow the UP_* convention.
    needle = f'"{name}"'
    for _, text in sources:
        if needle in text or f"'{name}'" in text:
            return True, "referenced in production source"
    if name.startswith("UP_"):
        return True, "UP_* environment contract"
    return False, "not a settings attribute and never referenced in production source"


def _settings_attributes() -> set[str]:
    try:
        from ultimate_pipeline.config.settings import Settings

        return {k for k in dir(Settings) if not k.startswith("__")}
    except Exception:  # noqa: BLE001
        return set()


def audit(*, out_dir: str | None = None) -> dict[str, Any]:
    from ultimate_pipeline.signals.registry import (
        SIGNAL_REGISTRY,
        artifact_relpath,
        canonical_release_profile,
        enabled_signals,
        required_for_profile,
    )

    sources = _iter_production_sources()
    settings_attrs = _settings_attributes()

    findings: list[dict[str, Any]] = []
    dead: list[str] = []
    runtime_missing: list[str] = []
    artifact_owners: dict[str, list[str]] = {}

    for sid in sorted(SIGNAL_REGISTRY):
        entry = SIGNAL_REGISTRY[sid]
        artifact = entry.get("artifact") or ""
        rel = artifact_relpath(sid)
        producer_status, producer_detail = _resolve_producer(entry.get("producer", ""))
        writers = _writer_sites(rel or artifact, sources)

        pred_results = []
        for name in _predicate_names(entry):
            ok, why = _known_predicate(name, settings_attrs, sources)
            pred_results.append({"name": name, "known": ok, "detail": why})

        # Static problems make a signal "dead" (nothing could ever satisfy
        # it).  Runtime problems are reported separately: an empty or fresh out
        # dir legitimately has missing artifacts, and that is a property of the
        # run under audit, not of the registry.
        problems: list[str] = []
        runtime_problems: list[str] = []
        if producer_status == "unresolved":
            problems.append(f"producer_unresolved: {producer_detail}")
        if not writers:
            problems.append("artifact_never_written: no production source references the artifact")
        unknown_preds = [str(p["name"]) for p in pred_results if not p["known"]]
        if unknown_preds:
            problems.append(f"unknown_predicates: {', '.join(unknown_preds)}")
        if not rel:
            problems.append("artifact_path_unresolvable")

        if rel:
            artifact_owners.setdefault(rel, []).append(sid)

        finding = {
            "signal_id": sid,
            "artifact": artifact,
            "artifact_relpath": rel,
            "class": entry.get("class"),
            "consumer": entry.get("consumer"),
            "enabled_by": entry.get("enabled_by") or [],
            "required_release_profiles": entry.get("required_release_profiles") or [],
            "producer_status": producer_status,
            "producer_detail": producer_detail,
            "writer_sites": writers,
            "predicates": pred_results,
            "problems": problems,
            "runtime_problems": runtime_problems,
        }

        if out_dir:
            from ultimate_pipeline.signals.index import normalize_signal_status
            from ultimate_pipeline.signals.registry import is_signal_enabled

            path = Path(out_dir) / rel if rel else None
            enabled = is_signal_enabled(sid, env=dict(os.environ))
            present = bool(path and path.is_file())
            payload: Any = None
            error = None
            if present and path is not None:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                except Exception as exc:  # noqa: BLE001
                    error = f"{type(exc).__name__}: {exc}"
            if not enabled:
                status = "NOT_APPLICABLE"
            elif not present:
                status = "MISSING"
            else:
                status = normalize_signal_status(sid, payload, error=error)
            finding["runtime"] = {
                "enabled": bool(enabled),
                "present": bool(present),
                "status": status,
                "path": str(path) if path else None,
            }
            if enabled and status == "MISSING" and entry.get(
                "missing_policy", "FAIL"
            ).upper().startswith("FAIL"):
                runtime_problems.append(
                    "enabled_but_missing: required evidence absent from out_dir"
                )
                runtime_missing.append(sid)

        findings.append(finding)
        if problems:
            # Static problems only: unresolved producers, artifacts no
            # production source writes, predicates nothing defines.
            dead.append(sid)

    duplicates = {k: v for k, v in artifact_owners.items() if len(v) > 1}

    profiles = sorted({canonical_release_profile(p) for p in ("structural_release", "visual_build", "perception_research", "debug")})
    pack_shapes: dict[str, Any] = {}
    for profile in profiles:
        try:
            pack_shapes[profile] = sorted(required_for_profile(profile))
        except Exception as exc:  # noqa: BLE001
            pack_shapes[profile] = f"ERROR: {type(exc).__name__}: {exc}"

    enabled_now = []
    try:
        enabled_now = sorted(enabled_signals(env=dict(os.environ)))
    except Exception:  # noqa: BLE001
        enabled_now = []

    report = {
        "schema": "pipeline_signal_graph_audit/v1",
        "signal_count": len(SIGNAL_REGISTRY),
        "scanned_sources": len(sources),
        "dead_signals": sorted(set(dead)),
        "dead_count": len(set(dead)),
        "runtime_missing_signals": sorted(set(runtime_missing)),
        "shared_artifacts": duplicates,
        "required_by_profile": pack_shapes,
        "enabled_signals_now": enabled_now,
        "out_dir": out_dir,
        "findings": findings,
    }
    report["status"] = "FAIL" if report["dead_count"] else "PASS"
    return report


#: Public alias -- the resolver is part of this tool's contract for tests.
resolve_producer = _resolve_producer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", default=None, help="optional run directory for runtime status")
    parser.add_argument("--json-out", default=None, help="write the full report to this path")
    args = parser.parse_args()

    try:
        report = audit(out_dir=args.out_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"[SIGNAL_AUDIT] registry could not be audited: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        f"[SIGNAL_AUDIT] status={report['status']} signals={report['signal_count']} "
        f"dead={report['dead_count']} scanned_sources={report['scanned_sources']}"
    )
    for sid in report["dead_signals"]:
        finding = next(f for f in report["findings"] if f["signal_id"] == sid)
        for problem in finding["problems"]:
            print(f"  DEAD {sid}: {problem}")
    if report["shared_artifacts"]:
        for rel, owners in sorted(report["shared_artifacts"].items()):
            print(f"  SHARED {rel}: {', '.join(owners)}")
    if args.out_dir:
        for sid in report["runtime_missing_signals"]:
            finding = next(f for f in report["findings"] if f["signal_id"] == sid)
            runtime = finding.get("runtime") or {}
            print(f"  RUNTIME {sid}: {runtime.get('status')} -> {runtime.get('path')}")
        print(
            f"[SIGNAL_AUDIT] runtime_missing={len(report['runtime_missing_signals'])} "
            f"for out_dir={args.out_dir}"
        )
    return 1 if report["dead_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
