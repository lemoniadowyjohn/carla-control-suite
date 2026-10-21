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
    """Run the collapse check for ``checkpoint`` and return its verdict payload."""
    ckpt_path = Path(checkpoint)
    if not ckpt_path.is_file():
        return {
            "status": COLLAPSED_STATUS,
            "reason": "checkpoint_not_found",
            "checkpoint": str(ckpt_path),
        }
    tiles = Path(tiles_dir) if tiles_dir else (ckpt_path.parent / "tiles")
    try:
        verdict = run_collapse_check(checkpoint=ckpt_path, tiles_dir=tiles, out_path=Path(str(ckpt_path) + ".collapse.json"))
    except Exception as exc:  # fail closed: a collapsed verdict must not be masked
        return {
            "status": COLLAPSED_STATUS,
            "reason": "collapse_check_failed",
            "checkpoint": str(ckpt_path),
            "error": str(exc),
        }
    verdict["checkpoint"] = str(ckpt_path)
    verdict["status"] = COLLAPSED_STATUS if verdict.get("verdict") == "COLLAPSED" else "ok"
    verdict["reason"] = COLLAPSED_REASON if verdict["status"] == COLLAPSED_STATUS else None
    return verdict


def assert_encoder_not_collapsed(checkpoint: str, *, tiles_dir: Optional[str] = None) -> Dict[str, Any]:
    """Return the verdict payload, raising ``EncoderCollapsedError`` on collapse."""
    verdict = collapse_verdict(checkpoint, tiles_dir=tiles_dir)
    if verdict["status"] == COLLAPSED_STATUS:
        raise EncoderCollapsedError(COLLAPSED_NOTE)
    return verdict


def collapsed_payload(checkpoint: str, *, tiles_dir: Optional[str] = None) -> Dict[str, Any]:
    """Structured NOT_RUN payload for a collapsed encoder (no numeric metrics)."""
    verdict = collapse_verdict(checkpoint, tiles_dir=tiles_dir)
    return {
        "status": COLLAPSED_STATUS,
        "reason": verdict.get("reason", COLLAPSED_REASON),
        "note": COLLAPSED_NOTE,
        "encoder": {
            "checkpoint": verdict.get("checkpoint"),
            "verdict": verdict.get("verdict"),
            "noise_self_cosine": verdict.get("noise_self_cosine"),
        },
        "metrics": None,
    }


def write_collapsed_receipt(out_path: str, checkpoint: str, *, tiles_dir: Optional[str] = None) -> Path:
    """Persist the collapse verdict as a receipt next to the inference output."""
    payload = collapsed_payload(checkpoint, tiles_dir=tiles_dir)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return target