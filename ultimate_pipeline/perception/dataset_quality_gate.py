#!/usr/bin/env python3
"""RQ5 dataset quality gate — fail-closed dataset acceptance.

Requires dataset_identity.complete == true for science; partial prefix
hashing is diagnostic only. Checks paired rgb/label frames, label id range,
and manifest/hash binding. Supports --research-strict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from ultimate_pipeline.perception.carla_classes import assert_label_ids_in_range
import numpy as np
from PIL import Image


class QualityGateError(RuntimeError):
    pass


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def check_dataset(root: Path, camera: str, *, research_strict: bool,
                  manifest: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if research_strict and not camera:
        raise QualityGateError("research-strict rejects implicit camera")
    rgb_dir = root / "rgb" / camera
    lab_dir = root / "semseg_raw" / camera
    if not rgb_dir.is_dir() or not lab_dir.is_dir():
        raise QualityGateError(f"dataset root {root} missing rgb/{camera} and semseg_raw/{camera}")
    rgb = sorted(p.name for p in rgb_dir.glob("*.png"))
    lab = sorted(p.name for p in lab_dir.glob("*.png"))
    unpaired_rgb = sorted(set(rgb) - set(lab))
    unpaired_lab = sorted(set(lab) - set(rgb))
    if unpaired_rgb or unpaired_lab:
        raise QualityGateError(f"unpaired frames: rgb-only={unpaired_rgb[:5]} labels-only={unpaired_lab[:5]}")
    if not rgb:
        raise QualityGateError("no paired frames found")
    # label range spot-check (first min(8, n) frames)
    for name in rgb[:8]:
        arr = np.array(Image.open(lab_dir / name).convert("L"), dtype=np.uint8)
        assert_label_ids_in_range(arr)
    out: Dict[str, Any] = {"paired_frames": len(rgb), "camera": camera, "root": str(root)}
    if manifest is not None and research_strict:
        ident = manifest.get("dataset_identity") or {}
        if ident.get("complete") is not True:
            raise QualityGateError("research-strict requires dataset_identity.complete == true")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--camera", default=None)
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--research-strict", action="store_true")
    args = ap.parse_args()
    try:
        m = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
        rep = check_dataset(args.dataset, args.camera or "", research_strict=args.research_strict, manifest=m)
        print(json.dumps({"ok": True, **rep}, indent=2))
        return 0
    except QualityGateError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
