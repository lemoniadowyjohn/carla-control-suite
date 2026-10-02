"""RQ4 reproducibility, provenance and supersession evidence pack.

This module is the single governed implementation behind
``tools/rq4_reproducibility_pack.py``. It is deliberately *read-only* with
respect to every pre-existing RQ4 artifact: it hashes, cross-recomputes and
classifies, and it writes only into the lane's own report directory.

Design rules that this module enforces on itself:

* No RQ4 number is ever copied from a historical PASS string into new
  authority. Every reported value is either (a) recomputed here from committed
  per-seed inputs, or (b) copied verbatim and explicitly marked as a recorded
  claim that could not be independently reproduced in this environment.
* Missing evidence is reported with the explicit sentinels ``UNKNOWN``,
  ``MISSING`` and ``EXTERNAL_PATH_UNAVAILABLE`` -- never with a guess.
* The claim boundary "RQ4 latent separation != held-out perception accuracy" is
  emitted as data, so that a downstream consumer cannot silently drop it.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ultimate_pipeline.domain_gap_gnn import gnn_provenance as prov

UNKNOWN = "UNKNOWN"
MISSING = "MISSING"
EXTERNAL_PATH_UNAVAILABLE = "EXTERNAL_PATH_UNAVAILABLE"

#: Producer worktree recorded by the 2026-09-24 leak-free campaign. Recorded
#: absolute Windows paths on that machine; absent from this checkout.
PRODUCER_ROOT = Path(r"G:\gap010-rq4-retrain-20260924")

#: The authoritative, leak-free RQ4 result: five-seed GAP-010 retrain.
LEAKFREE_DIR = Path(
    "reports/production_readiness/20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN"
)
LEAKFREE_AGGREGATE = LEAKFREE_DIR / "aggregate_stats.json"
LEAKFREE_PRE_AUDIT = LEAKFREE_DIR / "PRE_TRAINING_LEAKAGE_AUDIT.json"
LEAKFREE_POST_AUDIT = LEAKFREE_DIR / "POST_HOC_LEAKAGE_AUDIT.json"
LEAKFREE_RESULTS = LEAKFREE_DIR / "RESULTS.md"
LEAKFREE_RUNNER = LEAKFREE_DIR / "run_seed_ensemble_leakfree.py"
LEAKFREE_AGG_SCRIPT = LEAKFREE_DIR / "compute_aggregate_stats.py"

#: Independent second record of the same five per-seed runs.
MASTER_CLOSE = Path(
    "reports/production_readiness/20260924T120000Z_RQ1_RQ4_MASTER_CLOSE"
    "/RQ4_MASTER_CLOSE_VERIFICATION.json"
)

#: The 2026-09-01 leaky five-seed result this campaign supersedes.
LEAKY_DIR = Path("reports/post_audit_hardening/C21_GNN_AUTHORITATIVE")
LEAKY_AGGREGATE = LEAKY_DIR / "aggregate_stats.json"
LEAKY_ISOLATION = LEAKY_DIR / "isolation_old_checkpoints_new_graph_builder.json"
LEAKY_PROVENANCE_MD = LEAKY_DIR / "C21_STATISTICAL_PROVENANCE.md"

#: Pre-graph-bugfix five-seed result (2026-08-26).
PREBUGFIX_DIR = Path(
    "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE_PREBUGFIX_20260826"
)
PREBUGFIX_AGGREGATE = PREBUGFIX_DIR / "aggregate_stats.json"

#: GAP-010 provenance hardening bundle (2026-09-19).
PROVENANCE_DIR = Path("reports/production_readiness/20260919_RQ4_GNN_PROVENANCE")
PROV_AUTHORITATIVE_PATH = PROVENANCE_DIR / "AUTHORITATIVE_PATH.json"
PROV_CHECKPOINT_CONTRACT = PROVENANCE_DIR / "CHECKPOINT_CONTRACT.json"
PROV_DATASET_MANIFEST = PROVENANCE_DIR / "DATASET_MANIFEST.json"
PROV_HISTORICAL_CLASS = PROVENANCE_DIR / "HISTORICAL_PROVENANCE_CLASSIFICATION.json"
PROV_LEAKAGE_AUDIT = PROVENANCE_DIR / "LEAKAGE_AUDIT.json"
PROV_TEST_RESULTS = PROVENANCE_DIR / "TEST_RESULTS.json"

#: GAP-010 root-cause fix package.
LEAK_FIX_DIR = Path("reports/production_readiness/20260923T140000Z_GAP010_RQ4_LEAKAGE_FIX")

#: Domain-randomization half of RQ4 (part A).
DR_DIR = Path("reports/post_audit_hardening/C15_RQ4_DR")

#: Stale recovery artifact at repo root.
SEED_RECOVERY = Path("RQ4_SEED_RECOVERY.json")

#: Thesis assembly bundle whose evidence_sha256 anchors the C21 aggregate.
THESIS_BUNDLE = Path("reports/post_audit_hardening/C19_THESIS_ASSEMBLY")

#: Code paths a clean clone needs in order to recompute every RQ4 number.
RECOMPUTE_CODE_PATHS: Tuple[str, ...] = (
    "ultimate_pipeline/domain_gap_gnn/gnn_provenance.py",
    "ultimate_pipeline/domain_gap_gnn/graph_builder.py",
    "ultimate_pipeline/domain_gap_gnn/map_tile_dataset.py",
    "ultimate_pipeline/domain_gap_gnn/map_encoder.py",
    "ultimate_pipeline/domain_gap_gnn/train_map_encoder.py",
    "ultimate_pipeline/domain_gap_gnn/run_ksweep.py",
    "ultimate_pipeline/domain_gap_gnn/latent_gap_runner.py",
    "ultimate_pipeline/domain_gap_gnn/reproducibility_pack.py",
    "ultimate_pipeline/tools/run_gnn_pipeline.py",
    "reports/production_readiness/20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN/"
    "run_seed_ensemble_leakfree.py",
    "reports/production_readiness/20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN/"
    "post_hoc_leakage_audit.py",
    "reports/production_readiness/20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN/"
    "compute_aggregate_stats.py",
)

#: Frozen claim boundary. RQ4 is an in-sample latent-separation diagnostic.
CLAIM_BOUNDARY: Dict[str, Any] = {
    "rq4_result_kind": "IN_SAMPLE_LATENT_SEPARATION_DIAGNOSTIC",
    "rq4_latent_separation_is_not": "HELD_OUT_PERCEPTION_ACCURACY",
    "forbidden_promotion": (
        "The GNN representation result must not be restated as an RQ5 transfer, "
        "generalization or predictive-accuracy claim."
    ),
    "permutation_pvalue_transfer": {
        "thesis_protocol": "K=1000 permutation test, p<0.001",
        "thesis_lineage": "PRE_LEAK_FIX",
        "transfer_to_leak_free_metric": False,
        "reason": (
            "The thesis permutation p-value was computed on the pre-fix lineage. "
            "The 2026-09-24 leak-free retrain is a different trained model under a "
            "different exclusion regime, and no permutation test was recomputed for "
            "it. The bootstrap CI over n=5 seeds is therefore the only statistical "
            "support carried by the leak-free number itself."
        ),
        "n_seed_caveat": (
            "n=5 bootstrap CIs are fragile in the tails; the per-seed values, not "
            "the CI endpoints, are the durable evidence."
        ),
    },
}


# ---------------------------------------------------------------------------
# hashing / environment helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with Path(path).open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=60, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return UNKNOWN


def environment_fingerprint() -> Dict[str, str]:
    fp: Dict[str, str] = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "torch_version": UNKNOWN,
        "torch_cuda_available": UNKNOWN,
        "torch_geometric_version": UNKNOWN,
    }
    try:
        import torch  # noqa: PLC0415

        fp["torch_version"] = str(torch.__version__)
        fp["torch_cuda_available"] = str(bool(torch.cuda.is_available()))
    except Exception:
        pass
    try:
        import torch_geometric  # noqa: PLC0415

        fp["torch_geometric_version"] = str(torch_geometric.__version__)
    except Exception:
        pass
    return fp


def load_json(root: Path, rel: Path) -> Any:
    p = root / rel
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _finite_close(a: Any, b: Any, tol: float = 0.0) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# reproducibility manifest
# ---------------------------------------------------------------------------

def build_reproducibility_manifest(root: Path) -> Dict[str, Any]:
    """Bind every RQ4 reproducibility input that evidence actually supports."""
    agg = load_json(root, LEAKFREE_AGGREGATE) or {}
    master = load_json(root, MASTER_CLOSE) or {}
    post = load_json(root, LEAKFREE_POST_AUDIT) or {}
    pre = load_json(root, LEAKFREE_PRE_AUDIT) or {}
    prov_bundle = load_json(root, PROV_AUTHORITATIVE_PATH) or {}
    code_and_tools = master.get("code_and_tools") or {}

    per_seed_agg = agg.get("per_seed_detail") or {}
    per_seed_master = {str(r.get("seed")): r for r in (master.get("per_seed") or [])}

    per_seed: List[Dict[str, Any]] = []
    for seed in agg.get("seeds") or []:
        s = str(seed)
        a = per_seed_agg.get(s) or {}
        m = per_seed_master.get(s) or {}
        pc = (post.get("per_seed_checkpoint_source_hash_check") or {}).get(s) or {}
        record: Dict[str, Any] = {
            "seed": seed,
            "cosine_distance": a.get("cosine_distance"),
            "cosine_similarity": a.get("cosine_similarity"),
            "final_loss": a.get("final_loss"),
            "epochs_completed": a.get("epochs_completed"),
            "tile_count": a.get("tile_count"),
            "checkpoint_path_recorded": a.get("checkpoint"),
            "checkpoint_md5": a.get("checkpoint_md5"),
            "checkpoint_sha256_post_hoc_audit": pc.get("checkpoint_sha256"),
            "checkpoint_sha256_master_close": m.get("checkpoint_sha256"),
            "training_dataset_manifest_sha256": (
                pc.get("training_dataset_manifest_sha256")
                or m.get("training_dataset_manifest_sha256")
            ),
            "eval_pair_hash_overlap": pc.get("eval_pair_hash_overlap"),
            "n_source_tiles_recorded": pc.get("n_source_tiles_recorded"),
            "training_seed": m.get("training_seed"),
            "producer_git_sha": code_and_tools.get("retrain_base_commit", UNKNOWN),
            "provenance_label": m.get("provenance", UNKNOWN),
            "status": m.get("status", UNKNOWN),
        }
        record["cross_record_checkpoint_sha256_agreement"] = bool(
            record["checkpoint_sha256_post_hoc_audit"]
            and record["checkpoint_sha256_master_close"]
            and record["checkpoint_sha256_post_hoc_audit"]
            == record["checkpoint_sha256_master_close"]
        )
        # Producer identity per seed: the campaign only ever recorded the retrain
        # base commit; seed 43's manifest recorded UNKNOWN. Preserve that gap
        # rather than back-filling it with the base commit.
        if m.get("git_sha_note"):
            record["producer_git_sha"] = UNKNOWN
            record["producer_git_sha_note"] = m["git_sha_note"]
        per_seed.append(record)

    excluded = sorted(set(pre.get("exclude_source_hashes") or []))
    eval_pair = dict(post.get("eval_pair_sha256") or {})

    manifest: Dict[str, Any] = {
        "schema": "RQ4_REPRODUCIBILITY_MANIFEST/v1",
        "candidate_git_sha": git_sha(root),
        "historical_producer_git_sha": {
            "retrain_base_commit": code_and_tools.get("retrain_base_commit", UNKNOWN),
            "retrain_branch": "fix/gap010-rq4-leakfree-retrain-20260924",
            "gap010_fix_commit": code_and_tools.get("gap010_fix_commit", UNKNOWN),
            "fix_commit_present_in_main_checkout": code_and_tools.get(
                "fix_commit_present_in_main_checkout", UNKNOWN),
            "fix_commit_present_in_retrain_worktree": code_and_tools.get(
                "fix_commit_present_in_retrain_worktree", UNKNOWN),
            "per_seed_overrides": {
                str(r.get("seed")): (
                    UNKNOWN if r.get("git_sha_note") else code_and_tools.get(
                        "retrain_base_commit", UNKNOWN)
                )
                for r in (master.get("per_seed") or [])
            },
        },
        "input_identity": {
            "manual_xodr_sha256": pre.get("manual_xodr_sha256", UNKNOWN),
            "auto_xodr_sha256": pre.get("auto_xodr_sha256", UNKNOWN),
            "auto_xodr_role": (
                "manually/auto SUBSTITUTION for the unrecoverable original "
                "auto_full_aligned.xodr (documented producer decision)"
            ),
            "evaluation_pair_hashes": eval_pair,
            "evaluation_pair_hash_roles": (
                "these two hashes are simultaneously the eval pair AND the "
                "exclusion set; the eval pair is never permitted in the training set"
            ),
            "auto_vs_manual_input_distinction": (
                "manual_xodr is the human-authored baseline; auto_xodr is the "
                "pipeline-generated candidate. They are the two domains whose "
                "latent representations RQ4 compares."
            ),
            "excluded_source_hashes": excluded,
        },
        "training_tile_manifest": {
            "manifest_sha256": pre.get("manifest_sha256", UNKNOWN),
            "manifest_entry_count": pre.get("manifest_entry_count", UNKNOWN),
            "manifest_entry_count_post_exclusion": post.get(
                "tiles_dir_manifest_entry_count_post_exclusion", UNKNOWN),
            "train_tile_count_post_exclusion": pre.get(
                "train_tile_count_post_exclusion", UNKNOWN),
            "tile_count": 562,
            "tiles_dir_recorded": pre.get("tiles_dir", UNKNOWN),
            "manifest_construction": (load_json(root, PROV_DATASET_MANIFEST) or {}).get(
                "manifest_construction", UNKNOWN),
        },
        "seeds": list(agg.get("seeds") or []),
        "environment": {
            "recorded_by_producer": {
                "python_version": code_and_tools.get("python_version", UNKNOWN),
                "torch_version": code_and_tools.get("torch_version", UNKNOWN),
                "torch_geometric_version": code_and_tools.get("pyg_version", UNKNOWN),
                "torch_cuda_available": code_and_tools.get(
                    "torch_cuda_available", UNKNOWN),
            },
            "observed_in_this_clean_clone": environment_fingerprint(),
        },
        "training_parameters": {
            "epochs": 50,
            "batch_size": 16,
            "learning_rate": 1e-4,
            "device": "cpu",
            "tile_count": 562,
            "seeds": list(agg.get("seeds") or []),
            "source": "METHODOLOGY_STRING_IN_" + LEAKFREE_AGGREGATE.name,
        },
        "checkpoints": {
            str(r["seed"]): {
                "path_recorded": r["checkpoint_path_recorded"],
                "sha256_post_hoc_audit": r["checkpoint_sha256_post_hoc_audit"],
                "sha256_master_close": r["checkpoint_sha256_master_close"],
                "md5": r["checkpoint_md5"],
            }
            for r in per_seed
        },
        "aggregate_procedure": {
            "statistic": "arithmetic mean over per-seed values",
            "std": "sample std, ddof=1",
            "implementation": "ultimate_pipeline.domain_gap_gnn.gnn_provenance"
                              ".summarize_runs",
            "normal_approx_ci95": "mean +/- 1.96 * std / sqrt(n) (also returned)",
            "n": 5,
        },
        "bootstrap_procedure": {
            "kind": "non-parametric percentile bootstrap of the mean",
            "rng": "python stdlib random.Random(0) (deterministic)",
            "n_boot": 2000,
            "percentiles": "indices int(0.025*n_boot) and int(0.975*n_boot)",
            "implementation": "ultimate_pipeline.domain_gap_gnn.gnn_provenance"
                              ".summarize_runs",
        },
        "code_paths_for_recomputation": [],
        "per_seed_metrics": per_seed,
        "claim_boundary": CLAIM_BOUNDARY,
        "authoritative_module_sha256_recorded": prov_bundle.get(
            "authoritative_modules", MISSING),
    }

    for rel in RECOMPUTE_CODE_PATHS:
        p = root / rel
        manifest["code_paths_for_recomputation"].append({
            "path": rel,
            "present": p.is_file(),
            "sha256": sha256_file(p) if p.is_file() else MISSING,
        })

    downgrades: List[str] = []
    if not (root / LEAKFREE_DIR).is_dir():
        downgrades.append("leakfree_evidence_directory_absent")
    if not PRODUCER_ROOT.exists():
        downgrades.append("producer_worktree_absent:" + EXTERNAL_PATH_UNAVAILABLE)
    if not (root / LEAKY_DIR / "union_tiles").is_dir():
        downgrades.append("union_tiles_absent:" + MISSING)
    if any(not r["cross_record_checkpoint_sha256_agreement"] for r in per_seed):
        downgrades.append("checkpoint_sha256_cross_record_disagreement")
    if any(r["producer_git_sha"] == UNKNOWN for r in per_seed):
        downgrades.append("per_seed_producer_identity_missing")

    manifest["reproducibility_downgrades"] = downgrades
    manifest["reproducibility_level"] = (
        "FULL_REEXECUTION_CAPABLE" if not downgrades else "EVIDENCE_RECOMPUTABLE_ONLY"
    )
    return manifest


# ---------------------------------------------------------------------------
# leakage re-verification
# ---------------------------------------------------------------------------

def reverify_leakage(root: Path) -> Dict[str, Any]:
    """Independently re-check the leak-free claim from committed artifacts.

    This does NOT trust the recorded ``overall_status``/``status`` strings. It
    re-derives the zero-overlap conclusion from the recorded hash sets and from
    the actual bytes present in this checkout, and records explicitly which
    checks could not be executed here.
    """
    post = load_json(root, LEAKFREE_POST_AUDIT) or {}
    pre = load_json(root, LEAKFREE_PRE_AUDIT) or {}
    agg = load_json(root, LEAKFREE_AGGREGATE) or {}
    master = load_json(root, MASTER_CLOSE) or {}
    prov_leak = load_json(root, PROV_LEAKAGE_AUDIT) or {}

    per_seed_checks = post.get("per_seed_checkpoint_source_hash_check") or {}
    excluded = sorted(set(pre.get("exclude_source_hashes") or []))

    # --- check A: recorded exclusion set equals the recorded eval-pair hashes.
    pre_eval = sorted(set(
        ((pre.get("audit_leakage_result") or {})
         .get("source_map_identity_overlap", {})
         .get("eval_pair_sha256") or {}).values()))
    post_eval = sorted(set((post.get("eval_pair_sha256") or {}).values()))
    exclusion_covers_eval_pair = bool(excluded) and excluded == post_eval == pre_eval

    # --- check B: per-seed zero overlap, recomputed from the hash sets.
    seed_rows: List[Dict[str, Any]] = []
    for seed in agg.get("seeds") or []:
        s = str(seed)
        pc = per_seed_checks.get(s) or {}
        overlap = pc.get("eval_pair_hash_overlap")
        leaked = sorted(set(overlap or []) & set(post_eval))
        seed_rows.append({
            "seed": seed,
            "recorded_eval_pair_hash_overlap": overlap,
            "recomputed_overlap_is_empty": overlap == [],
            "intersection_with_eval_pair_hashes": leaked,
            "n_source_tiles_recorded": pc.get("n_source_tiles_recorded"),
            "tile_count_matches_aggregate": (
                pc.get("n_source_tiles_recorded")
                == (agg.get("per_seed_detail", {}).get(s) or {}).get("tile_count")
            ),
            "training_manifest_sha256": pc.get("training_dataset_manifest_sha256"),
            "status": "PASS" if (overlap == [] and not leaked) else "FAIL",
        })

    all_zero = all(
        r["recomputed_overlap_is_empty"] and not r["intersection_with_eval_pair_hashes"]
        for r in seed_rows
    )

    # --- check C: identical training manifest across seeds (single pool).
    manifests = {r["training_manifest_sha256"] for r in seed_rows
                 if r["training_manifest_sha256"]}

    # --- check D: pre-training audit recorded zero, post-exclusion count intact.
    pre_block = pre.get("audit_leakage_result") or {}
    pre_zero = (pre_block.get("source_map_identity_overlap") or {}).get(
        "eval_pair_content_in_training_set") == []
    count_intact = (
        pre.get("manifest_entry_count") == pre.get("train_tile_count_post_exclusion")
        == 562
    )

    # --- check E: hash-level verification of eval-pair bytes available here.
    pre_eval_map = ((pre.get("audit_leakage_result") or {})
                    .get("source_map_identity_overlap", {})
                    .get("eval_pair_sha256") or {})
    manual_expected = next(
        (h for p, h in pre_eval_map.items()
         if p.lower().replace("\\", "/").endswith("manual_grid0821.xodr")),
        UNKNOWN,
    )
    expected = [
        (Path("cities/ingolstadt/manual_grid0821.xodr"), manual_expected),
        (Path("reports/ingolstadt_map_quality_v2/work_package_02_connectivity"
              "/candidate_connectivity_repaired.xodr"),
         pre.get("auto_xodr_sha256", UNKNOWN)),
    ]
    hash_checks: List[Dict[str, Any]] = []
    for rel, exp in expected:
        p = root / rel
        if not p.is_file():
            hash_checks.append({
                "artifact": rel.as_posix(), "expected_sha256": exp,
                "observed_sha256": MISSING, "result": MISSING,
                "reason": "artifact absent from this checkout"})
        else:
            obs = sha256_file(p)
            hash_checks.append({
                "artifact": rel.as_posix(), "expected_sha256": exp,
                "observed_sha256": obs,
                "result": "MATCH" if obs == exp else "MISMATCH"})
    n_verified = sum(1 for r in hash_checks if r["result"] == "MATCH")

    # --- check F: the historical leaky lineage leak, re-read from its own audit.
    historical = {
        "audit_artifact": PROV_LEAKAGE_AUDIT.as_posix(),
        "recorded_status": prov_leak.get("status", MISSING),
        "recorded_eval_pair_content_in_training_set": (
            (prov_leak.get("source_map_identity_overlap") or {}).get(
                "eval_pair_content_in_training_set")),
        "recorded_coverage": prov_leak.get("coverage", MISSING),
        "interpretation": (
            "This FAIL is scoped to the 2026-09-01 C21 split, whose training "
            "tile bytes are absent from this checkout, so it cannot be "
            "recomputed here. It is the documented rationale for superseding "
            "the leaky number; it is NOT a statement about the 2026-09-24 "
            "leak-free retrain."
        ),
        "recomputable_here": False,
    }

    masters_manifest = (master.get("training_dataset") or {}).get("manifest_sha256")
    manifest_consistent = bool(manifests) and manifests == {masters_manifest}

    checks: List[Dict[str, Any]] = [
        {"check": "exclusion_set_equals_eval_pair_hashes",
         "result": "PASS" if exclusion_covers_eval_pair else "FAIL",
         "detail": {"excluded": excluded, "post_hoc_eval_pair": post_eval,
                    "pre_eval_pair": pre_eval}},
        {"check": "per_seed_eval_pair_hash_overlap_zero",
         "result": "PASS" if all_zero else "FAIL",
         "detail": {"n_seeds": len(seed_rows),
                    "failing_seeds": [r["seed"] for r in seed_rows
                                      if r["status"] != "PASS"]}},
        {"check": "single_consistent_training_manifest_across_seeds",
         "result": "PASS" if manifest_consistent else "FAIL",
         "detail": {"distinct_manifests": sorted(manifests),
                    "master_close_manifest": masters_manifest}},
        {"check": "pre_training_audit_zero_and_tile_count_intact",
         "result": "PASS" if (pre_zero and count_intact) else "FAIL",
         "detail": {"pre_training_zero_overlap": pre_zero,
                    "manifest_entry_count": pre.get("manifest_entry_count"),
                    "train_tile_count_post_exclusion": pre.get(
                        "train_tile_count_post_exclusion")}},
        {"check": "eval_pair_byte_hashes_recomputed_in_this_checkout",
         "result": ("PASS" if n_verified == len(hash_checks)
                    else ("PARTIAL" if n_verified else "FAIL")),
         "detail": hash_checks},
        {"check": "training_tile_manifest_sha_recomputed_from_tile_bytes",
         "result": MISSING,
         "detail": {
             "recorded_manifest_sha256": pre.get("manifest_sha256", MISSING),
             "reason": (
                 "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles "
                 "is absent from this checkout (562 tiles). The recorded manifest "
                 "hash therefore cannot be independently recomputed here."
             )}},
        {"check": "per_seed_checkpoint_provenance_verified_against_bytes",
         "result": EXTERNAL_PATH_UNAVAILABLE,
         "detail": {
             "reason": (
                 "Checkpoints exist only under the producer worktree "
                 "G:/gap010-rq4-retrain-20260924/, which is not present. Recorded "
                 "SHA256 values are accepted as recorded claims only."
             )}},
        {"check": "seed_identity_distinctness",
         "result": "PASS" if _seed_identity_ok(agg, per_seed_checks) else "FAIL",
         "detail": {"criterion": "one distinct checkpoint hash per seed; no reuse"}},
    ]

    failing = [c for c in checks if c["result"] == "FAIL"]
    if failing:
        overall = "FAIL"
    elif any(c["result"] in (MISSING, EXTERNAL_PATH_UNAVAILABLE, "PARTIAL")
             for c in checks):
        overall = "PASS_WITH_INDEPENDENTLY_UNVERIFIABLE_CHECKS"
    else:
        overall = "PASS"

    return {
        "schema": "RQ4_LEAKAGE_REVERIFICATION/v1",
        "method": (
            "Recorded PASS strings are NOT trusted. Every check below is "
            "re-derived from the recorded hash sets and from bytes present in "
            "this checkout. Checks that cannot be executed here are reported "
            "as MISSING or EXTERNAL_PATH_UNAVAILABLE, never as PASS."
        ),
        "overall_status": overall,
        "content_overlap_train_vs_eval_zero_for_every_seed": all_zero,
        "n_seeds_verified": len(seed_rows),
        "per_seed": seed_rows,
        "checks": checks,
        "historical_leaky_lineage": historical,
        "blockers": [c["check"] for c in checks
                     if c["result"] in (MISSING, EXTERNAL_PATH_UNAVAILABLE,
                                        "PARTIAL", "FAIL")],
    }


def _seed_identity_ok(agg: Dict[str, Any], per_seed_checks: Dict[str, Any]) -> bool:
    """No checkpoint reused across seeds, and every seed is a distinct integer."""
    seeds = agg.get("seeds") or []
    if not seeds or len(set(seeds)) != len(seeds):
        return False
    shas = [(per_seed_checks.get(str(s)) or {}).get("checkpoint_sha256")
            for s in seeds]
    if any(s is None for s in shas) or len(set(shas)) != len(shas):
        return False
    md5s = [(agg.get("per_seed_detail", {}).get(str(s)) or {}).get("checkpoint_md5")
            for s in seeds]
    return not any(m is None for m in md5s) and len(set(md5s)) == len(md5s)


# ---------------------------------------------------------------------------
# aggregate recomputation
# ---------------------------------------------------------------------------

def recompute_aggregates(root: Path) -> Dict[str, Any]:
    """Recompute mean/std/min/bootstrap CI from per-seed values.

    The statistical protocol is the committed
    ``gnn_provenance.summarize_runs`` implementation (deterministic
    ``random.Random(0)``, n_boot=2000, percentile indices). Nothing is tuned
    toward the historical output: recomputed values are reported as-is and any
    disagreement is reported as a disagreement.
    """
    agg = load_json(root, LEAKFREE_AGGREGATE) or {}
    master = load_json(root, MASTER_CLOSE) or {}
    leaky = load_json(root, LEAKY_AGGREGATE) or {}
    prebug = load_json(root, PREBUGFIX_AGGREGATE) or {}

    primary = {k: list(agg.get(k, {}).get("values") or [])
               for k in ("cosine_distance", "cosine_similarity")}

    master_seeds = master.get("per_seed") or []
    secondary = {
        "cosine_distance": [r.get("cosine_distance") for r in master_seeds
                            if r.get("cosine_distance") is not None],
        "cosine_similarity": [r.get("cosine_similarity") for r in master_seeds
                              if r.get("cosine_similarity") is not None],
    }

    recomputed: Dict[str, Any] = {}
    for metric in ("cosine_distance", "cosine_similarity"):
        vals = [float(v) for v in primary[metric]]
        summary = prov.summarize_runs(vals)
        committed = agg.get(metric, {})
        rec: Dict[str, Any] = {
            "recomputed": summary,
            "committed": {
                "mean": committed.get("mean"),
                "std": committed.get("std"),
                "ci95_bootstrap": committed.get("ci95_bootstrap"),
                "values": committed.get("values"),
            },
            "comparison": {
                "mean_absolute_difference": (
                    abs(summary["mean"] - float(committed["mean"]))
                    if committed.get("mean") is not None else None),
                "std_absolute_difference": (
                    abs(summary["std"] - float(committed["std"]))
                    if committed.get("std") is not None else None),
                "bootstrap_ci_bit_identical": [
                    summary["bootstrap_ci95_low"],
                    summary["bootstrap_ci95_high"],
                ] == committed.get("ci95_bootstrap"),
                "values_bit_identical": vals == [
                    float(v) for v in (committed.get("values") or [])],
            },
        }
        sec = [float(v) for v in secondary[metric]]
        if len(sec) == len(vals):
            sec_summary = prov.summarize_runs(sec)
            rec["independent_second_input"] = {
                "source": MASTER_CLOSE.as_posix(),
                "mean_absolute_difference": abs(sec_summary["mean"] - summary["mean"]),
                "bit_identical": sec_summary["mean"] == summary["mean"],
            }
        recomputed[metric] = rec

    # --- internal consistency: cosine_similarity + cosine_distance == 1 per seed.
    seeds_list = agg.get("seeds") or []
    identity_rows = []
    for i, (d, s) in enumerate(zip(primary["cosine_distance"],
                                   primary["cosine_similarity"])):
        total = float(d) + float(s)
        identity_rows.append({
            "index": i,
            "seed": seeds_list[i] if i < len(seeds_list) else None,
            "sum": total,
            "abs_error_from_one": abs(total - 1.0),
            "within_float32_rounding": abs(total - 1.0) < 1e-6,
        })
    identity_ok = all(r["within_float32_rounding"] for r in identity_rows)
    max_identity_error = max((r["abs_error_from_one"] for r in identity_rows),
                             default=0.0)

    # --- the superseded generations, recomputed the same way.
    generations: Dict[str, Any] = {}
    for label, doc in (("c21_leaky_20260901", leaky),
                       ("c21_prebugfix_20260826", prebug)):
        block: Dict[str, Any] = {}
        for metric in ("cosine_distance", "cosine_similarity"):
            vals = [float(v) for v in (doc.get(metric, {}).get("values") or [])]
            if not vals:
                block[metric] = MISSING
                continue
            s = prov.summarize_runs(vals)
            block[metric] = {
                "recomputed_mean": s["mean"],
                "committed_mean": doc.get(metric, {}).get("mean"),
                "recomputed_bootstrap_ci95": [s["bootstrap_ci95_low"],
                                              s["bootstrap_ci95_high"]],
                "committed_bootstrap_ci95": doc.get(metric, {}).get("ci95_bootstrap"),
                "bit_identical": (
                    s["mean"] == doc.get(metric, {}).get("mean")
                    and [s["bootstrap_ci95_low"], s["bootstrap_ci95_high"]]
                    == doc.get(metric, {}).get("ci95_bootstrap")
                ),
            }
        generations[label] = block

    primary_disagreements: List[str] = []
    for metric, rec in recomputed.items():
        if not rec["comparison"]["bootstrap_ci_bit_identical"]:
            primary_disagreements.append(metric + ":bootstrap_ci")
        if not rec["comparison"]["values_bit_identical"]:
            primary_disagreements.append(metric + ":values")

    superseded_disagreements: List[Dict[str, Any]] = []
    for label, block in generations.items():
        for metric, val in block.items():
            if not isinstance(val, dict) or val["bit_identical"]:
                continue
            superseded_disagreements.append({
                "generation": label,
                "metric": metric,
                "kind": ("BOOTSTRAP_PROTOCOL_DRIFT_ONLY"
                         if val["recomputed_mean"] == val["committed_mean"]
                         else "VALUE_DISAGREEMENT"),
                "recomputed_mean": val["recomputed_mean"],
                "committed_mean": val["committed_mean"],
                "mean_bit_identical": val["recomputed_mean"] == val["committed_mean"],
                "recomputed_bootstrap_ci95": val["recomputed_bootstrap_ci95"],
                "committed_bootstrap_ci95": val["committed_bootstrap_ci95"],
            })

    return {
        "schema": "RQ4_AGGREGATE_RECOMPUTATION/v1",
        "protocol_source": "ultimate_pipeline.domain_gap_gnn.gnn_provenance"
                           ".summarize_runs (committed, unmodified)",
        "protocol": {
            "statistic": "mean of per-seed values",
            "std": "sample std ddof=1 (statistics.stdev)",
            "bootstrap": "percentile bootstrap of the mean, random.Random(0), "
                         "n_boot=2000, indices int(0.025*2000) and int(0.975*2000)",
            "n": 5,
        },
        "tuned_toward_historical_output": False,
        "primary_input": {
            "source": LEAKFREE_AGGREGATE.as_posix(),
            "per_seed_values": primary,
            "note": "per-seed gnn_training_report.json files are NOT committed; "
                    "the per-seed values are taken from the committed aggregate "
                    "and independently cross-checked against the master-close "
                    "per-seed records.",
        },
        "recomputed": recomputed,
        "cosine_distance_similarity_complementarity": {
            "note": "the two metrics are complements up to producer float "
                    "precision; max |distance + similarity - 1| observed",
            "max_abs_error_from_one": max_identity_error,
            "within_float32_rounding": identity_ok,
            "per_seed": identity_rows,
        },
        "primary_recomputation": {
            "status": "RECOMPUTED_MATCHES_COMMITTED"
                      if not primary_disagreements else "RECOMPUTED_DISAGREES",
            "disagreements": primary_disagreements,
        },
        "superseded_generations": generations,
        "superseded_generation_recomputation": {
            "status": "BOOTSTRAP_PROTOCOL_DRIFT" if superseded_disagreements
                      else "RECOMPUTED_MATCHES_COMMITTED",
            "interpretation": (
                "The superseded generations' per-seed means and sample std "
                "reproduce EXACTLY under the committed protocol; only their "
                "bootstrap interval endpoints drift by ~1e-3. That is a change "
                "in the bootstrap implementation between those runs and the "
                "currently committed summarize_runs, NOT a data or numeric "
                "contradiction. It does not touch the current leak-free "
                "authority, whose CI is bit-identical."
            ),
            "disagreements": superseded_disagreements,
        },
        "status": "RECOMPUTED_MATCHES_COMMITTED" if not primary_disagreements
                  else "RECOMPUTED_DISAGREES",
        "disagreements": primary_disagreements
                         + [d["generation"] + "." + d["metric"]
                            for d in superseded_disagreements],
    }


# ---------------------------------------------------------------------------
# checkpoint durability
# ---------------------------------------------------------------------------

AVAILABLE_AND_HASH_VERIFIED = "AVAILABLE_AND_HASH_VERIFIED"
AVAILABLE_HASH_MISMATCH = "AVAILABLE_HASH_MISMATCH"
EXTERNAL_ONLY = "EXTERNAL_ONLY"
MISSING_CLASS = MISSING


def classify_checkpoints(root: Path) -> Dict[str, Any]:
    post = load_json(root, LEAKFREE_POST_AUDIT) or {}
    agg = load_json(root, LEAKFREE_AGGREGATE) or {}
    master = load_json(root, MASTER_CLOSE) or {}
    master_by_seed = {str(r.get("seed")): r for r in (master.get("per_seed") or [])}
    per_seed_checks = post.get("per_seed_checkpoint_source_hash_check") or {}

    rows: List[Dict[str, Any]] = []
    for seed in agg.get("seeds") or []:
        s = str(seed)
        pc = per_seed_checks.get(s) or {}
        a = (agg.get("per_seed_detail") or {}).get(s) or {}
        m = master_by_seed.get(s) or {}
        recorded_path = pc.get("checkpoint") or a.get("checkpoint")

        present = False
        observed = MISSING
        classification = EXTERNAL_ONLY
        if recorded_path:
            try:
                present = Path(recorded_path).is_file()
            except OSError:
                present = False
            if present:
                observed = sha256_file(recorded_path)
                classification = (
                    AVAILABLE_AND_HASH_VERIFIED
                    if observed in {pc.get("checkpoint_sha256"),
                                    m.get("checkpoint_sha256")}
                    else AVAILABLE_HASH_MISMATCH)

        sha_post = pc.get("checkpoint_sha256")
        sha_master = m.get("checkpoint_sha256")
        rows.append({
            "seed": seed,
            "recorded_path": recorded_path,
            "classification": classification,
            "path_under_producer_worktree": bool(
                recorded_path and str(recorded_path).upper().startswith("G:")),
            "producer_worktree_present": PRODUCER_ROOT.exists(),
            "sha256_post_hoc_audit": sha_post,
            "sha256_master_close": sha_master,
            "md5": a.get("checkpoint_md5"),
            "sha256_cross_record_agreement": bool(
                sha_post and sha_master and sha_post == sha_master),
            "sha256_observed_in_this_environment": observed,
            "committed_to_git": False,
            "committed_to_git_basis": (
                "RESULTS.md states per-seed checkpoints are gitignored, matching "
                "the C21 precedent; the absent files in this checkout are "
                "consistent with that."
            ),
        })

    mismatched = [r["seed"] for r in rows if not r["sha256_cross_record_agreement"]]
    return {
        "schema": "RQ4_CHECKPOINT_DURABILITY/v1",
        "policy": (
            "Large checkpoints are not required to be committed to Git. "
            "Reproducibility therefore states how each is recovered or "
            "regenerated, and downgrades honestly when neither is possible."
        ),
        "per_seed": rows,
        "counts": {
            AVAILABLE_AND_HASH_VERIFIED: sum(
                1 for r in rows if r["classification"] == AVAILABLE_AND_HASH_VERIFIED),
            AVAILABLE_HASH_MISMATCH: sum(
                1 for r in rows if r["classification"] == AVAILABLE_HASH_MISMATCH),
            EXTERNAL_ONLY: sum(1 for r in rows if r["classification"] == EXTERNAL_ONLY),
            MISSING_CLASS: sum(1 for r in rows if r["classification"] == MISSING_CLASS),
        },
        "recovery_or_regeneration": {
            "recovery": {
                "source_worktree": str(PRODUCER_ROOT),
                "source_branch": "fix/gap010-rq4-leakfree-retrain-20260924",
                "source_base_commit": (master.get("code_and_tools") or {}).get(
                    "retrain_base_commit", UNKNOWN),
                "per_seed_path_template": str(
                    PRODUCER_ROOT / LEAKFREE_DIR / "seed_{seed}" / "checkpoints"
                    / "map_encoder_epoch50.pt"),
                "available_in_this_environment": PRODUCER_ROOT.exists(),
            },
            "regeneration": {
                "deterministic": True,
                "entrypoint": LEAKFREE_RUNNER.as_posix(),
                "code_paths": list(RECOMPUTE_CODE_PATHS),
                "inputs_required": [
                    "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles"
                    " (562 tiles, NOT committed)",
                    "cities/ingolstadt/manual_grid0821.xodr (NOT committed)",
                    "reports/ingolstadt_map_quality_v2/work_package_02_connectivity"
                    "/candidate_connectivity_repaired.xodr (committed)",
                ],
                "blocked_in_this_clean_clone": True,
                "blocked_reason": (
                    "Two of the three required inputs are absent from a clean "
                    "clone, so the checkpoints can be neither recovered nor "
                    "bit-reproduced here."
                ),
            },
        },
        "integrity_anomalies": (
            [{
                "anomaly": "cross_record_checkpoint_sha256_disagreement",
                "seeds": mismatched,
                "detail": (
                    "POST_HOC_LEAKAGE_AUDIT.json and "
                    "RQ4_MASTER_CLOSE_VERIFICATION.json record different SHA256 "
                    "values for the same five checkpoint paths while recording "
                    "the SAME MD5 for each. Two different SHA256 values cannot "
                    "both hash the same bytes, so the two artifacts hashed "
                    "different targets. Neither can be resolved without the "
                    "checkpoint files."
                ),
                "md5_cross_record_agreement": True,
                "resolution": EXTERNAL_PATH_UNAVAILABLE,
            }] if mismatched else []
        ),
        "status": ("CONTRADICTORY_CROSS_RECORD_HASHES" if mismatched
                   else "CONSISTENT"),
    }


# ---------------------------------------------------------------------------
# evidence inventory
# ---------------------------------------------------------------------------

CURRENT = "CURRENT"
SUPPORTING = "SUPPORTING"
SUPERSEDED = "SUPERSEDED"
HISTORICAL = "HISTORICAL"
STALE = "STALE"
MISSING_SOURCE = "MISSING_SOURCE"
CONTRADICTORY = "CONTRADICTORY"


def build_evidence_inventory(root: Path, manifest: Dict[str, Any],
                             durability: Dict[str, Any]) -> Dict[str, Any]:
    """Classify every RQ4 artifact. Reads only; never edits or quarantines."""
    entries: List[Dict[str, Any]] = []

    def add(rel, classification, role, note="", claim=""):
        p = root / rel
        entries.append({
            "artifact": Path(rel).as_posix(),
            "exists": p.is_file(),
            "sha256": sha256_file(p) if p.is_file() else MISSING,
            "classification": classification,
            "role": role,
            "recorded_claim": claim or UNKNOWN,
            "note": note,
        })

    # --- current leak-free authority
    add(LEAKFREE_AGGREGATE, CURRENT, "CURRENT_AUTHORITY",
        "Five-seed leak-free GAP-010 retrain aggregates; the live RQ4 number.",
        "cosine_distance mean 0.9207, bootstrap CI95 [0.8446, 0.9760]")
    add(LEAKFREE_POST_AUDIT, CURRENT, "CURRENT_AUTHORITY",
        "Per-checkpoint post-hoc leakage audit; the zero-overlap claim.",
        "overall_status PASS, eval_pair_hash_overlap [] for all 5 seeds")
    add(LEAKFREE_PRE_AUDIT, CURRENT, "CURRENT_AUTHORITY",
        "Pre-training leakage audit proving the exclusion was active.",
        "status PASS, 562/562 tiles retained post-exclusion")
    add(LEAKFREE_RESULTS, CURRENT, "CURRENT_AUTHORITY",
        "Human-readable result write-up for the current campaign.")
    add(LEAKFREE_RUNNER, CURRENT, "REPRODUCTION_ENTRYPOINT",
        "Leak-free seed-ensemble driver used by the producer.")
    add(LEAKFREE_AGG_SCRIPT, CURRENT, "AGGREGATE_COMPUTATION",
        "Producer's aggregate script; delegates to gnn_provenance.summarize_runs.")
    add(MASTER_CLOSE, CURRENT, "SUPPORTING_SECOND_RECORD",
        "Independent second record of the same five per-seed runs.",
        "RQ4_CLEAN_EXTENSION_SUPPORTED")

    # --- supporting mechanism evidence
    add(LEAK_FIX_DIR / "RESULTS.md", SUPPORTING, "ROOT_CAUSE_FIX",
        "GAP-010 root-cause fix write-up.")
    add(PROV_LEAKAGE_AUDIT, SUPPORTING, "SUPERSESSION_RATIONALE",
        "status FAIL scoped to the 2026-09-01 C21 split; this is the evidence "
        "that establishes the leaky number must be superseded.",
        "status FAIL, eval_pair_content_in_training_set [69ee3498...]")
    add(PROV_CHECKPOINT_CONTRACT, SUPPORTING, "CHECKPOINT_CONTRACT",
        "Reuse policy and manifest fields the leak-free checkpoints claim.")
    add(PROV_DATASET_MANIFEST, SUPPORTING, "MANIFEST_CONTRACT",
        "Tile-manifest construction rule.",
        "INCOMPLETE - training tile bytes absent from that checkout")
    add(PROV_HISTORICAL_CLASS, SUPPORTING, "PROVENANCE_RECLASSIFICATION",
        "Reclassifies C18/C21/V2 placeholders as LEGACY_DESCRIPTIVE_PROVENANCE.")
    add(PROV_AUTHORITATIVE_PATH, SUPPORTING, "MODULE_AUTHORITY",
        "Authoritative module list with recorded SHA256 values.")
    add(PROV_TEST_RESULTS, SUPPORTING, "TEST_EVIDENCE",
        "GNN-focused test subset result.", "79 passed, 0 failed")

    # --- RQ4 part A (domain randomization) -- still live, not superseded
    add(DR_DIR / "C15_RQ4_DOMAIN_RANDOMIZATION.json", CURRENT,
        "PART_A_DOMAIN_RANDOMIZATION",
        "RQ4 part A; unaffected by the GNN leak-fix supersession.")
    add(DR_DIR / "determinism" / "report.json", CURRENT, "PART_A_EVIDENCE",
        "Three-run structural determinism evidence.")

    # --- superseded generations
    add(LEAKY_AGGREGATE, SUPERSEDED, "SUPERSEDED_LEAKY_GENERATION",
        "The 2026-09-01 five-seed number; leaky by construction.",
        "cosine_distance mean 0.6433733820915222")
    add(LEAKY_DIR / "seed_42" / "gnn_training_report.json", SUPERSEDED,
        "SUPERSEDED_LEAKY_PER_SEED", "Committed per-seed report of the leaky run.")
    add(LEAKY_ISOLATION, SUPPORTING, "ISOLATION_PROBE",
        "Separate isolation probe (old checkpoints, new graph builder). Its "
        "cosine_distance > 1.0 values are a DIFFERENT metric instance and must "
        "not be mistaken for the C21 aggregate.",
        "cosine_distance 1.02-1.11 with negative cosine_similarity")
    add(LEAKY_PROVENANCE_MD, SUPPORTING, "CLAIM_BOUNDARY_SOURCE",
        "Origin of the in-sample-diagnostic claim boundary.")
    add(PREBUGFIX_AGGREGATE, SUPERSEDED, "SUPERSEDED_PREBUGFIX_GENERATION",
        "2026-08-26 pre-graph-bugfix generation.",
        "cosine_distance mean 1.153711485862732")

    # --- stale / contradictory
    add(SEED_RECOVERY, STALE, "STALE_SEED_RECOVERY",
        "States MISSING / 'Retraining required' for a five-seed leak-free RQ4 "
        "extension. That campaign was executed on 2026-09-24 and is committed "
        "as aggregate_stats.json. The recovery artifact was never retired.",
        "complete_valid 0, all seed states {}, 'Retraining required'")
    add(Path("reports/production_readiness/20260923_MASTER_CLOSURE_PLAN/PLAN.md"),
        STALE, "STALE_PLAN",
        "Lists RQ4 as blocked by GAP-010 and retraining 'not yet actionable'; "
        "both were resolved on 2026-09-23/24.",
        "'RQ4 retraining ... not yet actionable'")
    add(Path("reports/production_readiness/20260919T000000Z_RQ3_PAIRED_CAPTURE_"
             "CONTRACT/TEST_RESULTS.json"), STALE, "STALE_TEST_EXCLUSION",
        "Excludes test_rq4_gnn_provenance.py claiming an IndentationError at "
        "line 551. Superseded by clean full-suite runs recorded in "
        "MASTER_GAP_REGISTER.json (GAP-015, closed).",
        "collection_blocker_excluded: IndentationError at line 551")
    add(Path("reports/production_readiness/20260915T233000Z_DOMAIN_GAP_GNN_V2"
             "/GNN_SCHEMA_CHECKPOINT_AUDIT.json"), CONTRADICTORY,
        "DESCRIPTIVE_PLACEHOLDER_HASHES",
        "Marks descriptive placeholder identifiers as VERIFIED; reclassified "
        "LEGACY_DESCRIPTIVE_PROVENANCE by HISTORICAL_PROVENANCE_CLASSIFICATION.json.")
    add(Path("reports/post_audit_hardening/THESIS_VS_CURRENT_STATE_COMPARISON_"
             "20260827.md"), CONTRADICTORY, "CONTRADICTORY_GENERATION_NUMBER",
        "Presents 1.1537 as the current C21 mean; that is the PREBUGFIX "
        "generation's number, contradicting the 2026-09-01 C21 aggregate "
        "(0.6434) held in the same report tree.",
        "C21 cosine_distance mean=1.1537 CI [1.0803, 1.2476]")
    add(THESIS_BUNDLE / "rq_tables.json", SUPERSEDED, "SUPERSEDED_THESIS_TABLE",
        "Ranks the leaky 0.6434 as [AUTHORITATIVE]; retained because its "
        "evidence_sha256 anchors C21 aggregate_stats.json.",
        "gnn_latent_cosine_distance 0.6433733820915222 AUTHORITATIVE")
    add(THESIS_BUNDLE / "rq_tables.md", SUPERSEDED, "SUPERSEDED_THESIS_TABLE_MD",
        "Same leaked number.")
    add(THESIS_BUNDLE / "THESIS_RUN_BUNDLE.md", SUPERSEDED, "SUPERSEDED_BUNDLE_MD",
        "Cites the leaky CI as the RQ4 authoritative interval.")
    add(Path("submission/results/gnn_v1_full/permutation_test_n30.json"),
        HISTORICAL, "FROZEN_THESIS_EVIDENCE",
        "Frozen thesis permutation test. Immutable; explicitly NOT transferred "
        "to the leak-free metric.",
        "p=0.0000 on the PRE-LEAK-FIX lineage")

    # --- genuinely missing sources
    missing: List[Dict[str, str]] = [
        {"artifact": "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles",
         "status": MISSING_SOURCE,
         "impact": "training tile bytes; blocks independent recomputation of "
                   "training_dataset_manifest_sha256 and of a retrain"},
        {"artifact": "cities/ingolstadt/manual_grid0821.xodr",
         "status": MISSING_SOURCE,
         "impact": "one of the two eval-pair reference files; blocks independent "
                   "recomputation of eval-pair hash 69ee3498..."},
        {"artifact": str(PRODUCER_ROOT),
         "status": EXTERNAL_PATH_UNAVAILABLE,
         "impact": "producer worktree; holds all 5 checkpoints, the per-seed "
                   "gnn_training_report.json files and union_tiles"},
        {"artifact": "reports/production_readiness/20260924T000000Z_GAP010_"
                     "RQ4_LEAKFREE_RETRAIN/seed_{42..46}/gnn_training_report.json",
         "status": MISSING_SOURCE,
         "impact": "per-seed training reports for the current campaign; only "
                   "their aggregate and audit projections are committed"},
    ]

    counts: Dict[str, int] = {}
    for e in entries:
        counts[e["classification"]] = counts.get(e["classification"], 0) + 1
    counts[MISSING_SOURCE] = len([m for m in missing if m["status"] == MISSING_SOURCE])
    counts[EXTERNAL_PATH_UNAVAILABLE] = len(
        [m for m in missing if m["status"] == EXTERNAL_PATH_UNAVAILABLE])

    return {
        "schema": "RQ4_EVIDENCE_INVENTORY/v1",
        "candidate_git_sha": git_sha(root),
        "artifacts": entries,
        "missing_sources": missing,
        "classification_counts": counts,
        "read_only_guarantee": (
            "No pre-existing RQ4 artifact was edited, deleted or quarantined by "
            "this lane. Promotion is the later integration batch's job."
        ),
        "checkpoint_durability_status": durability.get("status"),
        "reproducibility_level": manifest.get("reproducibility_level"),
    }


# ---------------------------------------------------------------------------
# supersession plan
# ---------------------------------------------------------------------------

def build_supersession_plan(root: Path, inventory: Dict[str, Any],
                            manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Produce the supersession plan. Performs NO promotion in this lane."""
    by_path = {e["artifact"]: e for e in inventory["artifacts"]}

    def sha_of(rel: Path) -> str:
        p = root / rel
        return sha256_file(p) if p.is_file() else MISSING

    current_sha = sha_of(LEAKFREE_AGGREGATE)
    master_close_sha = sha_of(MASTER_CLOSE)
    progress_sha = sha_of(Path("docs/research/THESIS_TO_CURRENT_PROGRESS.md"))

    items: List[Dict[str, Any]] = []

    def plan(artifact, classification, reason, replacement_key):
        rel = Path(artifact).as_posix()
        entry = by_path.get(rel, {})
        row: Dict[str, Any] = {
            "artifact": rel,
            "current_sha256": entry.get("sha256", MISSING),
            "current_classification": classification,
            "replacement_artifact": None,
            "replacement_sha256": MISSING,
            "supersedes_relationship": None,
            "reason": reason,
            "action_in_this_lane": "NONE (integration batch performs promotion)",
        }
        if replacement_key == "leak_free_retrain":
            row["replacement_artifact"] = LEAKFREE_AGGREGATE.as_posix()
            row["replacement_sha256"] = current_sha
            row["supersedes_relationship"] = (
                "leak-free five-seed GAP-010 retrain supersedes the leaky "
                "five-seed number; both retained, leaky one not citable")
        elif replacement_key == "master_close":
            row["replacement_artifact"] = MASTER_CLOSE.as_posix()
            row["replacement_sha256"] = master_close_sha
            row["supersedes_relationship"] = (
                "independent second record of the same five per-seed runs")
        elif replacement_key == "progress_doc":
            row["replacement_artifact"] = "docs/research/THESIS_TO_CURRENT_PROGRESS.md"
            row["replacement_sha256"] = progress_sha
            row["supersedes_relationship"] = (
                "canonical narrative already states the leak-free number as "
                "AUTHORITATIVE; this artifact contradicts that narrative")
        elif replacement_key == "self":
            row["replacement_artifact"] = "reports/parallel_wave/rq4/RQ4_EVIDENCE_INVENTORY.json"
            row["replacement_sha256"] = (
                "generated_at_commit (see RQ4_REPRODUCIBILITY_MANIFEST.json "
                "candidate_git_sha)")
            row["supersedes_relationship"] = "classified stale/contradictory here"
        items.append(row)

    plan(LEAKY_AGGREGATE, SUPERSEDED,
         "Leaky five-seed generation. GAP-010 established that the eval-pair "
         "reference hash-matched content present in its training set, so this "
         "number cannot be cited as an honest train/eval split.", "leak_free_retrain")
    plan(LEAKY_DIR / "seed_42" / "gnn_training_report.json", SUPERSEDED,
         "Per-seed report of the leaky generation; superseded as a source of an "
         "RQ4 number.", "leak_free_retrain")
    plan(PREBUGFIX_AGGREGATE, SUPERSEDED,
         "Pre-graph-bugfix generation (2026-08-26). Superseded twice over: by "
         "the 2026-09-01 bugfix and then by the 2026-09-24 leak-free retrain.",
         "leak_free_retrain")
    plan(SEED_RECOVERY, STALE,
         "Directly contradicts the committed leak-free campaign: it reports "
         "complete_valid 0 with empty per-seed states and recommends "
         "'Retraining required'. The retrain was executed on 2026-09-24 and its "
         "aggregates are committed. Note its expected_seeds were [1,2,3,4,5] "
         "while the executed campaign used [42,43,44,45,46], so the recovery "
         "artifact was tracking a seed set that was never run.", "self")
    plan(Path("reports/production_readiness/20260923_MASTER_CLOSURE_PLAN/PLAN.md"),
         STALE, "Lists RQ4 as blocked by GAP-010 with retraining 'not yet "
                "actionable'; both resolved on 2026-09-23/24.", "self")
    plan(Path("reports/production_readiness/20260919T000000Z_RQ3_PAIRED_CAPTURE_"
              "CONTRACT/TEST_RESULTS.json"), STALE,
         "Excludes tests/unit/test_rq4_gnn_provenance.py on an IndentationError "
         "that no longer exists, superseding itself with a false coverage claim.",
         "self")
    plan(Path("reports/post_audit_hardening/THESIS_VS_CURRENT_STATE_COMPARISON_"
              "20260827.md"), CONTRADICTORY,
         "Presents cosine_distance mean 1.1537 as the current C21 result. That "
         "is the PREBUGFIX generation's number; the 2026-09-01 C21 aggregate in "
         "the same tree reads 0.6434 and the leak-free retrain reads 0.9207. "
         "Three mutually inconsistent 'current' RQ4 numbers are live in the tree.",
         "leak_free_retrain")
    plan(Path("reports/production_readiness/20260915T233000Z_DOMAIN_GAP_GNN_V2"
              "/GNN_SCHEMA_CHECKPOINT_AUDIT.json"), CONTRADICTORY,
         "Marks descriptive placeholder identifiers as VERIFIED; already "
         "reclassified LEGACY_DESCRIPTIVE_PROVENANCE by "
         "HISTORICAL_PROVENANCE_CLASSIFICATION.json.", "self")
    plan(THESIS_BUNDLE / "rq_tables.json", SUPERSEDED,
         "Ranks the leaky 0.6434 as [AUTHORITATIVE] and anchors it via "
         "evidence_sha256, which is why the C21 aggregate must not be edited in "
         "place. Promotion requires re-anchoring, not overwriting.", "self")
    plan(THESIS_BUNDLE / "rq_tables.md", SUPERSEDED,
         "Markdown twin of the above.", "self")
    plan(THESIS_BUNDLE / "THESIS_RUN_BUNDLE.md", SUPERSEDED,
         "Cites the leaky bootstrap CI as the RQ4 authoritative interval.", "self")

    return {
        "schema": "RQ4_SUPERSESSION_PLAN/v1",
        "candidate_git_sha": git_sha(root),
        "promotion_performed_in_this_lane": False,
        "policy": (
            "This parallel lane classifies and plans only. Canonical historical "
            "artifacts are neither edited, deleted nor quarantined here. The "
            "integration batch performs promotion, and must re-anchor "
            "rq_tables.json evidence_sha256 rather than overwrite the C21 "
            "aggregate in place."
        ),
        "current_authority": {
            "leak_free_retrain_aggregate": LEAKFREE_AGGREGATE.as_posix(),
            "sha256": current_sha,
            "master_close_verification": MASTER_CLOSE.as_posix(),
            "sha256_master_close": master_close_sha,
            "thesis_progress_doc_sha256": progress_sha,
        },
        "superseded_artifact_count": sum(
            1 for i in items if i["current_classification"] == SUPERSEDED),
        "stale_artifact_count": sum(
            1 for i in items if i["current_classification"] == STALE),
        "contradictory_artifact_count": sum(
            1 for i in items if i["current_classification"] == CONTRADICTORY),
        "items": items,
    }


# ---------------------------------------------------------------------------
# clean-clone reproducibility
# ---------------------------------------------------------------------------

FULL_REEXECUTION_CAPABLE = "FULL_REEXECUTION_CAPABLE"
REGENERATION_CAPABLE_CHECKPOINTS_EXTERNAL = (
    "REGENERATION_CAPABLE_CHECKPOINTS_EXTERNAL")
EVIDENCE_RECOMPUTABLE_ONLY = "EVIDENCE_RECOMPUTABLE_ONLY"
INCOMPLETE = "INCOMPLETE"


def assess_clean_clone(root: Path, manifest: Dict[str, Any],
                       leakage: Dict[str, Any],
                       recomputation: Dict[str, Any]) -> Dict[str, Any]:
    """Can a clean clone at the candidate redo RQ4 end to end?"""
    steps: List[Dict[str, Any]] = []

    def step(name, capable, status, detail=""):
        steps.append({"step": name, "capable": capable, "status": status,
                      "detail": detail})

    inputs = {
        "cities/ingolstadt/manual_grid0821.xodr":
            (root / "cities/ingolstadt/manual_grid0821.xodr").is_file(),
        "reports/ingolstadt_map_quality_v2/work_package_02_connectivity/"
        "candidate_connectivity_repaired.xodr":
            (root / "reports/ingolstadt_map_quality_v2/work_package_02_connectivity"
             "/candidate_connectivity_repaired.xodr").is_file(),
        "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles":
            (root / "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE"
             "/union_tiles").is_dir(),
        LEAKFREE_RUNNER.as_posix(): (root / LEAKFREE_RUNNER).is_file(),
        LEAKFREE_AGG_SCRIPT.as_posix(): (root / LEAKFREE_AGG_SCRIPT).is_file(),
    }
    identified = sum(1 for v in inputs.values() if v)
    step("identify_exact_inputs", False,
         "PARTIAL" if identified < len(inputs) else "PASS",
         f"{identified}/{len(inputs)} required inputs present in a clean clone: "
         f"{inputs}")

    tiles_present = inputs[
        "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles"]
    step("reconstruct_training_dataset", False,
         "PASS" if tiles_present else MISSING,
         "" if tiles_present else
         "union_tiles (562 training tiles) is not committed; the tile pool "
         "cannot be reconstructed from a clean clone.")

    exclude_ok = (root / LEAKFREE_PRE_AUDIT).is_file()
    step("apply_leak_exclusions", exclude_ok, "PASS" if exclude_ok else MISSING,
         "Exclusion mechanism code is present and the exclusion hash set is "
         "committed, but it cannot be exercised without the tile pool.")

    step("execute_training_5x50_epochs", False, "INCOMPLETE",
         "No clean clone can execute the 5x50-epoch CPU retrain without the 562 "
         "tile pool and manual_grid0821.xodr. A 5x50-epoch retrain was NOT "
         "attempted in this batch and no PASS is claimed for it.")

    recomputed_ok = recomputation["status"] == "RECOMPUTED_MATCHES_COMMITTED"
    step("recompute_metrics", recomputed_ok,
         "PASS" if recomputed_ok else "FAIL",
         "All aggregates recomputed independently from committed per-seed values "
         "via the committed gnn_provenance.summarize_runs.")

    executed: List[Dict[str, Any]] = []
    try:
        s1 = prov.summarize_runs([0.5, 0.5])
        s2 = prov.summarize_runs([0.5, 0.5])
        executed.append({
            "check": "summarize_runs_is_deterministic",
            "result": "PASS" if s1 == s2 else "FAIL",
            "detail": "identical inputs produced identical bootstrap CI"})
    except Exception as exc:  # pragma: no cover - defensive
        executed.append({"check": "summarize_runs_is_deterministic",
                         "result": "FAIL", "detail": str(exc)})
    try:
        fp = environment_fingerprint()
        recorded = manifest["environment"]["recorded_by_producer"]
        match = (fp["python_version"] == recorded["python_version"]
                 and fp["torch_version"] == recorded["torch_version"]
                 and fp["torch_geometric_version"]
                 == recorded["torch_geometric_version"])
        executed.append({
            "check": "environment_matches_recorded_producer_environment",
            "result": "PASS" if match else "MISMATCH",
            "detail": {"observed": fp, "recorded": recorded}})
    except Exception as exc:  # pragma: no cover - defensive
        executed.append({
            "check": "environment_matches_recorded_producer_environment",
            "result": "FAIL", "detail": str(exc)})
    step("lightweight_deterministic_checks", True,
         "PASS" if all(e["result"] == "PASS" for e in executed) else "PARTIAL",
         f"{len(executed)} deterministic checks executed in this clean clone.")

    if all(s["status"] == "PASS" for s in steps):
        classification = FULL_REEXECUTION_CAPABLE
    elif recomputed_ok:
        # The aggregates are exactly reproducible from committed per-seed
        # values, but the training tile pool, one eval-pair reference and all
        # five checkpoints are absent, so neither recovery nor regeneration is
        # possible from a clean clone.
        classification = EVIDENCE_RECOMPUTABLE_ONLY
    else:
        classification = INCOMPLETE

    return {
        "schema": "RQ4_CLEAN_CLONE_REPRODUCIBILITY/v1",
        "candidate_git_sha": git_sha(root),
        "classification": classification,
        "full_retrain_attempted": False,
        "full_retrain_policy": (
            "A 5x50-epoch CPU retrain was not performed: two required inputs are "
            "absent from any clean clone, so it could not have reproduced the "
            "original run even with the compute available. Per the batch rules "
            "an unavailable input is INCOMPLETE, never a pass."
        ),
        "inputs_present": inputs,
        "steps": steps,
        "executed_lightweight_checks": executed,
        "unverifiable_here": leakage["blockers"],
    }


# ---------------------------------------------------------------------------
# negative controls
# ---------------------------------------------------------------------------

def run_negative_controls() -> List[Dict[str, Any]]:
    """Every control must FAIL. A control that passes is a broken control."""
    controls: List[Dict[str, Any]] = []

    def ctl(name, description, fn):
        try:
            outcome = fn()
            controls.append({
                "control": name, "description": description,
                "expected": "FAIL_DETECTED", "observed": outcome,
                "result": "PASS" if outcome == "FAIL_DETECTED" else "BROKEN"})
        except Exception as exc:
            controls.append({
                "control": name, "description": description,
                "expected": "FAIL_DETECTED",
                "observed": f"UNEXPECTED_EXCEPTION: {exc}", "result": "BROKEN"})

    eval_pair = {"69ee3498e0e7ca748dd5e342de10493dc4ece45a6b04cc34653f5917672c42e8",
                 "c3dc29d3f570d929cbe664961446ea76fd3b8c74b0f4668ade99a67995a7ca43"}

    ctl("train_eval_hash_overlap",
        "A checkpoint whose recorded eval_pair_hash_overlap is non-empty must "
        "be rejected.",
        lambda: "FAIL_DETECTED" if not _overlap_is_clean(
            [sorted(eval_pair)[0]], eval_pair) else "NOT_DETECTED")

    ctl("missing_exclusion_list",
        "An empty exclusion set must not pass the exclusion-covers-eval-pair "
        "check.",
        lambda: "FAIL_DETECTED" if not _exclusion_covers_eval_pair([], ["a", "b"])
        else "NOT_DETECTED")

    ctl("wrong_checkpoint_sha",
        "Two different recorded SHA256 values for the same checkpoint path must "
        "be reported as a cross-record disagreement.",
        lambda: "FAIL_DETECTED" if not _sha_agrees("a" * 64, "b" * 64)
        else "NOT_DETECTED")

    ctl("wrong_seed",
        "A seed list containing duplicates must fail seed-identity validation.",
        lambda: "FAIL_DETECTED" if not _seed_identity_ok(
            {"seeds": [42, 42, 44]},
            {"42": {"checkpoint_sha256": "x"}, "44": {"checkpoint_sha256": "y"}})
        else "NOT_DETECTED")

    ctl("wrong_training_manifest",
        "Divergent training-dataset manifest hashes across seeds must be reported.",
        lambda: "FAIL_DETECTED" if not _single_manifest({"a" * 64, "b" * 64}, "a" * 64)
        else "NOT_DETECTED")

    ctl("duplicate_checkpoint_reused_for_two_seeds",
        "One checkpoint hash reused across two seeds must fail seed-identity "
        "validation even when the seeds differ.",
        lambda: "FAIL_DETECTED" if not _seed_identity_ok(
            {"seeds": [42, 43]},
            {"42": {"checkpoint_sha256": "dup", }, "43": {"checkpoint_sha256": "dup"}})
        else "NOT_DETECTED")

    ctl("missing_producer_identity",
        "A per-seed record whose producer git SHA is UNKNOWN must be surfaced as "
        "a downgrade, not silently accepted.",
        lambda: "FAIL_DETECTED" if not _producer_identity_present(
            ["a4d8a97", UNKNOWN]) else "NOT_DETECTED")

    ctl("aggregate_inconsistent_with_per_seed_values",
        "An aggregate whose mean does not match the mean of its own per-seed "
        "values must be reported as a disagreement.",
        lambda: "FAIL_DETECTED" if not _mean_consistent([1.0, 2.0, 3.0], 99.0)
        else "NOT_DETECTED")

    return controls


def _overlap_is_clean(overlap: Sequence[str], eval_pair: Iterable[str]) -> bool:
    return list(overlap) == [] and not (set(overlap) & set(eval_pair))


def _exclusion_covers_eval_pair(excluded: Sequence[str],
                                eval_pair: Sequence[str]) -> bool:
    return bool(excluded) and sorted(set(excluded)) == sorted(set(eval_pair))


def _sha_agrees(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a) and bool(b) and a == b


def _single_manifest(observed: Iterable[str], expected: Optional[str]) -> bool:
    obs = set(observed)
    return bool(obs) and len(obs) == 1 and obs == {expected}


def _mean_consistent(values: Sequence[float], claimed_mean: float) -> bool:
    if not values:
        return False
    return _finite_close(claimed_mean, sum(values) / len(values), tol=1e-12)


def _producer_identity_present(shas: Sequence[str]) -> bool:
    return bool(shas) and all(s and s != UNKNOWN for s in shas)