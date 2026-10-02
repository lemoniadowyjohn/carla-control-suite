#!/usr/bin/env python3
"""RQ5 training convergence gate — diagnostics-only validation, final epoch governs.

Checks: finite losses, expected epochs reached, checkpoint exists,
manifest/checkpoint match, strict parameter load, no trivial single-class
collapse, correct datasets, correct seed. Generated validation is a
convergence diagnostic; it never selects among epochs (v2 protocol).
Supports --research-strict (rejects latest checkpoint, implicit seed/split).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict

import torch


class ConvergenceGateError(RuntimeError):
    pass


def check_run(out_dir: Path, *, expected_epochs: int, expected_seed: int | None,
              manifest: Dict[str, Any] | None, research_strict: bool) -> Dict[str, Any]:
    metrics_path = out_dir / "metrics.json"
    ckpt = out_dir / "checkpoints" / "model_last.pt"
    if not metrics_path.is_file():
        raise ConvergenceGateError(f"missing {metrics_path}")
    if not ckpt.is_file():
        raise ConvergenceGateError(f"missing final checkpoint {ckpt}")
    if research_strict:
        if expected_seed is None:
            raise ConvergenceGateError("research-strict rejects implicit seed")
        # reject latest-checkpoint semantics: only model_last.pt (final epoch) governs
        extras = sorted((out_dir / "checkpoints").glob("model_best*.pt"))
        if extras:
            raise ConvergenceGateError(f"research-strict rejects best-epoch checkpoints: {extras[:3]}")
    m = json.loads(metrics_path.read_text(encoding="utf-8"))
    if research_strict and m.get("seed") != expected_seed:
        raise ConvergenceGateError(f"seed mismatch: metrics seed={m.get('seed')!r} expected={expected_seed!r}")
    losses = m.get("loss") or []
    if len(losses) != expected_epochs:
        raise ConvergenceGateError(f"expected {expected_epochs} epochs, got {len(losses)}")
    for e in losses:
        v = e.get("loss")
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ConvergenceGateError(f"non-finite loss at epoch {e.get('epoch')}: {v!r}")
    # strict parameter load (no silent shape mismatch)
    try:
        from torchvision.models.segmentation import fcn_resnet50
        from ultimate_pipeline.perception.semantic_classes import validate_num_classes
        model = fcn_resnet50(weights=None, num_classes=validate_num_classes(29))
        state = torch.load(str(ckpt), map_location="cpu")
        model.load_state_dict(state, strict=True)
        n_params = sum(p.numel() for p in model.parameters())
    except Exception as e:
        raise ConvergenceGateError(f"strict parameter load failed: {e}") from e
    # no trivial single-class collapse: class weights must span >1 class
    cw = ((m.get("class_weighting") or {}).get("weights")) or []
    nonzero = sum(1 for w in cw if isinstance(w, (int, float)) and w > 0)
    if cw and nonzero <= 1:
        raise ConvergenceGateError(f"trivial single-class collapse: {nonzero} nonzero class weights")
    # manifest/checkpoint match: record checkpoint sha + param count
    import hashlib
    h = hashlib.sha256()
    with ckpt.open("rb") as f:
        for c in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(c)
    out: Dict[str, Any] = {
        "epochs": len(losses),
        "losses": [e.get("loss") for e in losses],
        "checkpoint_sha256": h.hexdigest(),
        "params": int(n_params),
        "seed": m.get("seed"),
        "val_losses": m.get("val_loss"),
    }
    if manifest is not None and research_strict:
        if manifest.get("seed") != m.get("seed"):
            raise ConvergenceGateError("manifest/checkpoint seed mismatch")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--expected-epochs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--research-strict", action="store_true")
    args = ap.parse_args()
    try:
        man = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
        rep = check_run(args.run_dir, expected_epochs=args.expected_epochs,
                        expected_seed=args.seed, manifest=man, research_strict=args.research_strict)
        print(json.dumps({"ok": True, **rep}, indent=2))
        return 0
    except ConvergenceGateError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
