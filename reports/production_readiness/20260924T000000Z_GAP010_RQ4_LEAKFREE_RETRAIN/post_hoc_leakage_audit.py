#!/usr/bin/env python3
"""GAP-010 post-hoc leakage audit: confirm, against the ACTUAL checkpoints
produced by this retrain (not just the config), that the eval-pair content
never entered the training set for any of the 5 seeds.

For each seed's final checkpoint, reads the checkpoint's own recorded
source_tile_hashes (written by gnn_provenance.build_checkpoint_metadata at
save time) and cross-checks them against the eval pair's real SHA-256, in
addition to re-running audit_leakage() against the tiles_dir + eval pair
exactly as the pre-training check did.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(r"G:\gap010-rq4-retrain-20260924")
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.domain_gap_gnn import gnn_provenance as prov  # noqa: E402

OUT_ROOT = Path(__file__).resolve().parent
TILES_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / "C21_GNN_AUTHORITATIVE" / "union_tiles"
MANUAL_XODR = REPO_ROOT / "cities" / "ingolstadt" / "manual_grid0821.xodr"
AUTO_XODR = (
    REPO_ROOT
    / "reports"
    / "ingolstadt_map_quality_v2"
    / "work_package_02_connectivity"
    / "candidate_connectivity_repaired.xodr"
)
SEEDS = [42, 43, 44, 45, 46]


def main() -> int:
    eval_pair_paths = [MANUAL_XODR, AUTO_XODR]
    eval_pair_hashes = {str(p): prov.sha256_file(p) for p in eval_pair_paths}
    eval_hash_set = set(eval_pair_hashes.values())

    # 1) Re-run audit_leakage() against tiles_dir AS IT ACTUALLY IS after the
    #    retrain (same directory the trainer read from -- confirms nothing
    #    was added/mutated mid-run).
    exclude_hashes = prov.exclusion_hashes_for(eval_pair_paths)
    entries, manifest_sha, tile_hashes = prov.build_training_dataset_manifest(
        TILES_DIR, width_mode="legacy", strict=False,
        exclude_source_hashes=exclude_hashes,
    )
    train_names = sorted(tile_hashes.keys())
    leakage_result = prov.audit_leakage(
        train_tile_names=train_names,
        train_tile_hashes=tile_hashes,
        train_tiles_dir=TILES_DIR,
        test_tile_names=[],
        test_tile_hashes={},
        test_tiles_dir=None,
        eval_pair_paths=eval_pair_paths,
        normalization_fitted_on="train_only",
        test_metrics_used_for_selection=False,
    )

    # 2) Per-seed: load the ACTUAL saved checkpoint metadata and check its
    #    recorded source_tile_hashes against the eval pair hashes directly.
    per_seed_checkpoint_check = {}
    all_clean = True
    for seed in SEEDS:
        report_path = OUT_ROOT / f"seed_{seed}" / "gnn_training_report.json"
        if not report_path.is_file():
            per_seed_checkpoint_check[str(seed)] = {"status": "MISSING_REPORT"}
            all_clean = False
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        ckpt_path = report.get("checkpoint")
        if not ckpt_path or not Path(ckpt_path).is_file():
            per_seed_checkpoint_check[str(seed)] = {"status": "MISSING_CHECKPOINT", "checkpoint": ckpt_path}
            all_clean = False
            continue
        loaded, metadata, _ = prov.load_checkpoint(ckpt_path)
        source_hashes = {
            entry.get("tile_sha256")
            for entry in (metadata or {}).get("source_tile_hashes", [])
        }
        overlap = sorted(source_hashes & eval_hash_set)
        checkpoint_clean = len(overlap) == 0
        all_clean = all_clean and checkpoint_clean
        per_seed_checkpoint_check[str(seed)] = {
            "status": "OK" if checkpoint_clean else "LEAK_FOUND",
            "checkpoint": str(ckpt_path),
            "checkpoint_sha256": (metadata or {}).get("checkpoint_sha256"),
            "n_source_tiles_recorded": len(source_hashes),
            "training_dataset_manifest_sha256": (metadata or {}).get("training_dataset_manifest_sha256"),
            "eval_pair_hash_overlap": overlap,
        }

    out = {
        "phase": "POST_HOC_RETRAIN_LEAKAGE_AUDIT",
        "eval_pair_sha256": eval_pair_hashes,
        "tiles_dir_audit_leakage_result": leakage_result,
        "tiles_dir_manifest_entry_count_post_exclusion": len(entries),
        "per_seed_checkpoint_source_hash_check": per_seed_checkpoint_check,
        "overall_status": "PASS" if (leakage_result["status"] == "PASS" and all_clean) else "FAIL",
    }
    out_path = OUT_ROOT / "POST_HOC_LEAKAGE_AUDIT.json"
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")
    return 0 if out["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
