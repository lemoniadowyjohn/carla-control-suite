#!/usr/bin/env python3
"""Batch 11 RQ4 lane: emit the reproducibility / provenance / supersession pack.

Emits nine JSON evidence files into ``reports/parallel_wave/rq4/``:

    RQ4_EVIDENCE_INVENTORY.json
    RQ4_LEAKAGE_REVERIFICATION.json
    RQ4_AGGREGATE_RECOMPUTATION.json
    RQ4_REPRODUCIBILITY_MANIFEST.json
    RQ4_CHECKPOINT_DURABILITY.json
    RQ4_SUPERSESSION_PLAN.json
    RQ4_CLEAN_CLONE_REPRODUCIBILITY.json
    RQ4_NEGATIVE_CONTROLS.json
    FINAL_VERDICT.json

Nothing pre-existing is written to. The tool is read-only with respect to every
RQ4 artifact that predates this lane.

Usage:
    python tools/rq4_reproducibility_pack.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.domain_gap_gnn import reproducibility_pack as rrp  # noqa: E402

OUT_DIR = Path("reports/parallel_wave/rq4")

BASE_SHA = "7fbd33ffc952aaafaca199f8e4939b1757cb94d6"
BRANCH = "opencode/batch11-rq4-repro-20261002"

OUTPUTS = {
    "reproducibility_manifest": "RQ4_REPRODUCIBILITY_MANIFEST.json",
    "leakage": "RQ4_LEAKAGE_REVERIFICATION.json",
    "recomputation": "RQ4_AGGREGATE_RECOMPUTATION.json",
    "inventory": "RQ4_EVIDENCE_INVENTORY.json",
    "durability": "RQ4_CHECKPOINT_DURABILITY.json",
    "supersession": "RQ4_SUPERSESSION_PLAN.json",
    "clean_clone": "RQ4_CLEAN_CLONE_REPRODUCIBILITY.json",
    "negative_controls": "RQ4_NEGATIVE_CONTROLS.json",
}


def derive_verdict(leakage, recomputation, durability, clean_clone, controls):
    """Derive the single allowed verdict token. No tuning toward a desired one."""
    broken = [c["control"] for c in controls if c["result"] != "PASS"]
    blockers = list(leakage["blockers"])
    integrity = durability.get("integrity_anomalies") or []

    if broken:
        return "RQ4_EVIDENCE_CONTRADICTION_FOUND", [
            "negative control(s) did not detect their failure: " + ", ".join(broken)
        ]
    if leakage["overall_status"] == "FAIL":
        return "RQ4_LEAKAGE_REVERIFICATION_FAIL", [
            "leakage re-verification returned FAIL; see per-seed rows"]
    if integrity:
        return "RQ4_EVIDENCE_CONTRADICTION_FOUND", [
            "checkpoint SHA256 disagrees between POST_HOC_LEAKAGE_AUDIT.json and "
            "RQ4_MASTER_CLOSE_VERIFICATION.json for seeds "
            + ", ".join(str(s) for s in integrity[0]["seeds"])
            + " (same MD5 in both, so one artifact hashed a different target); "
            "unresolvable without the checkpoint bytes"]
    if recomputation["status"] != "RECOMPUTED_MATCHES_COMMITTED":
        return "RQ4_EVIDENCE_CONTRADICTION_FOUND", [
            "independent aggregate recomputation disagrees: "
            + ", ".join(recomputation["disagreements"])]
    if not blockers and clean_clone["classification"] == rrp.FULL_REEXECUTION_CAPABLE:
        return "RQ4_REPRODUCIBILITY_PASS", []
    return "RQ4_RESULT_VALID_REPRODUCIBILITY_PARTIAL", [
        "the leak-free RQ4 result stands and its aggregates reproduce exactly, "
        "but these checks could not be independently executed in this "
        "environment: " + ", ".join(blockers)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(WORKTREE), help="repository root")
    ap.add_argument("--out", default=str(OUT_DIR), help="output report directory")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out = root / args.out
    out.mkdir(parents=True, exist_ok=True)

    manifest = rrp.build_reproducibility_manifest(root)
    leakage = rrp.reverify_leakage(root)
    recomputation = rrp.recompute_aggregates(root)
    durability = rrp.classify_checkpoints(root)
    inventory = rrp.build_evidence_inventory(root, manifest, durability)
    supersession = rrp.build_supersession_plan(root, inventory, manifest)
    clean_clone = rrp.assess_clean_clone(root, manifest, leakage, recomputation)
    control_rows = rrp.run_negative_controls()

    negative = {
        "schema": "RQ4_NEGATIVE_CONTROLS/v1",
        "principle": (
            "Each control mutates exactly one governed property of an otherwise "
            "valid record and asserts the pack REJECTS it. A control that fails "
            "to detect its own failure is reported BROKEN; none is weakened."
        ),
        "live_campaign_untouched": True,
        "controls": control_rows,
        "n_controls": len(control_rows),
        "n_broken": sum(1 for c in control_rows if c["result"] != "PASS"),
        "status": ("ALL_CONTROLS_DETECT_FAILURE"
                   if all(c["result"] == "PASS" for c in control_rows)
                   else "BROKEN_CONTROL_PRESENT"),
    }

    verdict, reasons = derive_verdict(leakage, recomputation, durability,
                                      clean_clone, control_rows)

    docs = {
        "reproducibility_manifest": manifest,
        "leakage": leakage,
        "recomputation": recomputation,
        "inventory": inventory,
        "durability": durability,
        "supersession": supersession,
        "clean_clone": clean_clone,
        "negative_controls": negative,
    }

    generated = {}
    for key, name in OUTPUTS.items():
        p = out / name
        p.write_text(json.dumps(docs[key], indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
        generated[name] = rrp.sha256_file(p)

    final = {
        "schema": "RQ4_BATCH11_FINAL_VERDICT/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "seeds_verified": leakage["n_seeds_verified"],
        "leakage_status": leakage["overall_status"],
        "leakage_content_overlap_zero": leakage[
            "content_overlap_train_vs_eval_zero_for_every_seed"],
        "aggregate_recomputation": recomputation["status"],
        "aggregate_recomputation_superseded_generations": recomputation[
            "superseded_generation_recomputation"]["status"],
        "checkpoint_durability": durability["status"],
        "clean_clone_reproducibility": clean_clone["classification"],
        "superseded_artifact_count": supersession["superseded_artifact_count"],
        "stale_artifact_count": supersession["stale_artifact_count"],
        "contradictory_artifact_count": supersession[
            "contradictory_artifact_count"],
        "negative_controls": negative["status"],
        "claim_boundary_preserved": True,
        "full_retrain_attempted": False,
        "final_verdict": verdict,
        "verdict_reasons": reasons,
        "claim_boundary": rrp.CLAIM_BOUNDARY,
        "emitted_artifacts_sha256": generated,
    }
    final_path = out / "FINAL_VERDICT.json"
    final_path.write_text(json.dumps(final, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")

    print(f"FINAL_VERDICT={verdict}")
    print(f"SEEDS_VERIFIED={final['seeds_verified']}")
    print(f"LEAKAGE_STATUS={final['leakage_status']}")
    print(f"AGGREGATE_RECOMPUTATION={final['aggregate_recomputation']}")
    print(f"CHECKPOINT_DURABILITY={final['checkpoint_durability']}")
    print(f"CLEAN_CLONE_REPRODUCIBILITY={final['clean_clone_reproducibility']}")
    print(f"SUPERSEDED_ARTIFACT_COUNT={final['superseded_artifact_count']}")
    print(f"NEGATIVE_CONTROLS={final['negative_controls']}")
    for r in reasons:
        print(f"  reason: {r}")
    for name, sha in generated.items():
        print(f"  {sha}  {name}")
    print(f"  {rrp.sha256_file(final_path)}  FINAL_VERDICT.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())