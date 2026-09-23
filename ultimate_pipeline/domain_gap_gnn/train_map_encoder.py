#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/train_map_encoder.py
#
# OC-51 (RQ4): explicit selection/training/torch seeds, recorded
# determinism level, strict dataset mode, and metadata-bearing checkpoints
# bound to graph schema + dataset manifest + code revision.

from __future__ import annotations

import argparse
import os
import random

import torch
import torch.nn.functional as F
from torch_geometric.loader import DataLoader

from . import gnn_provenance as prov
from .graph_builder import (
    graph_schema_hash,
    node_feature_dim,
)
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
    ap.add_argument(
        "--node_dim",
        type=int,
        default=0,
        help="Node feature width override. 0 = auto-detect from dataset graph.x.",
    )
    ap.add_argument("--hidden_dim", type=int, default=128)
    ap.add_argument("--out_dir", type=str, default="gnn_runs")
    ap.add_argument("--noise_std", type=float, default=0.01,
                    help="Std of Gaussian noise added to node features.")
    ap.add_argument("--seed", type=int, default=0,
                    help="Training seed (shuffling, init, noise).")
    ap.add_argument("--torch_seed", type=int, default=-1,
                    help="Torch RNG seed; -1 (default) = same as --seed.")
    ap.add_argument("--selection_seed", type=int, default=-1,
                    help="Dataset-selection seed that produced tiles_dir. "
                         "-1 (default) = not recorded (null in manifest).")
    ap.add_argument("--strict_dataset", action="store_true",
                    help="RESEARCH_STRICT dataset loading (fail-closed on "
                         "invalid tiles; requires --width_mode polynomial).")
    ap.add_argument("--width_mode", type=str, default="legacy",
                    choices=("legacy", "polynomial"),
                    help="Lane-width feature definition: legacy (PRE_FIX) or "
                         "polynomial (POST_FIX, required for strict).")
    ap.add_argument("--num_workers", type=int, default=0,
                    help="DataLoader workers (0 = deterministic).")
    ap.add_argument("--no_deterministic_algorithms", action="store_true",
                    help="Do NOT request deterministic algorithms "
                         "(default requests them warn-only).")
    ap.add_argument("--temperature", type=float, default=0.5,
                    help="NT-Xent temperature.")
    ap.add_argument(
        "--exclude_source_xodr",
        type=str,
        nargs="*",
        default=[],
        help="GAP-010 source-identity exclusion contract: paths to known "
             "eval/reference XODR files (e.g. the manual/auto whole-map "
             "eval pair, or cities/ingolstadt/manual_grid0821.xodr) whose "
             "content must NEVER become training data. Any file in "
             "--tiles_dir whose SHA-256 matches one of these paths' "
             "content is excluded from both the dataset and its manifest, "
             "regardless of filename.",
    )
    return ap.parse_args()


def _seed_worker(worker_id: int):
    worker_seed = (torch.initial_seed() + worker_id) % 2**32
    random.seed(worker_seed)


def set_seed(seed: int, *, torch_seed: int | None = None,
             deterministic: bool = True):
    """Seed Python, NumPy and torch RNGs (OC-51 §15).

    Keeps the historical ``set_seed(seed)`` call working; the extended
    keyword arguments separate the torch seed and record the determinism
    posture instead of promising byte-identical CUDA training.
    """
    import numpy as np

    training_seed = int(seed)
    ts = int(torch_seed) if torch_seed is not None and int(torch_seed) >= 0 else training_seed
    random.seed(training_seed)
    np.random.seed(training_seed % (2**32))
    torch.manual_seed(ts)
    torch.cuda.manual_seed_all(ts)
    if deterministic:
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        try:
            torch.use_deterministic_algorithms(True, warn_only=True)
        except Exception:
            pass
    return {
        "training_seed": training_seed,
        "torch_seed": ts,
        "deterministic_algorithms_requested": bool(deterministic),
    }


def perturb_graph(batch, noise_std: float):
    """
    Apply a small feature-space perturbation.
    This preserves topology and semantics.
    """
    batch = batch.clone()
    noise = torch.randn_like(batch.x) * noise_std
    batch.x = batch.x + noise
    return batch


def _should_save_checkpoint(epoch_idx: int, total_epochs: int) -> bool:
    """epoch_idx is 0-based, matching `for epoch in range(total_epochs)`.

    Save every 10th epoch, and always save the final epoch regardless of
    where it falls relative to that cadence.
    """
    epoch_num = epoch_idx + 1
    return epoch_num % 10 == 0 or epoch_num == total_epochs


def _nt_xent_loss(z_a: "torch.Tensor", z_b: "torch.Tensor", temperature: float = 0.5) -> "torch.Tensor":
    """
    NT-Xent loss (SimCLR). z_a and z_b are already L2-normalized (shape [N, D]).
    For each i, positive pair is (z_a[i], z_b[i]); negatives are all other 2N-2 embeddings.
    """
    import torch
    import torch.nn.functional as F
    N = z_a.shape[0]
    # Concatenate all 2N embeddings
    z = torch.cat([z_a, z_b], dim=0)  # [2N, D]
    # Pairwise cosine similarity matrix [2N, 2N]
    sim = torch.mm(z, z.t()) / temperature
    # Mask out self-similarity on diagonal
    mask = torch.eye(2 * N, device=z.device).bool()
    sim.masked_fill_(mask, float('-inf'))
    # Positive pair indices: for z_a[i] (row i), positive is z_b[i] (row i+N)
    #                        for z_b[i] (row i+N), positive is z_a[i] (row i)
    labels = torch.cat([
        torch.arange(N, 2 * N, device=z.device),
        torch.arange(0, N, device=z.device)
    ])
    loss = F.cross_entropy(sim, labels)
    return loss


def _graph_content_digest(g) -> str:
    """Deterministic digest of one graph payload (kept for backward compat;
    new code should use gnn_provenance.graph_content_digest)."""
    return prov.graph_content_digest(g)


# ---------------------------------------------------------
# Main training
# ---------------------------------------------------------

def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    torch_seed = int(args.torch_seed) if int(args.torch_seed) >= 0 else int(args.seed)
    selection_seed = (
        None if int(args.selection_seed) < 0 else int(args.selection_seed)
    )
    deterministic_algorithms = not bool(args.no_deterministic_algorithms)
    set_seed(int(args.seed), torch_seed=torch_seed,
             deterministic=deterministic_algorithms)

    # GAP-010 source-identity exclusion contract: hash every declared
    # protected reference path up front so a leaked duplicate inside
    # tiles_dir is excluded from BOTH the dataset actually trained on and
    # the manifest that identifies the resulting checkpoint.
    exclude_hashes = prov.exclusion_hashes_for(list(args.exclude_source_xodr))
    if args.exclude_source_xodr:
        print(
            f"[gnn] source-SHA exclusion requested for "
            f"{len(args.exclude_source_xodr)} path(s); "
            f"{len(exclude_hashes)} resolved to real files on disk"
        )

    # Dataset (deterministic, pre-validated; strict mode is fail-closed).
    ds = MapTileDataset(
        args.tiles_dir,
        strict=bool(args.strict_dataset),
        width_mode=str(args.width_mode),
        exclude_source_hashes=exclude_hashes,
    )
    if len(ds) <= 0:
        raise RuntimeError(f"No graphs available in tiles_dir: {args.tiles_dir}")
    loader_gen = torch.Generator()
    loader_gen.manual_seed(torch_seed)
    dl = DataLoader(
        ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=int(args.num_workers),
        worker_init_fn=_seed_worker if int(args.num_workers) > 0 else None,
        generator=loader_gen if int(args.num_workers) == 0 else None,
    )

    detected_node_dim = int(node_feature_dim())
    try:
        sample_graph = ds[0]
        sample_x = getattr(sample_graph, "x", None)
        if sample_x is not None and getattr(sample_x, "dim", lambda: 0)() == 2:
            detected_node_dim = int(sample_x.shape[1])
    except Exception:
        detected_node_dim = int(node_feature_dim())

    selected_node_dim = int(args.node_dim) if int(args.node_dim) > 0 else int(detected_node_dim)
    print(f"[gnn] auto-detected node_dim={int(detected_node_dim)}")
    if int(args.node_dim) > 0 and int(args.node_dim) != int(detected_node_dim):
        print(
            f"[gnn] using explicit node_dim override={int(args.node_dim)} "
            f"(detected={int(detected_node_dim)})"
        )

    cfg = MapEncoderConfig(node_dim=int(selected_node_dim), hidden_dim=int(args.hidden_dim))
    model = MapEncoder(cfg)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    # ---- Provenance: schema + dataset manifest (content-derived) ----
    # NOTE: the manifest MUST be built with
    # prov.build_training_dataset_manifest (same helper run_ksweep uses for
    # its expected identity), otherwise checkpoint reuse can never verify.
    schema_hash = graph_schema_hash(width_mode=str(args.width_mode))
    manifest_entries, dataset_manifest_sha, tile_hashes = (
        prov.build_training_dataset_manifest(
            args.tiles_dir,
            width_mode=str(args.width_mode),
            strict=bool(args.strict_dataset),
            exclude_source_hashes=exclude_hashes,
        )
    )
    selection_hash = prov.tile_selection_hash(list(tile_hashes), tile_hashes)
    versions = prov.get_torch_versions()
    git_sha = prov.get_git_sha()
    det_summary = prov.summarize_determinism(
        selection_seed=selection_seed,
        training_seed=int(args.seed),
        torch_seed=torch_seed,
        num_workers=int(args.num_workers),
        deterministic_algorithms=deterministic_algorithms,
    )

    model_config = prov.build_model_config(
        node_dim=int(cfg.node_dim),
        hidden_dim=int(cfg.hidden_dim),
        num_layers=int(cfg.num_layers),
        dropout=float(cfg.dropout),
        out_dim=int(cfg.out_dim),
        normalize_embedding=bool(cfg.normalize_embedding),
    )
    training_config = prov.build_training_config(
        epochs=int(args.epochs),
        batch_size=int(args.batch_size),
        lr=float(args.lr),
        noise_std=float(args.noise_std),
        temperature=float(args.temperature),
        width_mode=str(args.width_mode),
        strict_dataset=bool(args.strict_dataset),
        num_workers=int(args.num_workers),
        deterministic_algorithms=bool(deterministic_algorithms),
    )

    print("🧠 Training MapEncoder")
    print(f"   tiles        : {len(ds)}")
    print(f"   epochs       : {args.epochs}")
    print(f"   batch size   : {args.batch_size}")
    print(f"   noise std    : {args.noise_std}")
    print(f"   device       : {device}")
    print(f"   schema       : {schema_hash} (width={args.width_mode})")
    print(f"   dataset      : {dataset_manifest_sha}")
    print(f"   selection    : {selection_hash} (selection_seed={selection_seed})")
    print(f"   determinism  : {det_summary['determinism_level']}")

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

            loss = _nt_xent_loss(z_a, z_b, temperature=float(args.temperature))

            opt.zero_grad()
            loss.backward()
            opt.step()

            total_loss += float(loss.item()) * batch.num_graphs

        avg_loss = total_loss / len(ds)
        print(f"[epoch {epoch+1:03d}/{args.epochs}] loss = {avg_loss:.6f}")

        # Save checkpoint (metadata-bearing, fail-closed on reload)
        if _should_save_checkpoint(epoch, args.epochs):
            ckpt_path = os.path.join(
                args.out_dir, f"map_encoder_epoch{epoch+1}.pt"
            )
            metadata = prov.build_checkpoint_metadata(
                graph_schema_sha256=schema_hash,
                training_dataset_manifest_sha256=dataset_manifest_sha,
                tile_selection_sha256=selection_hash,
                source_tile_hashes=[
                    {"tile": t, "tile_sha256": h}
                    for t, h in sorted(tile_hashes.items())
                ],
                selection_seed=selection_seed,
                training_seed=int(args.seed),
                model_config=model_config,
                training_config=training_config,
                git_sha=git_sha,
                torch_version=str(versions["torch_version"]),
                torch_geometric_version=str(versions["torch_geometric_version"]),
            )
            final_meta = prov.save_checkpoint(
                ckpt_path, model.state_dict(), metadata
            )
            print(f"💾 Saved checkpoint → {ckpt_path}")
            print(f"   checkpoint_sha256={final_meta['checkpoint_sha256']}")


if __name__ == "__main__":
    main()
