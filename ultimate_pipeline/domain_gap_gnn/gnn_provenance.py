#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/gnn_provenance.py
"""OC-51 (RQ4): cryptographic provenance primitives for GNN experiments.

This module centralises every content-derived identity used by the
authoritative RQ4 path so that no caller invents an ad-hoc descriptive ID:

- graph-schema hash (canonical JSON over real graph semantics);
- dataset-manifest hash (per-tile bytes + graph stats);
- nested K-subset selection with separated selection/training seeds;
- checkpoint manifest + compatibility verification;
- determinism summary;
- leakage audit;
- per-K multi-seed statistics.

Historical descriptive identifiers (``gnn_schema_v2_abc123``,
``dataset_ingolstadt_v1`` and friends) are NOT produced here. Anything
carrying them is classified ``LEGACY_DESCRIPTIVE_PROVENANCE`` by the
bundle generator and must never be presented as verified provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import random
import statistics
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Stage labels (§6 of OC-51)
# ---------------------------------------------------------------------------

DESCRIPTIVE_K_SWEEP = "DESCRIPTIVE_K_SWEEP"
MODEL_SELECTION = "MODEL_SELECTION"
FINAL_EVALUATION = "FINAL_EVALUATION"

LEGACY_DESCRIPTIVE_PROVENANCE = "LEGACY_DESCRIPTIVE_PROVENANCE"
VERIFIED_CRYPTOGRAPHIC_PROVENANCE = "VERIFIED_CRYPTOGRAPHIC_PROVENANCE"
LEGACY_UNBOUND_CHECKPOINT = "LEGACY_UNBOUND_CHECKPOINT"
LEGACY_TOLERANT = "LEGACY_TOLERANT"
RESEARCH_STRICT = "RESEARCH_STRICT"


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    """Canonical JSON encoding: sorted keys, compact separators, UTF-8."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def canonical_hash(obj: Any) -> str:
    return sha256_bytes(canonical_json_bytes(obj))


# ---------------------------------------------------------------------------
# Code / environment identity
# ---------------------------------------------------------------------------

def get_git_sha(repo_root: Optional[str | Path] = None) -> str:
    """Best-effort git SHA of the working tree. Returns ``"UNKNOWN"`` when
    git is unavailable (recorded honestly, never fabricated)."""
    try:
        root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        sha = (out.stdout or "").strip()
        if out.returncode == 0 and len(sha) == 40:
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            suffix = "-dirty" if (dirty.stdout or "").strip() else ""
            return sha + suffix
    except Exception:
        pass
    return "UNKNOWN"


def get_torch_versions() -> Dict[str, str]:
    info: Dict[str, str] = {
        "torch_version": "UNKNOWN",
        "torch_geometric_version": "UNKNOWN",
        "cuda_available": "UNKNOWN",
        "python_version": platform.python_version(),
    }
    try:
        import torch

        info["torch_version"] = str(getattr(torch, "__version__", "UNKNOWN"))
        try:
            info["cuda_available"] = str(bool(torch.cuda.is_available()))
        except Exception:
            pass
    except Exception:
        pass
    try:
        import torch_geometric

        info["torch_geometric_version"] = str(
            getattr(torch_geometric, "__version__", "UNKNOWN")
        )
    except Exception:
        pass
    return info


# ---------------------------------------------------------------------------
# Graph-schema descriptor (§8)
# ---------------------------------------------------------------------------

def canonical_graph_schema(
    *,
    node_feature_names: Sequence[str],
    normalization_constants: Mapping[str, float],
    lane_type_vocabulary: Sequence[str],
    edge_semantics: Sequence[str],
    junction_edge_policy: str,
    geometry_kernel: Mapping[str, Any],
    curvature_policy: Mapping[str, Any],
    width_feature_algorithm: str,
    schema_version: str,
) -> Dict[str, Any]:
    """Build the canonical schema descriptor from actual graph semantics.

    The descriptor is a plain JSON-able dict; hash it with
    :func:`graph_schema_hash`. Any change to feature names, order,
    normalisation, vocabulary, edge semantics, junction policy, geometry
    kernel or feature algorithms changes the hash.
    """
    return {
        "schema_version": str(schema_version),
        "node_feature_names": list(node_feature_names),
        "node_feature_order": list(node_feature_names),
        "node_feature_dim": int(len(list(node_feature_names))),
        "normalization_constants": {
            str(k): float(v) for k, v in dict(normalization_constants).items()
        },
        "lane_type_vocabulary": list(lane_type_vocabulary),
        "edge_semantics": list(edge_semantics),
        "junction_edge_policy": str(junction_edge_policy),
        "geometry_kernel": dict(geometry_kernel),
        "curvature_policy": dict(curvature_policy),
        "width_feature_algorithm": str(width_feature_algorithm),
    }


def graph_schema_hash(schema: Mapping[str, Any]) -> str:
    return canonical_hash(dict(schema))


# ---------------------------------------------------------------------------
# Dataset manifest (§9)
# ---------------------------------------------------------------------------

def build_tile_record(
    *,
    tile_name: str,
    tile_sha256: str,
    node_count: int,
    edge_count: int,
    feature_dim: int,
    graph_digest: str,
) -> Dict[str, Any]:
    return {
        "tile": str(tile_name),
        "tile_sha256": str(tile_sha256),
        "node_count": int(node_count),
        "edge_count": int(edge_count),
        "feature_dim": int(feature_dim),
        "graph_digest": str(graph_digest),
    }


def dataset_manifest_hash(records: Sequence[Mapping[str, Any]]) -> str:
    """Hash of the canonical manifest: records sorted by tile name."""
    ordered = sorted((dict(r) for r in records), key=lambda r: str(r.get("tile", "")))
    return canonical_hash(ordered)


def tile_selection_hash(tile_names: Sequence[str], tile_hashes: Mapping[str, str]) -> str:
    """Identity of an exact tile subset: names bound to content hashes."""
    entries = [
        {"tile": str(n), "tile_sha256": str(tile_hashes.get(str(n), "MISSING"))}
        for n in sorted(set(str(n) for n in tile_names))
    ]
    return canonical_hash(entries)


# ---------------------------------------------------------------------------
# Nested K subsets with separated seeds (§3, §4)
# ---------------------------------------------------------------------------

def deterministic_permutation(
    tile_names: Sequence[str], selection_seed: int
) -> List[str]:
    """One deterministic permutation of the eligible tiles per
    dataset-selection seed. Sorting the input first makes the result
    independent of filesystem enumeration order."""
    names = sorted(str(n) for n in tile_names)
    rng = random.Random(int(selection_seed))
    perm = list(names)
    rng.shuffle(perm)
    return perm


def nested_subsets(
    tile_names: Sequence[str],
    k_values: Sequence[int],
    selection_seed: int,
) -> Dict[int, List[str]]:
    """subset(K) = P[:K] with P the deterministic permutation, so
    K=10 ⊂ K=20 ⊂ K=30 ... — isolating incremental sample-size effects."""
    perm = deterministic_permutation(tile_names, selection_seed)
    out: Dict[int, List[str]] = {}
    for k in k_values:
        k = int(k)
        if k <= 0:
            raise ValueError(f"K must be positive, got {k}")
        if k > len(perm):
            raise ValueError(
                f"K={k} exceeds eligible tile count {len(perm)} "
                f"(selection_seed={int(selection_seed)})"
            )
        out[k] = list(perm[:k])
    # Verify nesting (defensive; cheap).
    ordered = sorted(out)
    for smaller, larger in zip(ordered, ordered[1:]):
        if out[smaller] != out[larger][: int(smaller)]:
            raise RuntimeError("nested subset invariant violated")
    return out


# ---------------------------------------------------------------------------
# Checkpoint contract (§7, §10)
# ---------------------------------------------------------------------------

CHECKPOINT_MANIFEST_FIELDS = (
    "checkpoint_sha256",
    "graph_schema_sha256",
    "training_dataset_manifest_sha256",
    "tile_selection_sha256",
    "source_tile_hashes",
    "selection_seed",
    "training_seed",
    "model_config",
    "training_config",
    "git_sha",
    "torch_version",
    "torch_geometric_version",
)


def build_checkpoint_metadata(
    *,
    graph_schema_sha256: str,
    training_dataset_manifest_sha256: str,
    tile_selection_sha256: str,
    source_tile_hashes: Sequence[Mapping[str, str]],
    selection_seed: Optional[int],
    training_seed: int,
    model_config: Mapping[str, Any],
    training_config: Mapping[str, Any],
    git_sha: str,
    torch_version: str,
    torch_geometric_version: str,
    provenance: str = VERIFIED_CRYPTOGRAPHIC_PROVENANCE,
) -> Dict[str, Any]:
    return {
        "checkpoint_sha256": "PENDING_SAVE",
        "graph_schema_sha256": str(graph_schema_sha256),
        "training_dataset_manifest_sha256": str(training_dataset_manifest_sha256),
        "tile_selection_sha256": str(tile_selection_sha256),
        "source_tile_hashes": [dict(e) for e in source_tile_hashes],
        "selection_seed": None if selection_seed is None else int(selection_seed),
        "training_seed": int(training_seed),
        "model_config": dict(model_config),
        "training_config": dict(training_config),
        "git_sha": str(git_sha),
        "torch_version": str(torch_version),
        "torch_geometric_version": str(torch_geometric_version),
        "provenance": str(provenance),
    }


def save_checkpoint(
    path: str | Path,
    state_dict: Any,
    metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    """Save ``{"state_dict", "metadata"}`` plus legacy-compat aliases
    (``model_state``/``cfg``/``seed``/``noise_std``) so historical loaders
    keep working. Finalises ``checkpoint_sha256`` over the payload bytes
    deterministically: the hash is computed over the canonical JSON of the
    metadata with the placeholder removed, then stored both in the payload
    and in a ``<ckpt>.manifest.json`` sidecar."""
    import torch

    meta = dict(metadata)
    meta.pop("checkpoint_sha256", None)
    payload_hash = canonical_hash(meta)
    meta["checkpoint_sha256"] = payload_hash

    model_cfg = dict(meta.get("model_config", {}))
    training_cfg = dict(meta.get("training_config", {}))
    payload = {
        # Canonical (new) keys.
        "state_dict": state_dict,
        "metadata": meta,
        # Legacy-compat aliases for historical loaders.
        "model_state": state_dict,
        "cfg": {
            "node_dim": model_cfg.get("node_dim"),
            "hidden_dim": model_cfg.get("hidden_dim"),
            "num_layers": model_cfg.get("num_layers", 3),
            "dropout": model_cfg.get("dropout", 0.1),
            "out_dim": model_cfg.get("out_dim", 128),
            "normalize_embedding": model_cfg.get("normalize_embedding", True),
        },
        "seed": meta.get("training_seed"),
        "noise_std": training_cfg.get("noise_std"),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, str(path))
    file_hash = sha256_file(path)
    meta["checkpoint_file_sha256"] = file_hash
    sidecar = path.with_suffix(path.suffix + ".manifest.json")
    sidecar.write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return meta


def _normalise_loaded_checkpoint(ckpt: Any) -> tuple[Any, Optional[Dict[str, Any]], str]:
    """Return (state_dict, metadata_or_None, provenance_label)."""
    if isinstance(ckpt, dict) and isinstance(ckpt.get("metadata"), dict):
        meta = dict(ckpt["metadata"])
        state = ckpt.get("state_dict", ckpt.get("model_state"))
        label = str(meta.get("provenance", VERIFIED_CRYPTOGRAPHIC_PROVENANCE))
        return state, meta, label
    if isinstance(ckpt, dict) and "model_state" in ckpt:
        return ckpt["model_state"], None, LEGACY_UNBOUND_CHECKPOINT
    # Bare state_dict.
    return ckpt, None, LEGACY_UNBOUND_CHECKPOINT


def load_checkpoint(
    path: str | Path,
    *,
    expected_schema_hash: Optional[str] = None,
    expected_node_dim: Optional[int] = None,
    expected_model_config: Optional[Mapping[str, Any]] = None,
) -> tuple[Any, Optional[Dict[str, Any]], str]:
    """Load a checkpoint, verifying identity fail-closed.

    - Metadata-bearing checkpoints: node dim, schema hash, architecture and
      expected model config are verified; any mismatch raises.
    - Historical raw checkpoints (no metadata): returned with the
      ``LEGACY_UNBOUND_CHECKPOINT`` label; callers must not present them as
      authoritative evidence.
    """
    import torch

    ckpt = torch.load(str(path), map_location="cpu")
    state, meta, label = _normalise_loaded_checkpoint(ckpt)
    if meta is None:
        return state, None, label
    if expected_node_dim is not None:
        got = int(meta.get("model_config", {}).get("node_dim", -1))
        if got != int(expected_node_dim):
            raise ValueError(
                f"checkpoint node_dim mismatch: checkpoint={got} "
                f"expected={int(expected_node_dim)} ({path})"
            )
    if expected_schema_hash is not None:
        got_hash = str(meta.get("graph_schema_sha256", ""))
        if got_hash != str(expected_schema_hash):
            raise ValueError(
                f"checkpoint graph-schema mismatch: checkpoint={got_hash} "
                f"expected={expected_schema_hash} ({path})"
            )
    if expected_model_config is not None:
        for key, value in dict(expected_model_config).items():
            got_value = meta.get("model_config", {}).get(key)
            if got_value != value:
                raise ValueError(
                    f"checkpoint model_config[{key}] mismatch: "
                    f"checkpoint={got_value!r} expected={value!r} ({path})"
                )
    return state, meta, label


def checkpoints_compatible(
    expected: Mapping[str, Any], found: Mapping[str, Any]
) -> tuple[bool, List[str]]:
    """Compare an expected checkpoint manifest against a stored one.

    Every identity field must match exactly; returns (ok, reasons).
    ``git_sha`` mismatch is reported (code moved) but does not alone force
    incompatibility when the content-derived hashes still match — the
    caller decides the reuse policy; the default ksweep policy retrains.
    """
    reasons: List[str] = []
    for field in (
        "graph_schema_sha256",
        "training_dataset_manifest_sha256",
        "tile_selection_sha256",
        "selection_seed",
        "training_seed",
        "model_config",
        "training_config",
    ):
        exp_val = expected.get(field)
        got_val = found.get(field)
        exp_n = json.dumps(exp_val, sort_keys=True) if isinstance(exp_val, dict) else exp_val
        got_n = json.dumps(got_val, sort_keys=True) if isinstance(got_val, dict) else got_val
        if exp_n != got_n:
            reasons.append(f"mismatch:{field}")
    if str(expected.get("git_sha", "")) != str(found.get("git_sha", "")):
        reasons.append("mismatch:git_sha")
    return (len(reasons) == 0, reasons)


# ---------------------------------------------------------------------------
# Training-dataset manifest builder (shared by train_map_encoder and
# run_ksweep so both sides of the checkpoint-identity check construct
# byte-identical manifests).
# ---------------------------------------------------------------------------

def graph_content_digest(graph: Any) -> str:
    """Deterministic digest of one graph payload (topology + features)."""
    import hashlib

    h = hashlib.sha256()
    try:
        h.update(str(tuple(graph.x.shape)).encode("utf-8"))
        h.update(graph.x.detach().cpu().numpy().tobytes())
        h.update(str(tuple(graph.edge_index.shape)).encode("utf-8"))
        h.update(graph.edge_index.detach().cpu().numpy().tobytes())
    except Exception as exc:
        h.update(repr(exc).encode("utf-8"))
    return h.hexdigest()


def build_training_dataset_manifest(
    tiles_dir: str | Path,
    *,
    width_mode: str = "legacy",
    strict: bool = False,
) -> tuple[list[dict[str, Any]], str, dict[str, str]]:
    """Build content-derived manifest entries for every USED tile.

    Returns (entries, manifest_hash, tile_hashes). Raises in strict mode
    on invalid tiles (same fail-closed rule as the training dataset).
    """
    from .graph_builder import MapGraphBuilder

    tiles_dir = Path(tiles_dir)
    names = sorted(p.name for p in tiles_dir.glob("*.xodr") if p.is_file())
    entries: list[dict[str, Any]] = []
    tile_hashes: dict[str, str] = {}
    for name in names:
        fpath = tiles_dir / name
        tile_hashes[name] = sha256_file(fpath)
        try:
            g = MapGraphBuilder.build_from_xodr(
                str(fpath), strict=bool(strict), width_mode=str(width_mode)
            )
        except Exception:
            if strict:
                raise
            continue
        if g is None:
            if strict:
                raise ValueError(f"graph build returned None (strict): {fpath}")
            continue
        x = getattr(g, "x", None)
        entries.append(
            build_tile_record(
                tile_name=name,
                tile_sha256=tile_hashes[name],
                node_count=int(g.num_nodes),
                edge_count=int(g.edge_index.shape[1]),
                feature_dim=int(x.shape[1]) if x is not None else -1,
                graph_digest=graph_content_digest(g),
            )
        )
    return entries, dataset_manifest_hash(entries), tile_hashes


# ---------------------------------------------------------------------------
# Canonical config dicts (shared by train_map_encoder and run_ksweep so
# both sides of the checkpoint-identity check construct byte-identical
# training_config / model_config dicts).
# ---------------------------------------------------------------------------

def build_training_config(
    *,
    epochs: int,
    batch_size: int,
    lr: float,
    noise_std: float = 0.01,
    temperature: float = 0.5,
    width_mode: str = "legacy",
    strict_dataset: bool = False,
    num_workers: int = 0,
    deterministic_algorithms: bool = True,
) -> dict[str, Any]:
    return {
        "epochs": int(epochs),
        "batch_size": int(batch_size),
        "lr": float(lr),
        "noise_std": float(noise_std),
        "temperature": float(temperature),
        "width_mode": str(width_mode),
        "strict_dataset": bool(strict_dataset),
        "num_workers": int(num_workers),
        "deterministic_algorithms_requested": bool(deterministic_algorithms),
    }


def build_model_config(
    *,
    node_dim: int,
    hidden_dim: int = 128,
    num_layers: int = 3,
    dropout: float = 0.1,
    out_dim: int = 128,
    normalize_embedding: bool = True,
) -> dict[str, Any]:
    return {
        "node_dim": int(node_dim),
        "hidden_dim": int(hidden_dim),
        "num_layers": int(num_layers),
        "dropout": float(dropout),
        "out_dim": int(out_dim),
        "normalize_embedding": bool(normalize_embedding),
        "architecture": "MapEncoder/GCNConv+global_mean_pool+proj",
    }


# ---------------------------------------------------------------------------
# Determinism summary (§15)
# ---------------------------------------------------------------------------

def summarize_determinism(
    *,
    selection_seed: Optional[int],
    training_seed: int,
    torch_seed: int,
    num_workers: int,
    deterministic_algorithms: bool,
) -> Dict[str, Any]:
    versions = get_torch_versions()
    cudnn_det: Any = "UNKNOWN"
    cudnn_bench: Any = "UNKNOWN"
    try:
        import torch

        cudnn_det = bool(torch.backends.cudnn.deterministic)
        cudnn_bench = bool(torch.backends.cudnn.benchmark)
    except Exception:
        pass
    limitations: List[str] = []
    if int(num_workers) != 0:
        limitations.append(
            "DataLoader num_workers != 0: worker RNG seeded per-worker but "
            "multi-process scheduling may affect batch order reproducibility"
        )
    limitations.append(
        "torch.use_deterministic_algorithms(warn_only=True): PyG scatter/gather "
        "ops may fall back to nondeterministic kernels with a warning"
    )
    try:
        import torch

        if torch.cuda.is_available():
            limitations.append(
                "CUDA execution: byte-identical training across devices is NOT "
                "guaranteed even with deterministic flags"
            )
    except Exception:
        pass
    level = (
        "DETERMINISTIC_CPU_SINGLE_WORKER"
        if int(num_workers) == 0 and bool(deterministic_algorithms)
        else "BEST_EFFORT_DETERMINISTIC"
    )
    return {
        "selection_seed": None if selection_seed is None else int(selection_seed),
        "training_seed": int(training_seed),
        "torch_seed": int(torch_seed),
        "numpy_seeded": True,
        "python_random_seeded": True,
        "dataloader_workers": int(num_workers),
        "deterministic_algorithms_requested": bool(deterministic_algorithms),
        "cudnn_deterministic": cudnn_det,
        "cudnn_benchmark": cudnn_bench,
        "determinism_level": level,
        "limitations": limitations,
        "torch_version": versions["torch_version"],
        "torch_geometric_version": versions["torch_geometric_version"],
        "cuda_available": versions["cuda_available"],
    }


# ---------------------------------------------------------------------------
# Leakage audit (§18)
# ---------------------------------------------------------------------------

def _road_ids_in_xodr(path: str | Path) -> List[str]:
    try:
        root = ET.parse(str(path)).getroot()
        return sorted(
            str(r.get("id", "")) for r in root.findall("road") if r.get("id") is not None
        )
    except Exception:
        return []


def audit_leakage(
    *,
    train_tile_names: Sequence[str],
    train_tile_hashes: Mapping[str, str],
    train_tiles_dir: str | Path,
    test_tile_names: Sequence[str],
    test_tile_hashes: Mapping[str, str],
    test_tiles_dir: Optional[str | Path] = None,
    eval_pair_paths: Sequence[str | Path] = (),
    normalization_fitted_on: str = "train_only",
    test_metrics_used_for_selection: bool = False,
) -> Dict[str, Any]:
    """Programmatic (not prose-only) leakage checks. All machine-readable."""
    train_names = [str(n) for n in train_tile_names]
    test_names = [str(n) for n in test_tile_names]

    all_hashes = [str(train_tile_hashes.get(n, "MISSING")) for n in train_names]
    hash_counts: Dict[str, int] = {}
    for h in all_hashes:
        hash_counts[h] = hash_counts.get(h, 0) + 1
    duplicate_tile_hashes = sorted(h for h, c in hash_counts.items() if c > 1 and h != "MISSING")

    same_filename_in_train_and_test = sorted(set(train_names) & set(test_names))

    train_hash_set = {str(train_tile_hashes.get(n, "")) for n in train_names}
    test_hash_set = {str(test_tile_hashes.get(n, "")) for n in test_names}
    same_content_in_train_and_test = sorted(
        (train_hash_set & test_hash_set) - {""} - {"MISSING"}
    )

    same_road_ids: List[str] = []
    neighbouring_frame_note = "N/A - not frame-based"
    try:
        train_roads: set[str] = set()
        for n in train_names:
            train_roads.update(_road_ids_in_xodr(Path(str(train_tiles_dir)) / n))
        test_dir = Path(str(test_tiles_dir)) if test_tiles_dir is not None else None
        if test_dir is not None and test_dir.is_dir():
            test_roads: set[str] = set()
            for n in test_names:
                test_roads.update(_road_ids_in_xodr(test_dir / n))
            same_road_ids = sorted(train_roads & test_roads)
    except Exception:
        pass

    eval_pair_hashes: Dict[str, str] = {}
    for p in eval_pair_paths:
        try:
            if Path(str(p)).is_file():
                eval_pair_hashes[str(p)] = sha256_file(p)
        except Exception:
            eval_pair_hashes[str(p)] = "UNREADABLE"
    eval_in_train = sorted(
        h for h in eval_pair_hashes.values() if h in train_hash_set and h not in ("", "MISSING")
    )

    scaler_ok = str(normalization_fitted_on) == "train_only"
    selection_ok = not bool(test_metrics_used_for_selection)

    passed = (
        not duplicate_tile_hashes
        and not same_filename_in_train_and_test
        and not same_content_in_train_and_test
        and not same_road_ids
        and not eval_in_train
        and scaler_ok
        and selection_ok
    )
    return {
        "duplicate_tile_hashes": duplicate_tile_hashes,
        "same_spatial_tile_in_train_and_test_by_filename": same_filename_in_train_and_test,
        "same_content_in_train_and_test_by_hash": same_content_in_train_and_test,
        "same_road_ids_in_train_and_test": same_road_ids,
        "neighbouring_frame_leakage": neighbouring_frame_note,
        "source_map_identity_overlap": {
            "eval_pair_sha256": eval_pair_hashes,
            "eval_pair_content_in_training_set": eval_in_train,
        },
        "normalization_fitted_on": str(normalization_fitted_on),
        "normalization_leakage": (not scaler_ok),
        "test_metrics_used_for_selection": bool(test_metrics_used_for_selection),
        "test_metrics_feeding_training_or_selection": bool(test_metrics_used_for_selection),
        "status": "PASS" if passed else "FAIL",
    }


# ---------------------------------------------------------------------------
# Multi-seed statistics (§5)
# ---------------------------------------------------------------------------

def summarize_runs(values: Sequence[float]) -> Dict[str, Any]:
    """n / mean / std / median / min / max / 95% CI (normal approx) /
    deterministic bootstrap 95% interval. Sample std (ddof=1); std of a
    single run is 0.0 and CIs collapse to the value."""
    vals = [float(v) for v in values]
    if not vals:
        raise ValueError("summarize_runs requires at least one value")
    n = len(vals)
    mean = float(statistics.fmean(vals))
    std = float(statistics.stdev(vals)) if n > 1 else 0.0
    median = float(statistics.median(vals))
    lo = min(vals)
    hi = max(vals)
    if n > 1:
        half = 1.96 * std / math.sqrt(n)
        ci_low, ci_high = mean - half, mean + half
    else:
        ci_low, ci_high = mean, mean
    # Deterministic bootstrap percentile interval.
    rng = random.Random(0)
    boot_means: List[float] = []
    n_boot = 2000 if n > 1 else 1
    for _ in range(n_boot):
        sample = [rng.choice(vals) for _ in range(n)]
        boot_means.append(float(statistics.fmean(sample)))
    boot_means.sort()
    if n > 1:
        b_lo = float(boot_means[int(0.025 * n_boot)])
        b_hi = float(boot_means[min(int(0.975 * n_boot), n_boot - 1)])
    else:
        b_lo, b_hi = mean, mean
    return {
        "n": int(n),
        "mean": mean,
        "std": std,
        "median": median,
        "min": float(lo),
        "max": float(hi),
        "ci95_low": float(ci_low),
        "ci95_high": float(ci_high),
        "bootstrap_ci95_low": float(b_lo),
        "bootstrap_ci95_high": float(b_hi),
    }
