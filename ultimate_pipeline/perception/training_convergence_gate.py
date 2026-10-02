#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/training_convergence_gate.py

Technical convergence sanity gate for an RQ5 training run.

What this gate does and does not decide
---------------------------------------
It answers one narrow question: *did this training run technically execute as
the frozen protocol requires, and is the resulting artifact internally
consistent?* It answers "no" when an epoch was not run, a loss became NaN, the
checkpoint does not match its manifest, the model does not load, the prediction
collapsed to a single class, the dataset identities do not match the requested
splits, or the seed contract was not applied.

It deliberately does **not** judge scientific target performance. A three-epoch
run on a small dataset may be technically perfect and scientifically worthless.
Conflating the two is how a broken run gets reported as "the model did not
learn" and how a working-but-weak run gets silently retrained until it looks
good. The two verdicts are emitted as separate blocks:

    technical_convergence : PASS / FAIL, with an explicit check list
    scientific_performance : NOT_ASSESSED_OFFLINE, with a claim boundary

If the *technical* checks pass but the run is scientifically underpowered, the
correct outcome is ``RQ5_PROTOCOL_UNDERPOWERED``: a v3 protocol must be
preregistered BEFORE any manual-target performance is viewed. Training is never
silently extended.

A dataset or a run that has not been executed cannot be reported as a pass: a
missing input yields ``INCOMPLETE``, never ``PASS``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ultimate_pipeline.perception.rq5_provenance import (
    canonical_dumps,
    load_state_dict_governed,
    sha256_text,
    verify_checkpoint_provenance_strict,
)

__all__ = [
    "CONVERGENCE_SCHEMA",
    "CONVERGENCE_FILENAME",
    "TECHNICAL_PASS",
    "TECHNICAL_FAIL",
    "TECHNICAL_INCOMPLETE",
    "SCIENTIFIC_NOT_ASSESSED",
    "PROTOCOL_UNDERPOWERED",
    "ConvergenceCheck",
    "ConvergenceReport",
    "run_convergence_gate",
    "write_convergence_report",
    "load_convergence_report",
]

CONVERGENCE_SCHEMA = "rq5_training_convergence_v1"
CONVERGENCE_FILENAME = "TRAINING_CONVERGENCE.json"

TECHNICAL_PASS = "PASS"
TECHNICAL_FAIL = "FAIL"
TECHNICAL_INCOMPLETE = "INCOMPLETE"

SCIENTIFIC_NOT_ASSESSED = "NOT_ASSESSED_OFFLINE"
PROTOCOL_UNDERPOWERED = "RQ5_PROTOCOL_UNDERPOWERED"


@dataclass(frozen=True)
class ConvergenceCheck:
    code: str
    ok: bool
    detail: str
    data: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "status": "PASS" if self.ok else "FAIL",
            "detail": self.detail,
            "data": dict(self.data) if self.data else None,
        }


@dataclass
class ConvergenceReport:
    technical_status: str
    scientific_status: str
    checks: List[ConvergenceCheck] = field(default_factory=list)
    observations: Dict[str, Any] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    claim_scope: str = "TEST_FIXTURE_ONLY"

    @property
    def ok(self) -> bool:
        return self.technical_status == TECHNICAL_PASS

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "schema": CONVERGENCE_SCHEMA,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "claim_scope": self.claim_scope,
            "technical_convergence": {
                "status": self.technical_status,
                "checks": [c.to_dict() for c in self.checks],
                "failures": list(self.failures),
            },
            "scientific_performance": {
                "status": self.scientific_status,
                "assessed": False,
                "claim_boundary": (
                    "This gate never judges mIoU, degradation or any scientific target. "
                    "Technical convergence sanity and scientific target performance are "
                    "independent verdicts; a PASS here does not license a performance claim."
                ),
                "observations": dict(self.observations),
            },
        }
        payload["report_sha256"] = sha256_text(
            canonical_dumps(
                {k: v for k, v in payload.items() if k not in ("created_utc", "report_sha256")}
            )
        )
        return payload


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def run_convergence_gate(
    *,
    run_dir: Any,
    checkpoint: Optional[Any] = None,
    manifest: Optional[Any] = None,
    training_history: Optional[Any] = None,
    expected_epochs: Optional[int] = None,
    expected_seed: Optional[int] = None,
    expected_dataset_identities: Optional[Mapping[str, Optional[str]]] = None,
    model_factory: Optional[Any] = None,
    prediction_probe: Optional[Any] = None,
    num_classes: int = 29,
    claim_scope: str = "TEST_FIXTURE_ONLY",
) -> ConvergenceReport:
    """
    Run every technical convergence check and return a :class:`ConvergenceReport`.

    Args:
        run_dir: Directory holding ``model_manifest.json`` / ``TRAINING_HISTORY.json``
            and the checkpoints.
        checkpoint: Explicit checkpoint path. When omitted the final-epoch
            checkpoint recorded in the manifest is used. **There is deliberately
            no "latest checkpoint by mtime" fallback** in this gate.
        manifest: Explicit manifest path; defaults to ``<run_dir>/model_manifest.json``.
        training_history: Defaults to ``<run_dir>/TRAINING_HISTORY.json``.
        expected_epochs: Epochs the protocol froze. Defaults to the manifest's value.
        expected_seed: Seed the protocol froze. Defaults to the manifest's value.
        expected_dataset_identities: ``{role: identity_sha256}`` the caller asked
            for. Any role present here must match the manifest.
        model_factory: Zero-argument callable returning a fresh model with the
            manifest's architecture, used for the load-completeness and
            single-class-collapse checks. When omitted those two checks are
            reported as skipped (and cannot silently pass).
        prediction_probe: ``(model) -> predicted label array`` used for the
            collapse check. Defaults to a forward pass over a synthetic tensor.
    """
    directory = Path(run_dir)
    checks: List[ConvergenceCheck] = []
    failures: List[str] = []
    observations: Dict[str, Any] = {}

    def record(code: str, ok: bool, detail: str, data: Optional[Mapping[str, Any]] = None) -> None:
        checks.append(ConvergenceCheck(code, ok, detail, data))
        if not ok:
            failures.append(f"{code}: {detail}")

    manifest_path = Path(manifest) if manifest else directory / "model_manifest.json"
    manifest_payload = _read_json(manifest_path)

    if manifest_payload is None:
        return ConvergenceReport(
            technical_status=TECHNICAL_INCOMPLETE,
            scientific_status=SCIENTIFIC_NOT_ASSESSED,
            checks=[
                ConvergenceCheck(
                    "manifest_present",
                    False,
                    f"no readable model_manifest.json at {manifest_path}",
                )
            ],
            failures=[f"manifest_present: no readable model_manifest.json at {manifest_path}"],
            claim_scope=claim_scope,
        )

    record("manifest_present", True, f"model_manifest.json loaded from {manifest_path}")

    # --- checkpoint exists and is the governed final-epoch checkpoint -----
    policy = (manifest_payload.get("checkpoint") or {}).get("policy") or {}
    if checkpoint is not None:
        ckpt_path = Path(checkpoint)
    else:
        recorded = (manifest_payload.get("checkpoint") or {}).get("path")
        ckpt_path = Path(recorded) if recorded else directory / "seg_fcn_epoch003.pt"
    record(
        "checkpoint_exists",
        ckpt_path.is_file(),
        f"governed checkpoint {'found' if ckpt_path.is_file() else 'missing'}: {ckpt_path}",
    )
    if not ckpt_path.is_file():
        return ConvergenceReport(
            technical_status=TECHNICAL_INCOMPLETE,
            scientific_status=SCIENTIFIC_NOT_ASSESSED,
            checks=checks,
            failures=failures,
            observations=observations,
            claim_scope=claim_scope,
        )

    epochs_declared = int((manifest_payload.get("optimization") or {}).get("epochs") or 0)
    expected = int(expected_epochs) if expected_epochs is not None else epochs_declared
    record(
        "checkpoint_policy_final_epoch",
        policy.get("checkpoint_policy") == "final_epoch_only"
        and not bool(policy.get("validation_selects_epoch"))
        and not bool(policy.get("early_stopping")),
        f"checkpoint policy is {policy!r}; protocol v2 requires final_epoch_only with no "
        "validation-based selection and no early stopping",
    )

    # --- checkpoint bytes match the manifest ------------------------------
    verification = verify_checkpoint_provenance_strict(ckpt_path, manifest_path)
    record(
        "checkpoint_manifest_binding",
        bool(verification["ok"]),
        "checkpoint sha256 and provenance match the manifest"
        if verification["ok"]
        else "; ".join(verification["failures"]),
        {"checkpoint_sha256": verification.get("checkpoint_sha256"),
         "protocol_sha256": verification.get("protocol_sha256")},
    )

    # --- expected dataset identities --------------------------------------
    dataset = manifest_payload.get("dataset") or {}
    observed_identities = {
        "generated_train": dataset.get("train_identity_sha256"),
        "generated_validation": dataset.get("validation_identity_sha256"),
    }
    for role, identity in (dataset.get("test_identities") or {}).items():
        observed_identities[str(role)] = (identity or {}).get("identity_sha256")

    if expected_dataset_identities:
        mismatches = []
        for role, expected_sha in expected_dataset_identities.items():
            if expected_sha is None:
                continue
            actual = observed_identities.get(role)
            if actual is None:
                mismatches.append(f"{role}: absent from the manifest")
            elif str(actual).lower() != str(expected_sha).lower():
                mismatches.append(f"{role}: manifest={actual} expected={expected_sha}")
        record(
            "dataset_identity_match",
            not mismatches,
            "manifest dataset identities match the requested splits"
            if not mismatches
            else "; ".join(mismatches),
            {"observed": observed_identities},
        )
    else:
        record(
            "dataset_identity_match",
            True,
            "no expected identities supplied by the caller; identity completeness was "
            "still enforced by checkpoint_manifest_binding",
            {"observed": observed_identities},
        )

    # --- seed contract ----------------------------------------------------
    manifest_seed = (manifest_payload.get("seed") or {}).get("seed")
    if expected_seed is not None:
        record(
            "seed_contract",
            manifest_seed is not None and int(manifest_seed) == int(expected_seed),
            f"manifest seed {manifest_seed} vs expected {expected_seed}",
        )
    else:
        record(
            "seed_contract",
            manifest_seed is not None,
            f"manifest records seed {manifest_seed}",
        )

    determinism = manifest_payload.get("determinism") or {}
    record(
        "determinism_recorded",
        bool(determinism.get("status")),
        f"determinism contract recorded with status {determinism.get('status')!r}; "
        "bit-exactness is never claimed",
        {"status": determinism.get("status"), "blockers": determinism.get("strict_determinism_blockers")},
    )
    if determinism.get("status") and determinism.get("status") != "DETERMINISM_ENFORCED":
        observations["determinism_caveat"] = (
            "SEEDED_BUT_NUMERICALLY_NONDETERMINISTIC: the seed was applied to every RNG but the "
            "hardware/library stack could not guarantee bit-exact numerics"
        )

    # --- training history: epochs + finite losses -------------------------
    history_path = (
        Path(training_history)
        if training_history
        else directory / "TRAINING_HISTORY.json"
    )
    history = _read_json(history_path)
    if history is None:
        record(
            "training_history_present",
            False,
            f"no readable TRAINING_HISTORY.json at {history_path}",
        )
        record("epochs_completed", False, "training history is unavailable")
        record("train_loss_finite", False, "training history is unavailable")
        record("validation_loss_finite", False, "training history is unavailable")
    else:
        record("training_history_present", True, f"TRAINING_HISTORY.json loaded from {history_path}")
        epoch_rows = list(history.get("epochs") or [])
        record(
            "epochs_completed",
            bool(epoch_rows) and len(epoch_rows) == int(expected) > 0,
            f"{len(epoch_rows)} epoch record(s) present, {expected} expected",
            {"expected": int(expected), "observed": len(epoch_rows)},
        )
        train_losses = [row.get("train_loss") for row in epoch_rows]
        record(
            "train_loss_finite",
            bool(train_losses) and all(_finite(v) for v in train_losses),
            f"training losses finite: {train_losses}",
            {"values": train_losses},
        )
        val_losses = [row.get("validation_loss") for row in epoch_rows]
        if any(v is not None for v in val_losses):
            record(
                "validation_loss_finite",
                all(_finite(v) for v in val_losses if v is not None),
                f"validation losses finite: {val_losses}",
                {"values": val_losses},
            )
        else:
            record(
                "validation_loss_finite",
                False,
                "no generated-validation loss was recorded; protocol v2 requires a real "
                "validation pass every epoch",
            )
        observations["epochs"] = epoch_rows

    # --- model loads completely -------------------------------------------
    if model_factory is None:
        record(
            "model_loads_completely",
            False,
            "no model_factory supplied; a governed run must verify the parameter set "
            "actually matches the checkpoint",
        )
        record(
            "prediction_not_single_class",
            False,
            "no model_factory supplied; single-class collapse cannot be ruled out",
        )
    else:
        model = model_factory()
        load_record: Dict[str, Any] = {}
        try:
            outcome = load_state_dict_governed(model, ckpt_path, record=load_record)
            record(
                "model_loads_completely",
                not outcome["missing_keys"] and not outcome["unexpected_keys"],
                f"strict load succeeded with {outcome['parameter_count']} parameter tensors",
                {"parameter_count": outcome["parameter_count"]},
            )
        except Exception as exc:
            record(
                "model_loads_completely",
                False,
                f"strict load failed: {type(exc).__name__}: {exc}",
            )

        try:
            import numpy as np
            import torch as _torch

            if prediction_probe is not None:
                predicted = prediction_probe(model)
            else:
                was_training = getattr(model, "training", False)
                model.eval()
                with _torch.no_grad():
                    dummy = _torch.zeros(1, 3, 32, 32)
                    predicted = model(dummy)["out"].argmax(dim=1).cpu().numpy().reshape(-1)
                if was_training:
                    model.train()
            classes = {int(v) for v in np.asarray(predicted).reshape(-1).tolist()}
            collapsed = len(classes) <= 1
            record(
                "prediction_not_single_class",
                not collapsed,
                f"predictions cover {len(classes)} distinct class id(s)"
                + (" (single-class collapse)" if collapsed else ""),
                {"distinct_classes": sorted(classes)[:16]},
            )
            observations["prediction_probe_classes"] = sorted(classes)[:16]
        except Exception as exc:
            record(
                "prediction_not_single_class",
                False,
                f"prediction probe failed: {type(exc).__name__}: {exc}",
            )

    technical_status = TECHNICAL_PASS if not failures else TECHNICAL_FAIL
    scientific_status = SCIENTIFIC_NOT_ASSESSED
    if technical_status == TECHNICAL_PASS:
        observations["note"] = (
            "Technical convergence sanity only. Whether 3 frozen epochs are scientifically "
            f"adequate is not decided here; if they are not, the correct outcome is "
            f"{PROTOCOL_UNDERPOWERED} and a v3 preregistered before any manual-target "
            "performance is viewed."
        )

    return ConvergenceReport(
        technical_status=technical_status,
        scientific_status=scientific_status,
        checks=checks,
        observations=observations,
        failures=failures,
        claim_scope=claim_scope,
    )


def write_convergence_report(
    out_dir: Any,
    report: ConvergenceReport,
    *,
    filename: str = CONVERGENCE_FILENAME,
) -> Path:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    target.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def load_convergence_report(path: Any) -> Dict[str, Any]:
    """Load a persisted ``TRAINING_CONVERGENCE.json`` and schema-check it."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"training convergence report not found: {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != CONVERGENCE_SCHEMA:
        raise ValueError(f"unsupported training convergence schema in {p}")
    return payload