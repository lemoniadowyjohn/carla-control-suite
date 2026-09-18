#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import torch
import torch.nn.functional as F
from torch_geometric.data import Batch, Data

from .map_encoder import MapEncoder, MapEncoderConfig
from .map_tile_dataset import MapTileDataset


DEFAULT_CHECKPOINT = (
    Path("thesis_results") / "gnn_v1" / "ksweep_runs" / "k_72" / "map_encoder_epoch50.pt"
)
DEFAULT_TILES_DIR = Path("domain_gap_results") / "auto_tiles_aligned"
DEFAULT_OUT = Path("thesis_results") / "gnn_v1" / "collapse_check.json"


def _pairwise_mean_cosine(embeddings: torch.Tensor) -> float:
    z = F.normalize(embeddings, p=2, dim=1)
    sims: List[torch.Tensor] = []
    for i in range(int(z.shape[0])):
        for j in range(i + 1, int(z.shape[0])):
            sims.append(torch.sum(z[i] * z[j]))
    if not sims:
        return 0.0
    return float(torch.stack(sims).mean().cpu().item())


def _cross_mean_cosine(a: torch.Tensor, b: torch.Tensor) -> float:
    a_n = F.normalize(a, p=2, dim=1)
    b_n = F.normalize(b, p=2, dim=1)
    sims = torch.matmul(a_n, b_n.T)
    return float(sims.mean().cpu().item())


def _load_model(checkpoint_path: Path) -> MapEncoder:
    ckpt = torch.load(str(checkpoint_path), map_location="cpu")
    cfg = MapEncoderConfig(**ckpt["cfg"])
    model = MapEncoder(cfg)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model


def _random_noise_graph(node_dim: int) -> Data:
    x = torch.randn(20, int(node_dim), dtype=torch.float32)
    edge_index = torch.randint(0, 20, (2, 40), dtype=torch.long)
    return Data(x=x, edge_index=edge_index)


def run_collapse_check(
    checkpoint: Path = DEFAULT_CHECKPOINT,
    tiles_dir: Path = DEFAULT_TILES_DIR,
    out_path: Path = DEFAULT_OUT,
) -> Dict[str, Any]:
    if not checkpoint.is_file():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint}")
    if not tiles_dir.is_dir():
        raise FileNotFoundError(f"Tile directory not found: {tiles_dir}")

    model = _load_model(checkpoint)
    node_dim = int(model.cfg.node_dim)

    noise_graphs = [_random_noise_graph(node_dim) for _ in range(5)]
    dataset = MapTileDataset(str(tiles_dir))
    if len(dataset) < 5:
        raise RuntimeError(f"Need at least 5 real tiles in {tiles_dir}, found {len(dataset)}")
    tile_graphs = [dataset[i] for i in range(5)]

    with torch.no_grad():
        z_noise = model(Batch.from_data_list(noise_graphs))
        z_tiles = model(Batch.from_data_list(tile_graphs))

    noise_self = _pairwise_mean_cosine(z_noise)
    tile_self = _pairwise_mean_cosine(z_tiles)
    cross = _cross_mean_cosine(z_noise, z_tiles)

    verdict = "NOT_COLLAPSED" if noise_self < 0.95 else "COLLAPSED"
    if noise_self > 0.95:
        interpretation = (
            "Noise embeddings are too similar; encoder likely collapsed and "
            "whole-map cosine claims are unreliable."
        )
    elif noise_self < 0.8 and tile_self > 0.9:
        interpretation = (
            "Noise embeddings are diverse while tile embeddings are coherent; "
            "encoder appears discriminative."
        )
    else:
        interpretation = (
            "Encoder is likely not collapsed, but separation margin is moderate; "
            "interpret with caution."
        )

    payload = {
        "checkpoint": str(checkpoint),
        "noise_self_cosine": float(noise_self),
        "tile_self_cosine": float(tile_self),
        "cross_cosine": float(cross),
        "verdict": verdict,
        "interpretation": interpretation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    payload = run_collapse_check()
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
