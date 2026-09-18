#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/map_encoder.py

from __future__ import annotations
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GCNConv, global_mean_pool
from torch_geometric.data import Batch


@dataclass
class MapEncoderConfig:
    """
    Configuration for the map graph encoder.

    node_dim:
        Dimension of node features produced by graph_builder.
    hidden_dim:
        Internal GNN feature size.
    num_layers:
        Number of GCN layers (>=2 recommended).
    dropout:
        Dropout probability (training only).
    out_dim:
        Dimension of latent embedding used for domain-gap metrics.
    normalize_embedding:
        If True, L2-normalize output embedding (recommended for gap metrics).
    """
    node_dim: int = 16
    hidden_dim: int = 128
    num_layers: int = 3
    dropout: float = 0.1
    out_dim: int = 128
    normalize_embedding: bool = True


class MapEncoder(nn.Module):
    """
    GNN-based encoder for OpenDRIVE lane graphs.

    Input:
        torch_geometric.data.Batch with:
          - x           : [N, node_dim]
          - edge_index  : [2, E]
          - batch       : [N]

    Output:
        z : [batch_size, out_dim]
            Global map embedding suitable for distance-based domain-gap metrics.
    """

    def __init__(self, cfg: MapEncoderConfig):
        super().__init__()
        self.cfg = cfg

        assert cfg.num_layers >= 1, "num_layers must be >= 1"

        self.convs = nn.ModuleList()
        self.convs.append(GCNConv(cfg.node_dim, cfg.hidden_dim))
        for _ in range(cfg.num_layers - 1):
            self.convs.append(GCNConv(cfg.hidden_dim, cfg.hidden_dim))

        self.dropout = nn.Dropout(cfg.dropout)
        self.proj = nn.Linear(cfg.hidden_dim, cfg.out_dim)

    def forward(self, batch: Batch) -> torch.Tensor:
        """
        Forward pass.

        Notes on determinism:
        - During evaluation (model.eval()), dropout is disabled.
        - With fixed seeds and deterministic graph construction,
          this encoder is deterministic and suitable for measurement.
        """
        x = batch.x
        edge_index = batch.edge_index
        batch_idx = batch.batch

        h = x
        for i, conv in enumerate(self.convs):
            h_in = h
            h = conv(h, edge_index)
            h = F.relu(h)
            h = self.dropout(h)

            # Residual connection (when dimensions match)
            if h.shape == h_in.shape:
                h = h + h_in

        # Global pooling: node → graph
        g = global_mean_pool(h, batch_idx)

        # Projection to latent space
        z = self.proj(g)

        # Optional normalization for metric stability
        if self.cfg.normalize_embedding:
            z = F.normalize(z, p=2, dim=-1)

        return z
