#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/train_map_encoder.py

from __future__ import annotations

import argparse
import os
import random

import torch
import torch.nn.functional as F
from torch_geometric.loader import DataLoader

from .map_encoder import MapEncoder, MapEncoderConfig
from .map_tile_dataset import MapTileDataset


# ---------------------------------------------------------
# Utilities
# ---------------------------------------------------------

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles_dir", type=str, required=True,
                    help="Directory with XODR tiles for training.")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch_size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--node_dim", type=int, default=16)
    ap.add_argument("--out_dir", type=str, default="gnn_runs")
    ap.add_argument("--noise_std", type=float, default=0.01,
                    help="Std of Gaussian noise added to node features.")
    ap.add_argument("--seed", type=int, default=0)
    return ap.parse_args()


def set_seed(seed: int):
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def perturb_graph(batch, noise_std: float):
    """
    Apply a small feature-space perturbation.
    This preserves topology and semantics.
    """
    batch = batch.clone()
    noise = torch.randn_like(batch.x) * noise_std
    batch.x = batch.x + noise
    return batch


# ---------------------------------------------------------
# Main training
# ---------------------------------------------------------

def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    set_seed(args.seed)

    # Dataset (deterministic, pre-validated)
    ds = MapTileDataset(args.tiles_dir)
    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=True)

    cfg = MapEncoderConfig(node_dim=args.node_dim)
    model = MapEncoder(cfg)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    print(f"🧠 Training MapEncoder")
    print(f"   tiles        : {len(ds)}")
    print(f"   epochs       : {args.epochs}")
    print(f"   batch size   : {args.batch_size}")
    print(f"   noise std    : {args.noise_std}")
    print(f"   device       : {device}")

    for epoch in range(args.epochs):
        model.train()
        total_loss = 0.0

        for batch in dl:
            batch = batch.to(device)

            # Two noisy views of the same graphs
            batch_a = perturb_graph(batch, args.noise_std)
            batch_b = perturb_graph(batch, args.noise_std)

            z_a = model(batch_a)  # [B, D]
            z_b = model(batch_b)  # [B, D]

            # Normalize to unit sphere
            z_a = F.normalize(z_a, dim=1)
            z_b = F.normalize(z_b, dim=1)

            # Consistency loss (cosine distance)
            loss = 1.0 - (z_a * z_b).sum(dim=1).mean()

            opt.zero_grad()
            loss.backward()
            opt.step()

            total_loss += float(loss.item()) * batch.num_graphs

        avg_loss = total_loss / len(ds)
        print(f"[epoch {epoch+1:03d}/{args.epochs}] loss = {avg_loss:.6f}")

        # Save checkpoint
        if (epoch + 1) % 10 == 0 or epoch == args.epochs:
            ckpt_path = os.path.join(
                args.out_dir, f"map_encoder_epoch{epoch+1}.pt"
            )
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "cfg": cfg.__dict__,
                    "seed": args.seed,
                    "noise_std": args.noise_std,
                },
                ckpt_path,
            )
            print(f"💾 Saved checkpoint → {ckpt_path}")


if __name__ == "__main__":
    main()
