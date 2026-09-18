#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-click thesis figure pack generator (offline).

Creates a standardized set of figures per run directory:
- copies domain gap figures if present
- creates a montage of a few RGB frames from perception capture if present
- writes FIGURE_PACK_SUMMARY.json for traceability

This does not require CARLA.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import matplotlib.image as mpimg


def _write_json(p: Path, d: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2, sort_keys=True), encoding="utf-8")


def _find_images(run_dir: Path) -> List[Path]:
    # Prefer screenshots/recording rgb
    cands = []
    for pat in [
        "screenshots/*.png",
        "perception_thesis/recording/**/*.png",
        "perception*/recording/**/*.png",
        "recording/**/*.png",
    ]:
        cands.extend(sorted(run_dir.glob(pat)))
    # de-dup
    seen = set()
    out = []
    for p in cands:
        if p.is_file() and p.suffix.lower() == ".png":
            if str(p) not in seen:
                out.append(p)
                seen.add(str(p))
    return out


def _make_montage(img_paths: List[Path], out_path: Path, max_n: int = 9) -> Dict[str, Any]:
    picks = img_paths[:max_n]
    if not picks:
        return {"ok": False, "reason": "no_images_found"}

    n = len(picks)
    cols = 3
    rows = (n + cols - 1) // cols

    fig = plt.figure(figsize=(cols * 4, rows * 3))
    for i, p in enumerate(picks, start=1):
        ax = fig.add_subplot(rows, cols, i)
        try:
            img = mpimg.imread(str(p))
            ax.imshow(img)
            ax.set_title(p.name[:40])
        except Exception as e:
            ax.text(0.5, 0.5, f"read error\n{e}", ha="center", va="center")
        ax.axis("off")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return {"ok": True, "count": n, "out": str(out_path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--out", default=None, type=Path, help="Output folder (default: <run-dir>/figure_pack)")
    ap.add_argument("--max-montage", type=int, default=9)
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    out_dir = (args.out.resolve() if args.out else (run_dir / "figure_pack"))
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: Dict[str, Any] = {"run_dir": str(run_dir), "out_dir": str(out_dir), "copied": [], "generated": []}

    # Copy domain_gap figures if present
    dg = run_dir / "domain_gap"
    if dg.exists():
        for pat in ["*.png", "*.pdf", "*.jpg", "*.jpeg"]:
            for f in dg.rglob(pat):
                if f.is_file():
                    dest = out_dir / "domain_gap" / f.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
                    summary["copied"].append(str(dest))
    # Montage
    imgs = _find_images(run_dir)
    montage_out = out_dir / "montage_rgb.png"
    rep = _make_montage(imgs, montage_out, max_n=int(args.max_montage))
    summary["generated"].append(rep)

    _write_json(out_dir / "FIGURE_PACK_SUMMARY.json", summary)
    print(f"[figure_pack] wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
