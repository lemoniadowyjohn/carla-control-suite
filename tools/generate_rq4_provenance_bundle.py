#!/usr/bin/env python3
"""OC-51 (RQ4): generate the provenance report bundle.

Writes reports/production_readiness/<RUN_ID>_RQ4_GNN_PROVENANCE/ with:
  AUTHORITATIVE_PATH.json
  GRAPH_SCHEMA.json
  DATASET_MANIFEST.json
  K_SWEEP_PROTOCOL.json
  CHECKPOINT_CONTRACT.json
  LEAKAGE_AUDIT.json
  HISTORICAL_PROVENANCE_CLASSIFICATION.json
  TEST_RESULTS.json   (placeholder PENDING; filled by the pytest step)

Deterministic and offline. Missing full-map inputs are recorded as
INCOMPLETE, never as a pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.domain_gap_gnn import gnn_provenance as prov  # noqa: E402
from ultimate_pipeline.domain_gap_gnn.graph_builder import (  # noqa: E402
    EDGE_SEMANTICS,
    GRAPH_SCHEMA_VERSION,
    JUNCTION_EDGE_POLICY,
    LANE_TYPES,
    NODE_FEATURE_NAMES,
    MapGraphBuilder,
    describe_graph_schema,
)
from ultimate_pipeline.domain_gap_gnn.run_ksweep import (  # noqa: E402
    DEFAULT_SELECTION_SEED,
    DEFAULT_TRAINING_SEEDS,
    K_VALUES,
)

RUN_ID = "20260919"
BUNDLE_DIR = (
    REPO_ROOT / "reports" / "production_readiness" / f"{RUN_ID}_RQ4_GNN_PROVENANCE"
)


def _write(name: str, payload: dict) -> Path:
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    p = BUNDLE_DIR / name
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {p}")
    return p


def _sha_or_missing(path: Path) -> dict:
    if path.is_file():
        return {"path": str(path.relative_to(REPO_ROOT)), "sha256": prov.sha256_file(path),
                "bytes": int(path.stat().st_size)}
    return {"path": str(path.relative_to(REPO_ROOT)), "sha256": "MISSING",
            "bytes": -1}


def build_authoritative_path(git_sha: str) -> dict:
    files = [
        "ultimate_pipeline/domain_gap_gnn/graph_builder.py",
        "ultimate_pipeline/domain_gap_gnn/map_tile_dataset.py",
        "ultimate_pipeline/domain_gap_gnn/map_encoder.py",
        "ultimate_pipeline/domain_gap_gnn/train_map_encoder.py",
        "ultimate_pipeline/domain_gap_gnn/run_ksweep.py",
        "ultimate_pipeline/domain_gap_gnn/latent_gap_runner.py",
        "ultimate_pipeline/domain_gap_gnn/gnn_provenance.py",
        "ultimate_pipeline/tools/run_gnn_pipeline.py",
    ]
    entries = []
    for rel in files:
        p = REPO_ROOT / rel
        entries.append({
            "file": rel,
            "sha256": prov.sha256_file(p) if p.is_file() else "MISSING",
            "role": "AUTHORITATIVE" if p.is_file() else "MISSING",
        })
    return {
        "run_id": RUN_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "authoritative_modules": entries,
        "historical_only": [
            {
                "path": "reports/post_audit_hardening/C18_GNN_LATENT_GAP/",
                "verdict": "HISTORICAL — single-seed prototype, descriptive IDs",
            },
            {
                "path": "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/",
                "verdict": "HISTORICAL — 5-seed union-tiles run; checkpoints are "
                           "LEGACY_UNBOUND (no manifests); tile set absent "
                           "from this checkout",
            },
            {
                "path": "reports/production_readiness/20260915T233000Z_DOMAIN_GAP_GNN_V2/",
                "verdict": "HISTORICAL — adversarial audit with descriptive "
                           "placeholder hashes, reclassified LEGACY_DESCRIPTIVE_PROVENANCE",
            },
        ],
    }


def build_graph_schema() -> dict:
    schemas = {}
    for mode in ("legacy", "polynomial"):
        desc = describe_graph_schema(width_mode=mode)
        schemas[mode] = {
            "descriptor": desc,
            "graph_schema_sha256": prov.graph_schema_hash(desc),
        }
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "node_feature_names": list(NODE_FEATURE_NAMES),
        "lane_type_vocabulary": list(LANE_TYPES),
        "edge_semantics": list(EDGE_SEMANTICS),
        "junction_edge_policy": JUNCTION_EDGE_POLICY,
        "modes": schemas,
        "note": "legacy (width_a_only_v0) reproduces PRE_FIX embeddings; "
                "polynomial (width_poly_v1) is the POST_FIX authoritative "
                "definition. The two hashes differ by construction.",
    }


def build_dataset_manifest(git_sha: str) -> dict:
    ref = REPO_ROOT / "cities" / "ingolstadt" / "manual_grid0821.xodr"
    reference_artifacts = []
    if ref.is_file():
        for mode, strict in (("legacy", False), ("polynomial", True)):
            g = MapGraphBuilder.build_from_xodr(
                str(ref), strict=strict, width_mode=mode
            )
            reference_artifacts.append({
                "artifact": "cities/ingolstadt/manual_grid0821.xodr",
                "sha256": prov.sha256_file(ref),
                "width_mode": mode,
                "node_count": int(g.num_nodes),
                "edge_count": int(g.edge_index.shape[1]),
                "feature_dim": int(g.x.shape[1]),
                "graph_digest": prov.graph_content_digest(g),
            })
    union_tiles = (
        REPO_ROOT / "reports" / "post_audit_hardening"
        / "C21_GNN_AUTHORITATIVE" / "union_tiles"
    )
    present = sorted(p.name for p in union_tiles.glob("*.xodr")) if union_tiles.is_dir() else []
    return {
        "git_sha": git_sha,
        "reference_artifact_manifest": reference_artifacts,
        "authoritative_training_tile_set": {
            "expected_location": "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles",
            "tiles_present_in_this_checkout": len(present),
            "status": "INCOMPLETE — training tile bytes absent; no manifest "
                      "claimed for them. Per-run manifests are produced by "
                      "train_map_encoder / run_ksweep at training time.",
        },
        "manifest_construction": "gnn_provenance.build_training_dataset_manifest "
                                 "(tile path, SHA256, node/edge counts, "
                                 "feature dim, graph digest; canonical hash "
                                 "over tile-sorted records)",
    }


def build_k_sweep_protocol(git_sha: str) -> dict:
    names = [f"tile_{i:03d}.xodr" for i in range(72)]
    example = prov.nested_subsets(names, K_VALUES, DEFAULT_SELECTION_SEED)
    return {
        "git_sha": git_sha,
        "design": "nested_subsets",
        "k_values": list(K_VALUES),
        "default_selection_seed": int(DEFAULT_SELECTION_SEED),
        "default_training_seeds": [int(s) for s in DEFAULT_TRAINING_SEEDS],
        "subset_rule": "subset(K) = P[:K]; P = deterministic permutation of "
                       "sorted eligible tiles from selection_seed "
                       "(random.Random.shuffle; input sorted first, so "
                       "enumeration order cannot leak in)",
        "nesting_verified_in_this_bundle": all(
            example[a] == example[b][:a]
            for a, b in zip(sorted(example), sorted(example)[1:])
        ),
        "seed_separation": {
            "selection_seed": "WHICH tiles per K (subset composition only)",
            "training_seed": "per-run shuffling / init / noise (never changes tiles)",
            "torch_seed": "defaults to training_seed; separately overridable",
        },
        "per_k_reporting": ["n_seeds", "mean", "std", "median", "min/max",
                            "ci95", "bootstrap_ci95", "raw per-run rows kept"],
        "metrics": ["latent cosine_similarity", "l2", "final training loss"],
        "stages": {
            prov.DESCRIPTIVE_K_SWEEP: "This sweep: describes metric-vs-K on the "
                                      "fixed manual-vs-auto pair. No independent "
                                      "generalization claim.",
            prov.MODEL_SELECTION: "Choosing any K/checkpoint on the whole-map "
                                  "pair must be recorded as selection, with criterion.",
            prov.FINAL_EVALUATION: "Requires a held-out map/pair never used for "
                                   "sweeps or selection.",
        },
        "evaluation_pair_reuse_warning": "The manual-vs-auto whole-map pair is "
            "reused across every (K, seed): it is NOT an untouched test set.",
        "historical_confounding_fixed": "pre-fix run_ksweep used seed=42+k with "
            "independent random.sample per K (subset AND seed changed with K); "
            "post-fix design isolates incremental sample-size effects.",
    }


def build_checkpoint_contract() -> dict:
    return {
        "manifest_fields": list(prov.CHECKPOINT_MANIFEST_FIELDS),
        "save_format": {"canonical": ["state_dict", "metadata"],
                        "legacy_compat": ["model_state", "cfg", "seed", "noise_std"],
                        "sidecar": "<checkpoint>.pt.manifest.json"},
        "reuse_policy": "exact compatible identity on graph_schema_sha256, "
                        "training_dataset_manifest_sha256, tile_selection_sha256, "
                        "selection_seed, training_seed, model_config, "
                        "training_config (git_sha drift also forces retrain "
                        "under the default policy). Otherwise retrain or fail "
                        "(--on_checkpoint_mismatch). Legacy checkpoints without "
                        "sidecars are NEVER silently reused.",
        "load_verification": "metadata-bearing checkpoints verify node dim, "
                             "schema hash vs current code, architecture and "
                             "model config; mismatch fails closed. Historical "
                             "raw checkpoints load as LEGACY_UNBOUND_CHECKPOINT.",
        "legacy_policy": "LEGACY_UNBOUND_CHECKPOINT payloads must not be "
                         "presented as authoritative evidence.",
    }


def build_leakage_audit() -> dict:
    # Programmatic checks over what is actually present in this checkout.
    ref = REPO_ROOT / "cities" / "ingolstadt" / "manual_grid0821.xodr"
    hashes = [prov.sha256_file(ref)] if ref.is_file() else []
    dupes = sorted({h for h in hashes if hashes.count(h) > 1})
    audit = prov.audit_leakage(
        train_tile_names=["manual_grid0821.xodr"] if ref.is_file() else [],
        train_tile_hashes=(
            {"manual_grid0821.xodr": hashes[0]} if hashes else {}
        ),
        train_tiles_dir=str(ref.parent),
        test_tile_names=[],
        test_tile_hashes={},
        test_tiles_dir=str(ref.parent),
        eval_pair_paths=[str(ref)] if ref.is_file() else [],
        normalization_fitted_on="train_only",
        test_metrics_used_for_selection=False,
    )
    audit["reference_duplicate_hashes"] = dupes
    audit["normalization_construction"] = (
        "No fitted scaler exists in the current code path: node features are "
        "normalized by fixed SETTINGS constants "
        "(GNN_MAX_SPEED_KMH/GNN_MAX_LANE_WIDTH_M/GNN_MAX_CURVATURE). "
        "There is therefore no scaler-fit leakage by construction; the V2 "
        "audit's 'scaler_v1_def456' refers to nothing in this code path."
    )
    audit["coverage"] = (
        "INCOMPLETE for the historical C21 union-tile train/test split "
        "(tile bytes absent from this checkout). The audit_leakage() helper "
        "is wired into run_ksweep-time reporting; re-run with the tile set "
        "present for a complete verdict."
    )
    return audit


def build_historical_classification(git_sha: str) -> dict:
    ckpt = (REPO_ROOT / "reports" / "post_audit_hardening"
            / "C21_GNN_AUTHORITATIVE" / "seed_42" / "checkpoints"
            / "map_encoder_epoch50.pt")
    c21_report = (REPO_ROOT / "reports" / "post_audit_hardening"
                  / "C21_GNN_AUTHORITATIVE" / "seed_42"
                  / "gnn_training_report.json")
    pre_fix = {}
    if ckpt.is_file():
        pre_fix["c21_seed42_epoch50"] = {
            "checkpoint_sha256": prov.sha256_file(ckpt),
            "format": ["model_state", "cfg", "seed", "noise_std"],
            "classification": prov.LEGACY_UNBOUND_CHECKPOINT,
            "note": "Loads under the new loader (backward compat) but carries "
                    "no manifest: not authoritative evidence until retrained "
                    "under the checkpoint contract.",
        }
    if c21_report.is_file():
        rep = json.loads(c21_report.read_text(encoding="utf-8"))
        pre_fix["c21_seed42_reported_metrics_preserved_verbatim"] = {
            "cosine_similarity": ((rep.get("latent_gap") or {}).get("metrics") or {}).get(
                "cosine_similarity"),
            "l2": ((rep.get("latent_gap") or {}).get("metrics") or {}).get("l2"),
            "final_loss": rep.get("final_loss"),
            "note": "Numbers preserved, NOT recomputed; metrics unchanged by "
                    "this task (no metric was altered to look stronger).",
        }
    ref = REPO_ROOT / "cities" / "ingolstadt" / "manual_grid0821.xodr"
    pre_post = {}
    if ref.is_file():
        g_leg = MapGraphBuilder.build_from_xodr(str(ref), width_mode="legacy")
        g_poly = MapGraphBuilder.build_from_xodr(
            str(ref), strict=True, width_mode="polynomial"
        )
        pre_post = {
            "artifact": "cities/ingolstadt/manual_grid0821.xodr",
            "artifact_sha256": prov.sha256_file(ref),
            "PRE_FIX_legacy_graph_digest": prov.graph_content_digest(g_leg),
            "POST_FIX_polynomial_graph_digest": prov.graph_content_digest(g_poly),
            "topology_nodes_edges_unchanged": (
                int(g_leg.num_nodes) == int(g_poly.num_nodes)
                and int(g_leg.edge_index.shape[1]) == int(g_poly.edge_index.shape[1])
            ),
            "why_numbers_move": "Topology identical; width mean/std now evaluate "
                                "a+b·ds+c·ds²+d·ds³ over each record's domain "
                                "instead of averaging bare `a` coefficients.",
        }
    return {
        "git_sha": git_sha,
        "v2_audit_descriptive_ids": {
            "gnn_schema_v2_abc123": prov.LEGACY_DESCRIPTIVE_PROVENANCE,
            "scaler_v1_def456": prov.LEGACY_DESCRIPTIVE_PROVENANCE,
            "dataset_ingolstadt_v1": prov.LEGACY_DESCRIPTIVE_PROVENANCE,
            "note": "The 20260915 V2 GNN_SCHEMA_CHECKPOINT_AUDIT.json marked these "
                    "VERIFIED; they are non-content labels and are hereby "
                    "reclassified. Real hashes: see GRAPH_SCHEMA.json.",
        },
        "pre_fix_reproduction": pre_fix,
        "pre_vs_post_fix": pre_post,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=RUN_ID)
    args = ap.parse_args()
    global BUNDLE_DIR
    BUNDLE_DIR = (REPO_ROOT / "reports" / "production_readiness"
                  / f"{args.run_id}_RQ4_GNN_PROVENANCE")

    git_sha = prov.get_git_sha(REPO_ROOT)
    versions = prov.get_torch_versions()

    _write("AUTHORITATIVE_PATH.json", build_authoritative_path(git_sha))
    _write("GRAPH_SCHEMA.json", build_graph_schema())
    _write("DATASET_MANIFEST.json", build_dataset_manifest(git_sha))
    _write("K_SWEEP_PROTOCOL.json", build_k_sweep_protocol(git_sha))
    _write("CHECKPOINT_CONTRACT.json", build_checkpoint_contract())
    _write("LEAKAGE_AUDIT.json", build_leakage_audit())
    _write("HISTORICAL_PROVENANCE_CLASSIFICATION.json",
           build_historical_classification(git_sha))
    _write("TEST_RESULTS.json", {
        "status": "PENDING",
        "note": "Filled by the pytest step after the bundle skeleton is generated.",
        "torch_version": versions["torch_version"],
        "torch_geometric_version": versions["torch_geometric_version"],
        "git_sha": git_sha,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
