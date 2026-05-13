#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/infer_tile_gaps.py

from __future__ import annotations

import argparse
import json
import os
import hashlib
from typing import Dict, Tuple

import torch
from torch_geometric.data import Batch

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.domain_gap.tile_matcher import TileMatcher
from .map_encoder import MapEncoder, MapEncoderConfig
from .latent_gap_utils import combine_latent_gaps
from .graph_builder import MapGraphBuilder


# ============================================================
# CLI
# ============================================================

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual_tiles", type=str, required=True)
    ap.add_argument("--auto_tiles", type=str, required=True)
    ap.add_argument("--checkpoint", type=str, required=True)
    ap.add_argument("--out_dir", type=str, default="domain_gap_gnn")
    ap.add_argument("--pairing", type=str, choices=["filename", "spatial"], default="filename")
    return ap.parse_args()


# ============================================================
# Utilities
# ============================================================

def _hash_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _set_determinism(seed: int | None):
    if seed is None:
        return
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def _list_xodr(dir_path: str):
    return sorted(f for f in os.listdir(dir_path) if f.lower().endswith(".xodr"))


# ============================================================
# Model loading
# ============================================================

def load_encoder(checkpoint_path: str, device: torch.device) -> MapEncoder:
    ckpt = torch.load(checkpoint_path, map_location="cpu")
    cfg = MapEncoderConfig(**ckpt["cfg"])
    model = MapEncoder(cfg)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model.to(device)


# ============================================================
# Main
# ============================================================

def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    # --------------------------------------------------------
    # Determinism
    # --------------------------------------------------------
    _set_determinism(getattr(SETTINGS, "DETERMINISTIC_SEED", None))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_encoder(args.checkpoint, device)

    # --------------------------------------------------------
    # Tile pairing
    # --------------------------------------------------------
    if args.pairing == "filename":
        manual_files = _list_xodr(args.manual_tiles)
        auto_files = _list_xodr(args.auto_tiles)
        pairs = {
            f: f for f in set(manual_files).intersection(auto_files)
        }
        pairing_method = "filename_intersection"
    else:
        pairs = TileMatcher.match(args.manual_tiles, args.auto_tiles)
        pairing_method = "spatial_iou"

    print(f"🔗 Tile pairing method: {pairing_method}")
    print(f"🔗 Matched tiles: {len(pairs)}")

    per_tile_gaps: Dict[str, Dict[str, float]] = {}
    skipped = []

    # --------------------------------------------------------
    # Inference
    # --------------------------------------------------------
    for m_name, a_name in pairs.items():
        m_path = os.path.join(args.manual_tiles, m_name)
        a_path = os.path.join(args.auto_tiles, a_name)

        g_m = MapGraphBuilder.build_from_xodr(m_path)
        g_a = MapGraphBuilder.build_from_xodr(a_path)

        if g_m is None or g_a is None:
            skipped.append(m_name)
            continue

        batch_m = Batch.from_data_list([g_m]).to(device)
        batch_a = Batch.from_data_list([g_a]).to(device)

        with torch.no_grad():
            z_m = model(batch_m)
            z_a = model(batch_a)

        if z_m.shape != z_a.shape:
            skipped.append(m_name)
            continue

        metrics = combine_latent_gaps(z_m, z_a)
        per_tile_gaps[m_name] = metrics

    # --------------------------------------------------------
    # Output
    # --------------------------------------------------------
    out = {
        "pairing_method": pairing_method,
        "n_tiles": len(per_tile_gaps),
        "skipped_tiles": skipped,
        "latent_gap_per_tile": per_tile_gaps,
        "encoder": {
            "checkpoint": args.checkpoint,
            "checkpoint_md5": _hash_file(args.checkpoint),
            "device": str(device),
        },
        "determinism": {
            "seed": getattr(SETTINGS, "DETERMINISTIC_SEED", None),
            "torch_deterministic": torch.backends.cudnn.deterministic,
        },
    }

    out_json = os.path.join(args.out_dir, "per_tile_latent_gap.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"💾 Saved latent per-tile gap → {out_json}")
    print(f"⚠ Skipped tiles: {len(skipped)}")


if __name__ == "__main__":
    main()
