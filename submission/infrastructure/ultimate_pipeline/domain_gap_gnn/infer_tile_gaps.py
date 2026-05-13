#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/infer_tile_gaps.py

from __future__ import annotations

import argparse
import json
import os
from typing import Dict

import torch
from torch_geometric.data import Batch

from .map_encoder import MapEncoder, MapEncoderConfig
from .latent_gap_utils import combine_latent_gaps
from .graph_builder import MapGraphBuilder


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual_tiles", type=str, required=True)
    ap.add_argument("--auto_tiles", type=str, required=True)
    ap.add_argument("--checkpoint", type=str, required=True)
    ap.add_argument("--out_dir", type=str, default="domain_gap_gnn")
    return ap.parse_args()


def load_encoder(checkpoint_path: str) -> MapEncoder:
    ckpt = torch.load(checkpoint_path, map_location="cpu")
    cfg = MapEncoderConfig(**ckpt["cfg"])
    model = MapEncoder(cfg)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model


def list_xodr_files(directory: str):
    return sorted(f for f in os.listdir(directory) if f.endswith(".xodr"))


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_encoder(args.checkpoint).to(device)

    manual_files = list_xodr_files(args.manual_tiles)
    auto_files = list_xodr_files(args.auto_tiles)

    # Simple pairing: assume identical filenames between manual and auto
    common = sorted(set(manual_files).intersection(auto_files))
    print(f"Found {len(common)} common tiles for latent gap computation.")

    per_tile_gaps: Dict[str, Dict[str, float]] = {}

    for fname in common:
        m_path = os.path.join(args.manual_tiles, fname)
        a_path = os.path.join(args.auto_tiles, fname)

        g_m = MapGraphBuilder.build_from_xodr(m_path)
        g_a = MapGraphBuilder.build_from_xodr(a_path)

        if g_m is None or g_a is None:
            print(f"⚠ Skipping {fname} (graph build failed).")
            continue

        # Build one-graph batches
        batch_m = Batch.from_data_list([g_m]).to(device)
        batch_a = Batch.from_data_list([g_a]).to(device)

        with torch.no_grad():
            z_m = model(batch_m)  # [1, D]
            z_a = model(batch_a)  # [1, D]

        metrics = combine_latent_gaps(z_m, z_a)
        per_tile_gaps[fname] = metrics

    out_json = os.path.join(args.out_dir, "per_tile_latent_gap.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(per_tile_gaps, f, indent=2)

    print(f"💾 Saved latent per-tile gaps → {out_json}")


if __name__ == "__main__":
    main()
