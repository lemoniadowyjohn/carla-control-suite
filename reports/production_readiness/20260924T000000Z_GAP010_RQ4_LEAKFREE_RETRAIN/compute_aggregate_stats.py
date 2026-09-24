#!/usr/bin/env python3
"""Compute aggregate_stats.json for the GAP-010 leak-free 5-seed retrain,
in the SAME schema as reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/aggregate_stats.json
so the new number is directly comparable in kind to the old one.

Methodology (matches C21_STATISTICAL_PROVENANCE.md): mean + 95% bootstrap CI
over the 5 per-seed cosine_distance / cosine_similarity values. Uses the
current canonical bootstrap implementation in gnn_provenance.summarize_runs()
(deterministic seed=0, n_boot=2000, percentile 2.5/97.5, sample std ddof=1)
rather than reinventing a second implementation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(r"G:\gap010-rq4-retrain-20260924")
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.domain_gap_gnn import gnn_provenance as prov  # noqa: E402

OUT_ROOT = Path(__file__).resolve().parent
SEEDS = [42, 43, 44, 45, 46]


def main() -> int:
    cosine_distance_values = []
    cosine_similarity_values = []
    per_seed = {}
    for seed in SEEDS:
        report_path = OUT_ROOT / f"seed_{seed}" / "gnn_training_report.json"
        if not report_path.is_file():
            print(f"MISSING report for seed {seed}: {report_path}")
            return 1
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("status") != "COMPLETE":
            print(f"seed {seed} status != COMPLETE: {report.get('status')}")
            return 1
        metrics = (report.get("latent_gap") or {}).get("metrics") or {}
        cd = metrics.get("cosine_distance")
        cs = metrics.get("cosine_similarity")
        if cd is None or cs is None:
            print(f"seed {seed} missing cosine metrics: {metrics}")
            return 1
        cosine_distance_values.append(float(cd))
        cosine_similarity_values.append(float(cs))
        per_seed[str(seed)] = {
            "cosine_distance": float(cd),
            "cosine_similarity": float(cs),
            "checkpoint": report.get("checkpoint"),
            "checkpoint_md5": ((report.get("latent_gap") or {}).get("encoder") or {}).get("checkpoint_md5"),
            "final_loss": report.get("final_loss"),
            "epochs_completed": report.get("epochs_completed"),
            "tile_count": report.get("tile_count"),
            "source_sha_exclusion_contract": report.get("source_sha_exclusion_contract"),
        }

    cd_summary = prov.summarize_runs(cosine_distance_values)
    cs_summary = prov.summarize_runs(cosine_similarity_values)

    ci_excludes_zero_similarity = bool(
        cs_summary["ci95_low"] > 0.0 or cs_summary["ci95_high"] < 0.0
    ) or bool(
        cs_summary["bootstrap_ci95_low"] > 0.0 or cs_summary["bootstrap_ci95_high"] < 0.0
    )
    # Match the original file's stricter framing: CI (bootstrap) excludes zero
    # only if BOTH bounds are on the same side of zero.
    boot_lo = cs_summary["bootstrap_ci95_low"]
    boot_hi = cs_summary["bootstrap_ci95_high"]
    ci_excludes_zero_similarity = bool(boot_lo > 0.0) or bool(boot_hi < 0.0)
    if boot_lo <= 0.0 <= boot_hi:
        ci_excludes_zero_similarity = False

    out = {
        "seeds": SEEDS,
        "cosine_distance": {
            "values": cosine_distance_values,
            "mean": cd_summary["mean"],
            "std": cd_summary["std"],
            "ci95_bootstrap": [cd_summary["bootstrap_ci95_low"], cd_summary["bootstrap_ci95_high"]],
        },
        "cosine_similarity": {
            "values": cosine_similarity_values,
            "mean": cs_summary["mean"],
            "std": cs_summary["std"],
            "ci95_bootstrap": [cs_summary["bootstrap_ci95_low"], cs_summary["bootstrap_ci95_high"]],
        },
        "ci_excludes_zero_similarity": ci_excludes_zero_similarity,
        "per_seed_detail": per_seed,
        "methodology": (
            "Same design as C21_STATISTICAL_PROVENANCE.md: 562 union_tiles, "
            "50 epochs, batch 16, lr 1e-4, CPU, seeds [42,43,44,45,46]. "
            "Mean + 95% bootstrap CI over n=5 seeds (deterministic bootstrap, "
            "seed=0, n_boot=2000, percentile 2.5/97.5, via "
            "gnn_provenance.summarize_runs()). DIFFERENCE from the original "
            "C21_GNN_AUTHORITATIVE run: GAP-010 source-SHA exclusion "
            "(exclude_source_xodr=[manual_grid0821.xodr, "
            "candidate_connectivity_repaired.xodr]) was active for every "
            "seed's training set, closing the train/eval content-identity "
            "leak channel that audit_leakage() found in the pre-fix pipeline."
        ),
    }
    out_path = OUT_ROOT / "aggregate_stats.json"
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "per_seed_detail"}, indent=2))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
