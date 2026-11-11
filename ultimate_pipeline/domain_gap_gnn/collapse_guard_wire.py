#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/domain_gap_gnn/collapse_guard_wire.py

CD-4 / RQ4 remediation: wire the encoder-collapse verdict into the inference
paths that produce latent-gap metrics.

Deep-Audit finding: ``collapse_check.run_collapse_check()`` could detect an
encoder whose embeddings had collapsed (noise_self_cosine > 0.95 ->
``COLLAPSED``), but the verdict was never consulted by the inference paths that
produce the actual latent-gap numbers. A collapsed encoder yields near-identical
embeddings for every tile, so any cosine/gap metric it produces is a *fabricated*
number, not evidence. This module is the single chokepoint: every inference
consumer calls ``assert_encoder_not_collapsed()`` before computing metrics;
if the encoder is COLLAPSED, the consumer returns a structured
``{"status": "NOT_RUN", "reason": "encoder_collapsed"}`` payload and never
emits numeric gap values.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .collapse_check import run_collapse_check

COLLAPSED_STATUS = "NOT_RUN"
COLLAPSED_REASON = "encoder_collapsed"
COLLAPSED_NOTE = (
    "encoder collapsed (noise_self_cosine > 0.95): latent-gap metrics would be "
    "fabricated; no numeric gap values emitted"
)


class EncoderCollapsedError(RuntimeError):
    """Raised when an inference path is asked to produce metrics on a collapsed encoder."""


def collapse_verdict(checkpoint: str, *, tiles_dir: Optional[str] = None) -> Dict[str, Any]:
    """Check the actual encoder; only a complete, consistent result can pass.

    A missing tile set, an exception, nonfinite values, or an unknown verdict
    must never be interpreted as NOT_COLLAPSED.
    """
    ckpt_path = Path(checkpoint)
    if not ckpt_path.is_file():
        return {
            "status": COLLAPSED_STATUS,
            "reason": "checkpoint_not_found",
            "checkpoint": str(ckpt_path),
        }
    tiles = Path(tiles_dir) if tiles_dir else (ckpt_path.parent / "tiles")
    try:
        raw = run_collapse_check(
            checkpoint=ckpt_path,
            tiles_dir=tiles,
            out_path=Path(str(ckpt_path) + ".collapse.json"),
        )
    except Exception as exc:
        return {
            "status": COLLAPSED_STATUS,
            "reason": "collapse_check_failed",
            "checkpoint": str(ckpt_path),
            "error": str(exc),
        }

    if not isinstance(raw, dict):
        return {
            "status": COLLAPSED_STATUS,
            "reason": "invalid_collapse_verdict",
            "checkpoint": str(ckpt_path),
        }
    verdict = dict(raw)
    verdict["checkpoint"] = str(ckpt_path)
    label = verdict.get("verdict")
    scores = ("noise_self_cosine", "tile_self_cosine", "cross_cosine")
    valid_scores = all(
        isinstance(verdict.get(k), (int, float))
        and not isinstance(verdict.get(k), bool)
        and math.isfinite(verdict[k])
        and -1.00001 <= verdict[k] <= 1.00001
        for k in scores
    )
    noise = verdict.get("noise_self_cosine")
    consistent = (
        (label == "COLLAPSED" and valid_scores and noise >= 0.95)
        or (label == "NOT_COLLAPSED" and valid_scores and noise < 0.95)
    )
    if not consistent:
        verdict["status"] = COLLAPSED_STATUS
        verdict["reason"] = "invalid_collapse_verdict"
        return verdict

    verdict["status"] = COLLAPSED_STATUS if label == "COLLAPSED" else "ok"
    verdict["reason"] = COLLAPSED_REASON if label == "COLLAPSED" else None
    return verdict


def assert_encoder_not_collapsed(checkpoint: str, *, tiles_dir: Optional[str] = None) -> Dict[str, Any]:
    """Return the verdict payload, raising ``EncoderCollapsedError`` on collapse."""
    verdict = collapse_verdict(checkpoint, tiles_dir=tiles_dir)
    if verdict["status"] == COLLAPSED_STATUS:
        raise EncoderCollapsedError(COLLAPSED_NOTE)
    return verdict


def blocked_payload(verdict: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a NOT_RUN result from an *already checked* verdict.

    Do not repeat the stochastic collapse experiment to manufacture a
    different answer for the same inference call.
    """
    if verdict.get("status") != COLLAPSED_STATUS:
        raise ValueError("blocked_payload requires a NOT_RUN collapse verdict")
    reason = str(verdict.get("reason") or "collapse_verdict_unavailable")
    return {
        "enabled": False,
        "status": COLLAPSED_STATUS,
        "reason": reason,
        "note": COLLAPSED_NOTE if reason == COLLAPSED_REASON
                else "Collapse check did not provide valid clearance; no latent-gap metrics emitted",
        "encoder": {
            "checkpoint": verdict.get("checkpoint"),
            "verdict": verdict.get("verdict"),
            "noise_self_cosine": verdict.get("noise_self_cosine"),
        },
        "metrics": None,
    }


def collapsed_payload(checkpoint: str, *, tiles_dir: Optional[str] = None) -> Dict[str, Any]:
    """Backward-compatible entrypoint for structured NOT_RUN results."""
    verdict = collapse_verdict(checkpoint, tiles_dir=tiles_dir)
    return blocked_payload(verdict)


def write_collapsed_receipt(out_path: str, checkpoint: str, *, tiles_dir: Optional[str] = None) -> Path:
    """Persist the collapse verdict as a receipt next to the inference output."""
    payload = collapsed_payload(checkpoint, tiles_dir=tiles_dir)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return target