#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/latent_gap_runner.py

from __future__ import annotations
from typing import Dict, Any, Optional
import os
import json
import hashlib

import torch
from torch_geometric.data import Batch

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.domain_gap.tile_matcher import TileMatcher
from .map_encoder import MapEncoder, MapEncoderConfig
from .latent_gap_metrics import combine_latent_gaps
from .graph_builder import MapGraphBuilder


# ============================================================
# Utilities
# ============================================================

def _hash_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _set_determinism(seed: Optional[int]):
    if seed is None:
        return
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def _load_encoder(checkpoint_path: str, device: torch.device) -> MapEncoder:
    ckpt = torch.load(checkpoint_path, map_location="cpu")
    cfg = MapEncoderConfig(**ckpt["cfg"])
    model = MapEncoder(cfg)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model.to(device)


# ============================================================
# Whole-map latent gap
# ============================================================

def compute_whole_map_latent_gap(
    manual_xodr: str,
    auto_xodr: str,
    checkpoint: str,
) -> Dict[str, Any]:

    _set_determinism(getattr(SETTINGS, "DETERMINISTIC_SEED", None))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = _load_encoder(checkpoint, device)

    g_m = MapGraphBuilder.build_from_xodr(manual_xodr)
    g_a = MapGraphBuilder.build_from_xodr(auto_xodr)

    if g_m is None or g_a is None:
        return {
            "enabled": False,
            "error": "graph_build_failed",
        }

    batch_m = Batch.from_data_list([g_m]).to(device)
    batch_a = Batch.from_data_list([g_a]).to(device)

    with torch.no_grad():
        z_m = model(batch_m)
        z_a = model(batch_a)

    metrics = combine_latent_gaps(z_m, z_a)

    return {
        "enabled": True,
        "metrics": metrics,
        "encoder": {
            "checkpoint": checkpoint,
            "checkpoint_md5": _hash_file(checkpoint),
            "device": str(device),
        },
        "determinism": {
            "seed": getattr(SETTINGS, "DETERMINISTIC_SEED", None),
            "torch_deterministic": torch.backends.cudnn.deterministic,
        },
    }


# ============================================================
# Per-tile latent gap
# ============================================================

def compute_per_tile_latent_gap(
    manual_tiles: str,
    auto_tiles: str,
    checkpoint: str,
    out_json: str,
    pairing: str = "filename",  # or "spatial"
) -> Dict[str, Any]:

    _set_determinism(getattr(SETTINGS, "DETERMINISTIC_SEED", None))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = _load_encoder(checkpoint, device)

    # --------------------------------------------------------
    # Tile pairing
    # --------------------------------------------------------
    if pairing == "filename":
        m_files = sorted(f for f in os.listdir(manual_tiles) if f.endswith(".xodr"))
        a_files = sorted(f for f in os.listdir(auto_tiles) if f.endswith(".xodr"))
        pairs = {f: f for f in set(m_files).intersection(a_files)}
        pairing_method = "filename_intersection"
    else:
        pairs = TileMatcher.match(manual_tiles, auto_tiles)
        pairing_method = "spatial_iou"

    per_tile: Dict[str, Dict[str, float]] = {}
    skipped = []

    for m_name, a_name in pairs.items():
        m_path = os.path.join(manual_tiles, m_name)
        a_path = os.path.join(auto_tiles, a_name)

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

        per_tile[m_name] = combine_latent_gaps(z_m, z_a)

    out = {
        "enabled": True,
        "pairing_method": pairing_method,
        "n_tiles": len(per_tile),
        "skipped_tiles": skipped,
        "latent_gap_per_tile": per_tile,
        "encoder": {
            "checkpoint": checkpoint,
            "checkpoint_md5": _hash_file(checkpoint),
            "device": str(device),
        },
        "determinism": {
            "seed": getattr(SETTINGS, "DETERMINISTIC_SEED", None),
            "torch_deterministic": torch.backends.cudnn.deterministic,
        },
    }

    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    return out
