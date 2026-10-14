#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal status normalization + the canonical per-run signal index (NEW-337).

The index is what ``run_summary.json`` publishes under ``signals``: for every
registered signal, its class, enablement, artifact path, artifact digest and
normalized status.  A consumer that reads ``run_summary.json`` can therefore
tell *why* a signal is absent (disabled / not required / missing / failing)
instead of inferring it from a missing key.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from ultimate_pipeline.signals.registry import (
    SIGNAL_REGISTRY,
    artifact_relpath,
    canonical_release_profile,
    is_signal_enabled,
    required_for_profile,
)

__all__ = [
    "STATUS_PASS",
    "STATUS_FAIL",
    "STATUS_INCOMPLETE",
    "STATUS_SKIP",
    "STATUS_MISSING",
    "STATUS_BLOCKED_EXTERNAL",
    "STATUS_NOT_APPLICABLE",
    "normalize_signal_status",
    "build_signal_index",
    "signal_ids_for_verdict",
]

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_SKIP = "SKIP"
STATUS_MISSING = "MISSING"
STATUS_BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

_FAILISH = {"fail", "failed", "failure", "error", "errored", "not_ok"}
_SKIPISH = {
    "skip",
    "skipped",
    "skipped_by_env",
    "not_run",
    "not_run_yet",
    "disabled",
    "conditional",
}
_BLOCKED = {"blocked_external", "blocked", "external_blocked"}


def _sha256_file(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _load(path: str) -> tuple[Any, str | None]:
    """Return ``(payload, error)``; payload is None when unreadable/absent."""
    if not os.path.exists(path):
        return None, None
    if os.path.getsize(path) == 0:
        return None, "empty file"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return json.load(handle), None
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return None, f"unreadable: {type(exc).__name__}: {exc}"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "ok", "pass"}
    return False


def _status_from_payload(payload: Any) -> str | None:
    """Best-effort extraction of a normalized status from an artifact body."""
    if not isinstance(payload, dict):
        return None

    # Explicit status/verdict fields first.
    for key in ("status", "verdict", "decision", "state"):
        if key in payload:
            raw = payload[key]
            if raw is None:
                continue
            text = str(raw).strip().lower()
            if text in _FAILISH:
                return STATUS_FAIL
            if text in _SKIPISH:
                return STATUS_SKIP
            if text in _BLOCKED:
                return STATUS_BLOCKED_EXTERNAL
            if text in {"pass", "ok", "passed", "success", "complete", "completed"}:
                return STATUS_PASS
            if text in {"incomplete", "partial", "unknown", "not_run"}:
                return STATUS_INCOMPLETE

    if "ok" in payload:
        return STATUS_PASS if _truthy(payload["ok"]) else STATUS_FAIL

    # Nested summary (validation_report_full.json style).
    summary = payload.get("summary")
    if isinstance(summary, dict) and ("ok" in summary or "status" in summary):
        nested = _status_from_payload(summary)
        if nested:
            return nested

    return None


def normalize_signal_status(
    signal_id: str,
    payload: Any,
    *,
    error: str | None = None,
) -> str:
    """Map a signal artifact body to one of the canonical status constants.

    Registry ``pass_states`` / ``failure_states`` / ``missing_states`` drive the
    mapping so a signal declaring (say) ``["ok"]`` as a pass state is honoured
    without hard-coding its name here.
    """
    entry = SIGNAL_REGISTRY.get(signal_id, {})
    pass_states = {str(s).strip().lower() for s in entry.get("pass_states", [])}
    failure_states = {str(s).strip().lower() for s in entry.get("failure_states", [])}

    if payload is None:
        if error:
            # An artifact that exists but cannot be read is *worse* than absent:
            # it means a producer wrote something a consumer cannot trust.
            return STATUS_FAIL
        return STATUS_MISSING

    # Signal-specific structural rules that no generic field read captures.
    if signal_id == "CUMULATIVE_GATES" or signal_id == "WRAPPED_GATE_FAILURES":
        if isinstance(payload, dict):
            return STATUS_PASS if not payload else STATUS_FAIL
        return STATUS_FAIL

    if signal_id == "CUMULATIVE_STAGE_GATES":
        if isinstance(payload, dict):
            try:
                failed = int(payload.get("failed", 0) or 0)
            except Exception:  # noqa: BLE001
                return STATUS_INCOMPLETE
            # ``total == 0`` is not itself a failure here: whether the expected
            # gates ran at all is PIPELINE_HEALTH's contract (NEW-335).  This
            # signal's contract is only "no gate that ran may have failed".
            return STATUS_PASS if failed == 0 else STATUS_FAIL
        return STATUS_FAIL

    if signal_id in {"MAP_ACCEPTANCE", "EXPERIMENT_READINESS"}:
        if isinstance(payload, dict):
            valid = payload.get("valid_for_experiments")
            if valid is None:
                valid = payload.get("valid")
            if valid is None:
                return STATUS_INCOMPLETE
            return STATUS_PASS if _truthy(valid) else STATUS_FAIL
        return STATUS_FAIL

    if signal_id == "FINAL_ARTIFACT_RECEIPT":
        if isinstance(payload, dict):
            sha = payload.get("final_artifact_sha256")
            if not sha:
                return STATUS_INCOMPLETE
            fp = payload.get("structure_fingerprint")
            if not (isinstance(fp, dict) and fp.get("sha256")):
                return STATUS_INCOMPLETE
            return STATUS_PASS
        return STATUS_FAIL

    if signal_id == "ENVIRONMENT_SNAPSHOT":
        if isinstance(payload, dict) and payload.get("schema"):
            return STATUS_PASS
        return STATUS_INCOMPLETE

    if signal_id == "PIPELINE_HEALTH":
        if isinstance(payload, dict):
            return STATUS_PASS if _truthy(payload.get("overall_ok")) else STATUS_FAIL
        return STATUS_FAIL

    if signal_id in {"RUN_SUMMARY", "VALIDATION_REPORT"}:
        if isinstance(payload, dict) and payload:
            return STATUS_PASS
        return STATUS_INCOMPLETE

    if signal_id == "DETERMINISM_FINGERPRINT":
        if isinstance(payload, dict) and payload.get("final_xodr"):
            return STATUS_PASS
        return STATUS_INCOMPLETE

    if signal_id == "G6_HYGIENE":
        if isinstance(payload, dict):
            if str(payload.get("status", "")).strip().upper() == "INCOMPLETE":
                return STATUS_INCOMPLETE
            if "ok" in payload:
                return STATUS_PASS if _truthy(payload.get("ok")) else STATUS_FAIL
        return STATUS_INCOMPLETE

    if signal_id == "DOMAIN_GAP":
        if isinstance(payload, dict):
            raw = str(payload.get("status", "")).strip().lower()
            if raw in _BLOCKED:
                return STATUS_BLOCKED_EXTERNAL
            if "ok" in payload and "status" not in payload:
                return STATUS_PASS if _truthy(payload.get("ok")) else STATUS_FAIL
        normalized = _status_from_payload(payload)
        if normalized:
            return normalized
        return STATUS_INCOMPLETE

    if signal_id == "SUCCESS_MARKER":
        # Presence of an OK header is the only meaningful content check.
        if isinstance(payload, str):
            return STATUS_PASS if payload.startswith("OK ") else STATUS_FAIL
        if isinstance(payload, dict) and payload.get("ok"):
            return STATUS_PASS
        return STATUS_FAIL

    generic = _status_from_payload(payload)
    if generic is None:
        # No recognizable verdict field: a governed signal without a verdict is
        # NOT a pass.  Record it as incomplete so it is visible either way.
        generic = STATUS_INCOMPLETE

    if generic == STATUS_PASS and pass_states and "pass" not in pass_states:
        # pass_states were given but do not include the generic "pass" token --
        # still accept the generic PASS; pass_states only extend the vocabulary.
        pass
    if generic == STATUS_FAIL and failure_states and "fail" not in failure_states:
        pass
    return generic


def signal_ids_for_verdict(
    *,
    profile: str,
    settings: Any = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Signals the final-run verdict must evaluate for ``profile``.

    ``SUCCESS_MARKER`` and producer-specific signals whose consumer is not the
    verdict (e.g. ``RQ1_DETERMINISM``, consumed by the five-run matrix) are
    excluded -- they belong to their own consumer's contract.
    """
    out: list[str] = []
    for sid, entry in SIGNAL_REGISTRY.items():
        if entry.get("consumer") != "final_run_verdict":
            continue
        if sid == "SUCCESS_MARKER":
            continue
        if sid == "FINAL_RUN_VERDICT":
            continue  # the verdict does not gate on itself
        out.append(sid)
    return sorted(out)


def build_signal_index(
    out_dir: str | os.PathLike[str],
    *,
    profile: str,
    settings: Any = None,
    env: dict[str, str] | None = None,
    final_xodr: str | None = None,
) -> dict[str, Any]:
    """Registry-derived signal index for ``run_summary.json`` (NEW-337)."""
    root = str(out_dir)
    profile = canonical_release_profile(profile)
    required = set(required_for_profile(profile))
    index: dict[str, Any] = {}

    for sid in sorted(SIGNAL_REGISTRY):
        entry = SIGNAL_REGISTRY[sid]
        rel = artifact_relpath(sid)
        enabled = is_signal_enabled(sid, settings=settings, env=env)
        path = os.path.join(root, *rel.split("/")) if rel else None
        payload = None
        error = None
        present = False
        digest = None
        if path:
            present = os.path.exists(path)
            if present:
                payload, error = _load(path)
                digest = _sha256_file(path)

        if not enabled:
            status = STATUS_NOT_APPLICABLE
        elif not present:
            status = STATUS_MISSING
        else:
            if payload is None and error is None:
                # Present but parsed to a bare JSON null: the artifact exists
                # and carries no verdict at all.  That is not a pass.
                error = "payload parsed to null"
            status = normalize_signal_status(sid, payload, error=error)

        index[sid] = {
            "signal_id": sid,
            "class": entry.get("class"),
            "enabled": bool(enabled),
            "required_for_profile": sid in required,
            "consumer": entry.get("consumer"),
            "consumer_action": entry.get("consumer_action"),
            "artifact": rel,
            "present": bool(present),
            "sha256": digest,
            "status": status,
            "read_error": error,
        }

    return {
        "schema": "signal_index/v1",
        "release_profile": profile,
        "out_dir": root,
        "signals": index,
        "counts": {
            "total": len(index),
            "enabled": sum(1 for v in index.values() if v["enabled"]),
            "present": sum(1 for v in index.values() if v["present"]),
            "pass": sum(1 for v in index.values() if v["status"] == STATUS_PASS),
            "missing": sum(1 for v in index.values() if v["status"] == STATUS_MISSING),
            "fail": sum(1 for v in index.values() if v["status"] == STATUS_FAIL),
        },
    }
