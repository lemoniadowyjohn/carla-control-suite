#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The canonical final run verdict (NEW-334, NEW-343).

``final_run_verdict.json`` is the SOLE run authority: ``SUCCESS.txt`` may only
exist when this verdict's status is ``PASS``, ``run_status.json`` may only be
``ok`` when the pack verifies, and no other artifact is allowed to substitute
for it.  The verdict is computed *from* the registry, so adding a signal to the
registry is what makes it count -- there is no second, private list.

Verdict vocabulary (also mirrored in :data:`VERDICT_VOCABULARY`):

``PASS``
    every enabled, required signal is present and normalizes to PASS, and no
    evidence-persistence failure was recorded during the run.
``FAIL``
    at least one required signal is missing, malformed or failing.
``BLOCKED_EXTERNAL``
    no required signal failed, but at least one required external dependency
    reported ``BLOCKED_EXTERNAL`` (CARLA unreachable, manual reference absent).
``NOT_EVALUATED``
    the verdict could not be computed at all (registry/artifact unreadable).
    Never a pass; callers must treat it as ``FAIL``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from ultimate_pipeline.signals.index import (
    STATUS_BLOCKED_EXTERNAL,
    STATUS_FAIL,
    STATUS_MISSING,
    STATUS_NOT_APPLICABLE,
    STATUS_PASS,
    STATUS_SKIP,
    build_signal_index,
    normalize_signal_status,
    signal_ids_for_verdict,
)
from ultimate_pipeline.signals.registry import (
    SIGNAL_REGISTRY,
    SignalClass,
    artifact_relpath,
    canonical_release_profile,
    is_signal_enabled,
    registry_sha256,
)
from ultimate_pipeline.signals.writer import (
    persistence_failures,
    write_governed_signal,
)

__all__ = [
    "VERDICT_SCHEMA",
    "VERDICT_VOCABULARY",
    "VERDICT_PASS",
    "VERDICT_FAIL",
    "VERDICT_BLOCKED_EXTERNAL",
    "VERDICT_NOT_EVALUATED",
    "compute_final_run_verdict",
    "write_final_run_verdict",
    "canonical_release_profile",
]

VERDICT_SCHEMA = "final_run_verdict/v1"
VERDICT_VOCABULARY = ("PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_EVALUATED")

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
VERDICT_NOT_EVALUATED = "NOT_EVALUATED"

#: ``canonical_release_profile`` (uppercase settings profile -> registry
#: vocabulary) lives in the registry so every consumer shares one mapping; it
#: is re-exported here because it is part of this module's public surface.

def _load(path: str) -> tuple[Any, str | None]:
    if not os.path.exists(path):
        return None, None
    if os.path.getsize(path) == 0:
        return None, "empty file"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return json.load(handle), None
    except Exception as exc:  # noqa: BLE001
        return None, f"unreadable: {type(exc).__name__}: {exc}"


def _sha256_file(path: str) -> str | None:
    import hashlib

    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "ok"}
    return False


def _blocking_status_for(
    signal_id: str,
    status: str,
    *,
    enabled: bool,
    required: bool,
) -> str | None:
    """Return how a normalized status blocks, or None when it does not."""
    if not enabled:
        return None
    entry = SIGNAL_REGISTRY[signal_id]
    cls = entry.get("class")

    if cls == SignalClass.ADVISORY.value or cls == SignalClass.INFORMATIONAL.value:
        return None

    if status == STATUS_NOT_APPLICABLE:
        return None

    if status == STATUS_PASS:
        return None

    if status == STATUS_BLOCKED_EXTERNAL:
        # External blockers block only for profiles that require the signal;
        # otherwise they are recorded as advisories.
        return VERDICT_BLOCKED_EXTERNAL if required else None

    if status == STATUS_SKIP:
        skip_policy = str(entry.get("skip_policy", "NEVER")).upper()
        if skip_policy.startswith("NEVER"):
            return VERDICT_FAIL if required else None
        if skip_policy.startswith("BLOCKED_EXTERNAL"):
            return VERDICT_BLOCKED_EXTERNAL if required else None
        # RECORD_IF_DISABLED / RECORD -> advisory
        return None

    # FAIL / INCOMPLETE / MISSING and anything unrecognized.
    missing_policy = str(entry.get("missing_policy", "FAIL")).upper()
    if status == STATUS_MISSING:
        if missing_policy.startswith("BLOCKED_EXTERNAL"):
            return VERDICT_BLOCKED_EXTERNAL if required else None
        if missing_policy.startswith("RECORD") or missing_policy.startswith("FAIL_IF"):
            return None
    return VERDICT_FAIL if required else None


def compute_final_run_verdict(
    out_dir: str | os.PathLike[str],
    *,
    profile: str | None = None,
    settings: Any = None,
    env: dict[str, str] | None = None,
    final_xodr: str | None = None,
) -> dict[str, Any]:
    """Compute (without writing) ``final_run_verdict.json``'s payload."""
    root = str(out_dir)
    resolved_profile = canonical_release_profile(
        profile
        if profile is not None
        else getattr(settings, "RELEASE_PROFILE", "structural_release")
    )

    blocking_failures: list[dict[str, Any]] = []
    blocked_external: list[dict[str, Any]] = []
    advisories: list[dict[str, Any]] = []
    evaluated: list[str] = []

    env_map = dict(os.environ) if env is None else env
    candidate_ids = signal_ids_for_verdict(profile=resolved_profile)

    identity_valid = False
    readiness_valid = False
    identity_detail: dict[str, Any] = {}
    readiness_detail: dict[str, Any] = {}

    receipt_payload: dict[str, Any] | None = None
    receipt_status = STATUS_MISSING
    acceptance_payload: dict[str, Any] | None = None
    acceptance_status = STATUS_MISSING
    experiment_status: str | None = None

    for sid in candidate_ids:
        entry = SIGNAL_REGISTRY[sid]
        enabled = is_signal_enabled(sid, settings=settings, env=env_map)
        required = resolved_profile in entry.get("required_release_profiles", [])
        rel = artifact_relpath(sid)
        path = os.path.join(root, *rel.split("/")) if rel else None
        payload: Any = None
        error = None
        present = bool(path) and path is not None and os.path.exists(path)
        if present and path is not None:
            payload, error = _load(path)

        if not enabled:
            status = STATUS_NOT_APPLICABLE
        elif not present:
            status = STATUS_MISSING
        else:
            status = normalize_signal_status(sid, payload, error=error)

        record = {
            "signal_id": sid,
            "class": entry.get("class"),
            "enabled": bool(enabled),
            "required": bool(required),
            "artifact": rel,
            "status": status,
            "consumer_action": entry.get("consumer_action"),
            "read_error": error,
        }

        # NEW-343: identity and experiment-readiness are tracked separately, and
        # the receipt's claims are cross-checked against the bytes on disk so a
        # self-consistent-but-stale receipt cannot stand in for a fresh one.
        if sid == "FINAL_ARTIFACT_RECEIPT":
            receipt_payload = payload if isinstance(payload, dict) else None
            receipt_status = status
        elif sid == "MAP_ACCEPTANCE":
            acceptance_payload = payload if isinstance(payload, dict) else None
            acceptance_status = status
        elif sid == "EXPERIMENT_READINESS":
            experiment_status = status

        blocker = _blocking_status_for(sid, status, enabled=enabled, required=required)
        if blocker == VERDICT_FAIL:
            blocking_failures.append(record)
        elif blocker == VERDICT_BLOCKED_EXTERNAL:
            blocked_external.append(record)
        elif status == STATUS_PASS and enabled:
            evaluated.append(sid)
        elif enabled and status != STATUS_NOT_APPLICABLE:
            # Non-blocking (advisory class, RECORD policy, or not required for
            # this profile) but not passing: surfaced, never silently ignored.
            advisories.append(record)

    # --- NEW-343: identity vs experiment-readiness cross-checks -------------
    # Identity   == "the receipt's recorded digests match the bytes on disk".
    # Readiness  == "map_acceptance says fit for experiments".
    # Both are reported separately, and either one failing blocks a PASS; a
    # structurally valid artifact must never stand in for experiment readiness
    # (or vice versa).
    identity_problems: list[str] = []
    readiness_problems: list[str] = []

    receipt_path = os.path.join(root, "final_artifact_receipt.json")
    acceptance_path = os.path.join(root, "map_acceptance.json")

    # A receipt that does not normalize to PASS is already a blocking signal;
    # only run the byte-level cross-checks when the receipt itself is readable.
    if receipt_status == STATUS_PASS and isinstance(receipt_payload, dict):
        recorded_final = str(receipt_payload.get("final_artifact_sha256") or "").strip()
        candidate_final = final_xodr or receipt_payload.get("final_artifact_path")
        if not recorded_final:
            identity_problems.append("receipt has no final_artifact_sha256")
        if isinstance(candidate_final, str) and candidate_final:
            final_path = (
                candidate_final
                if os.path.isabs(candidate_final)
                else os.path.join(root, candidate_final)
            )
            if os.path.exists(final_path):
                actual_final = _sha256_file(final_path)
                if recorded_final and actual_final and actual_final != recorded_final:
                    identity_problems.append(
                        "final_artifact_sha256 does not match the final XODR on disk"
                    )
            else:
                identity_problems.append(
                    f"receipt final artifact not found on disk: {candidate_final}"
                )
        acceptance_claim = receipt_payload.get("acceptance_receipt") or {}
        recorded_acc = str(
            acceptance_claim.get("sha256") or receipt_payload.get("map_acceptance_sha256") or ""
        ).strip()
        if recorded_acc:
            actual_acc = _sha256_file(acceptance_path) if os.path.exists(acceptance_path) else None
            if actual_acc is None:
                identity_problems.append(
                    "map_acceptance.json referenced by the receipt is missing"
                )
            elif actual_acc != recorded_acc:
                identity_problems.append(
                    "acceptance_receipt.sha256 does not match map_acceptance.json on disk"
                )
        elif os.path.exists(acceptance_path):
            identity_problems.append("receipt records no acceptance_receipt.sha256")

    if acceptance_status != STATUS_PASS:
        readiness_problems.append(f"map_acceptance.json status={acceptance_status}")
    if experiment_status is not None and experiment_status != STATUS_PASS:
        readiness_problems.append(f"EXPERIMENT_READINESS status={experiment_status}")

    receipt_required = resolved_profile in SIGNAL_REGISTRY["FINAL_ARTIFACT_RECEIPT"].get(
        "required_release_profiles", []
    )
    acceptance_required = resolved_profile in SIGNAL_REGISTRY["MAP_ACCEPTANCE"].get(
        "required_release_profiles", []
    )

    identity_valid = receipt_status == STATUS_PASS and not identity_problems
    readiness_valid = not readiness_problems
    identity_detail = {
        "receipt_artifact": "final_artifact_receipt.json",
        "receipt_status": receipt_status,
        "problems": identity_problems,
        "receipt_sha256_present": bool(
            isinstance(receipt_payload, dict) and receipt_payload.get("final_artifact_sha256")
        ),
        "exists": os.path.exists(receipt_path),
    }
    readiness_detail = {
        "acceptance_artifact": "map_acceptance.json",
        "acceptance_status": acceptance_status,
        "experiment_readiness_status": experiment_status,
        "problems": readiness_problems,
        "required_for_profile": acceptance_required,
        "valid_for_experiments": bool(
            isinstance(acceptance_payload, dict)
            and _truthy(acceptance_payload.get("valid_for_experiments"))
        ),
    }

    if identity_problems:
        record = {
            "signal_id": "FINAL_ARTIFACT_RECEIPT",
            "class": SignalClass.HARD_GATE.value,
            "artifact": "final_artifact_receipt.json",
            "status": STATUS_FAIL,
            "cross_check": "identity",
            "error": "; ".join(identity_problems),
        }
        (blocking_failures if receipt_required else advisories).append(record)
    # NOTE: readiness problems are NOT appended here.  MAP_ACCEPTANCE and
    # EXPERIMENT_READINESS are themselves evaluated in the loop above, so their
    # failures are already recorded exactly once under their own signal ids;
    # ``readiness_valid`` below is the NEW-343 report of the same evidence.

    # Evidence persistence failures (NEW-349) are blocking by construction: a
    # signal whose artifact could not be durably written cannot be verified.
    persist = persistence_failures()
    for failure in persist:
        blocking_failures.append(
            {
                "signal_id": failure.get("signal_id"),
                "class": "EVIDENCE_PERSISTENCE_FAILURE",
                "artifact": failure.get("path"),
                "status": STATUS_FAIL,
                "error": failure.get("error"),
                "timestamp_utc": failure.get("timestamp_utc"),
            }
        )

    # Canonical health gate: the health summary is authoritative for gate
    # aggregation (NEW-335).  When it exists, its own opinion is merged in so a
    # "no gate evidence" run cannot be reported as PASS by this verdict alone.
    health_path = os.path.join(root, "pipeline_health_summary.json")
    health, health_err = _load(health_path)
    health_status = None
    if os.path.exists(health_path):
        health_status = normalize_signal_status("PIPELINE_HEALTH", health, error=health_err)

    if blocking_failures:
        status = VERDICT_FAIL
    elif blocked_external:
        status = VERDICT_BLOCKED_EXTERNAL
    elif health_status is None and os.path.exists(health_path) is False:
        # Health summary is mandatory for every profile that requires it; if the
        # registry requires it and it is absent, that is a hard failure.
        required_health = resolved_profile in SIGNAL_REGISTRY["PIPELINE_HEALTH"].get(
            "required_release_profiles", []
        )
        status = VERDICT_FAIL if required_health else VERDICT_PASS
        if required_health:
            blocking_failures.append(
                {
                    "signal_id": "PIPELINE_HEALTH",
                    "class": SignalClass.HARD_GATE.value,
                    "artifact": "pipeline_health_summary.json",
                    "status": STATUS_MISSING,
                    "error": "pipeline health summary was never written",
                }
            )
    else:
        status = VERDICT_PASS

    index = build_signal_index(
        root,
        profile=resolved_profile,
        settings=settings,
        env=env_map,
        final_xodr=final_xodr,
    )

    verdict_payload: dict[str, Any] = {
        "schema": VERDICT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "release_profile": resolved_profile,
        "status": status,
        "run_status_ok": status == VERDICT_PASS,
        "registry_sha256": registry_sha256(),
        "evidence_persistence_failures": persist,
        "blocking_failures": blocking_failures,
        "blocked_external": blocked_external,
        "advisories": advisories,
        "required_signals": sorted(
            sid
            for sid in candidate_ids
            if SIGNAL_REGISTRY[sid].get("required_release_profiles") and resolved_profile
            in SIGNAL_REGISTRY[sid]["required_release_profiles"]
        ),
        "evaluated_signals": sorted(set(evaluated)),
        "verdict_vocabulary": list(VERDICT_VOCABULARY),
        "authority": {
            "artifact": "final_run_verdict.json",
            "rule": (
                "SUCCESS.txt is present if and only if this verdict is PASS, "
                "run_status.json reports ok, and verify_run_pack() passes."
            ),
        },
        # NEW-343: identity and readiness are distinct, separately-reported
        # properties; neither may stand in for the other.
        "final_artifact_identity_valid": bool(identity_valid),
        "experiment_readiness_valid": bool(readiness_valid),
        "identity_detail": identity_detail,
        "readiness_detail": readiness_detail,
        "pipeline_health_status": health_status,
        "signal_index": index["signals"],
        "signal_counts": index["counts"],
    }
    return verdict_payload


def write_final_run_verdict(
    out_dir: str | os.PathLike[str],
    *,
    profile: str | None = None,
    settings: Any = None,
    env: dict[str, str] | None = None,
    final_xodr: str | None = None,
) -> dict[str, Any]:
    """Compute and durably persist ``final_run_verdict.json``."""
    payload = compute_final_run_verdict(
        out_dir, profile=profile, settings=settings, env=env, final_xodr=final_xodr
    )
    target = os.path.join(str(out_dir), "final_run_verdict.json")
    write_governed_signal(target, payload, signal_id="FINAL_RUN_VERDICT")
    return payload
