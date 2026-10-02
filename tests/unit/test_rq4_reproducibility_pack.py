"""RQ4 reproducibility / provenance / supersession pack tests.

These are offline tests. They never require live CARLA and never require the
absent union_tiles pool or the producer worktree.

The negative-control tests are deliberately paired with
``run_negative_controls()``: each asserts that a mutated record is REJECTED, so
a future weakening of the pack fails the suite rather than silently passing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.domain_gap_gnn import reproducibility_pack as rrp

OUT = Path("reports/parallel_wave/rq4")

EMITTED = (
    "RQ4_EVIDENCE_INVENTORY.json",
    "RQ4_LEAKAGE_REVERIFICATION.json",
    "RQ4_AGGREGATE_RECOMPUTATION.json",
    "RQ4_REPRODUCIBILITY_MANIFEST.json",
    "RQ4_CHECKPOINT_DURABILITY.json",
    "RQ4_SUPERSESSION_PLAN.json",
    "RQ4_CLEAN_CLONE_REPRODUCIBILITY.json",
    "RQ4_NEGATIVE_CONTROLS.json",
    "FINAL_VERDICT.json",
)


@pytest.fixture(scope="module")
def pack():
    return {
        "manifest": rrp.build_reproducibility_manifest(WORKTREE),
        "leakage": rrp.reverify_leakage(WORKTREE),
        "recomputation": rrp.recompute_aggregates(WORKTREE),
        "durability": rrp.classify_checkpoints(WORKTREE),
    }


# ---------------------------------------------------------------------------
# aggregate recomputation must match the committed leak-free authority
# ---------------------------------------------------------------------------

def test_primary_aggregates_recompute_bit_identically(pack):
    rec = pack["recomputation"]
    assert rec["status"] == "RECOMPUTED_MATCHES_COMMITTED"
    # `disagreements` also lists the superseded generations' bootstrap drift;
    # the current authority is judged by `primary_recomputation`.
    assert rec["primary_recomputation"]["status"] == "RECOMPUTED_MATCHES_COMMITTED"
    assert rec["primary_recomputation"]["disagreements"] == []
    for metric in ("cosine_distance", "cosine_similarity"):
        cmp = rec["recomputed"][metric]["comparison"]
        assert cmp["bootstrap_ci_bit_identical"] is True
        assert cmp["values_bit_identical"] is True
        assert cmp["mean_absolute_difference"] == 0.0
        assert cmp["std_absolute_difference"] == 0.0


def test_recomputed_mean_matches_the_reported_leak_free_result(pack):
    """The pack must read the committed value, not a literal constant."""
    recomputed = pack["recomputation"]["recomputed"]["cosine_distance"]["recomputed"]
    assert recomputed["mean"] == pytest.approx(0.9206715822219849, abs=0.0)
    assert recomputed["bootstrap_ci95_low"] == pytest.approx(
        0.8446466565132141, abs=0.0)
    assert recomputed["bootstrap_ci95_high"] == pytest.approx(
        0.9759842038154602, abs=0.0)
    module_src = (WORKTREE / "ultimate_pipeline/domain_gap_gnn"
                  "/reproducibility_pack.py").read_text(encoding="utf-8")
    assert "0.9206715822219849" not in module_src


def test_cosine_distance_and_similarity_are_complements(pack):
    comp = pack["recomputation"]["cosine_distance_similarity_complementarity"]
    assert comp["within_float32_rounding"] is True
    assert comp["max_abs_error_from_one"] < 1e-6


def test_superseded_generation_drift_is_reported_not_hidden(pack):
    """The old C21 CI drift must be surfaced, never tuned away."""
    sup = pack["recomputation"]["superseded_generation_recomputation"]
    assert sup["status"] == "BOOTSTRAP_PROTOCOL_DRIFT"
    assert sup["disagreements"], "the drift must actually be listed"
    for d in sup["disagreements"]:
        # means reproduce exactly; only the bootstrap endpoints moved
        assert d["mean_bit_identical"] is True
        assert d["kind"] == "BOOTSTRAP_PROTOCOL_DRIFT_ONLY"


# ---------------------------------------------------------------------------
# leakage re-verification
# ---------------------------------------------------------------------------

def test_zero_train_eval_overlap_every_seed(pack):
    leak = pack["leakage"]
    assert leak["content_overlap_train_vs_eval_zero_for_every_seed"] is True
    assert leak["n_seeds_verified"] == 5
    for row in leak["per_seed"]:
        assert row["recorded_eval_pair_hash_overlap"] == []
        assert row["intersection_with_eval_pair_hashes"] == []
        assert row["tile_count_matches_aggregate"] is True


def test_leakage_reverification_does_not_trust_recorded_pass_strings(pack):
    """Unverifiable checks must never be downgraded to PASS."""
    results = {c["check"]: c["result"] for c in pack["leakage"]["checks"]}
    assert (results["training_tile_manifest_sha_recomputed_from_tile_bytes"]
            == rrp.MISSING)
    assert (results["per_seed_checkpoint_provenance_verified_against_bytes"]
            == rrp.EXTERNAL_PATH_UNAVAILABLE)
    assert pack["leakage"]["overall_status"] != "PASS"
    assert pack["leakage"]["blockers"]


def test_present_eval_pair_hash_is_independently_verified(pack):
    rows = [c for c in pack["leakage"]["checks"]
            if c["check"] == "eval_pair_byte_hashes_recomputed_in_this_checkout"
            ][0]["detail"]
    matched = [r for r in rows if r["result"] == "MATCH"]
    assert matched, "at least one eval-pair hash must be verifiable in-checkout"
    for r in matched:
        assert r["observed_sha256"] == r["expected_sha256"]
    for r in rows:
        if r["result"] == "MISSING":
            assert r["observed_sha256"] == rrp.MISSING


def test_historical_leak_rationale_is_scoped_not_reapplied(pack):
    hist = pack["leakage"]["historical_leaky_lineage"]
    assert hist["recorded_status"] == "FAIL"
    assert hist["recomputable_here"] is False
    assert "NOT a statement about the 2026-09-24" in hist["interpretation"]


def test_exclusion_set_covers_the_eval_pair(pack):
    results = {c["check"]: c["result"] for c in pack["leakage"]["checks"]}
    assert results["exclusion_set_equals_eval_pair_hashes"] == "PASS"
    assert results["single_consistent_training_manifest_across_seeds"] == "PASS"
    assert results["pre_training_audit_zero_and_tile_count_intact"] == "PASS"
    assert results["seed_identity_distinctness"] == "PASS"


# ---------------------------------------------------------------------------
# checkpoint durability + the cross-record contradiction
# ---------------------------------------------------------------------------

def test_every_checkpoint_is_classified(pack):
    dur = pack["durability"]
    assert sorted(r["seed"] for r in dur["per_seed"]) == [42, 43, 44, 45, 46]
    allowed = {rrp.AVAILABLE_AND_HASH_VERIFIED, rrp.AVAILABLE_HASH_MISMATCH,
               rrp.EXTERNAL_ONLY, rrp.MISSING_CLASS}
    for r in dur["per_seed"]:
        assert r["classification"] in allowed
    assert sum(dur["counts"].values()) == 5


def test_checkpoint_sha256_cross_record_contradiction_is_surfaced(pack):
    """Two committed artifacts record different SHA256 for the same paths.

    This is the batch's headline contradiction and must stay visible.
    """
    dur = pack["durability"]
    assert dur["status"] == "CONTRADICTORY_CROSS_RECORD_HASHES"
    anom = dur["integrity_anomalies"][0]
    assert sorted(anom["seeds"]) == [42, 43, 44, 45, 46]
    assert anom["md5_cross_record_agreement"] is True
    assert anom["resolution"] == rrp.EXTERNAL_PATH_UNAVAILABLE
    for r in dur["per_seed"]:
        assert r["sha256_cross_record_agreement"] is False
        assert r["sha256_post_hoc_audit"] != r["sha256_master_close"]


def test_durability_states_recovery_and_regeneration(pack):
    rec = pack["durability"]["recovery_or_regeneration"]
    assert rec["recovery"]["available_in_this_environment"] is False
    assert rec["regeneration"]["blocked_in_this_clean_clone"] is True
    assert "union_tiles" in " ".join(rec["regeneration"]["inputs_required"])


# ---------------------------------------------------------------------------
# reproducibility manifest bindings
# ---------------------------------------------------------------------------

def test_manifest_binds_every_required_field_or_marks_it(pack):
    m = pack["manifest"]
    assert m["candidate_git_sha"] != rrp.UNKNOWN
    assert m["historical_producer_git_sha"]["retrain_base_commit"] != rrp.UNKNOWN
    assert len(m["input_identity"]["evaluation_pair_hashes"]) == 2
    assert m["input_identity"]["excluded_source_hashes"]
    assert m["training_tile_manifest"]["tile_count"] == 562
    assert m["seeds"] == [42, 43, 44, 45, 46]
    tp = m["training_parameters"]
    assert (tp["epochs"], tp["batch_size"], tp["learning_rate"],
            tp["device"]) == (50, 16, 1e-4, "cpu")
    assert m["bootstrap_procedure"]["n_boot"] == 2000
    assert m["bootstrap_procedure"]["rng"].startswith("python stdlib random")
    assert m["aggregate_procedure"]["implementation"].endswith("summarize_runs")
    assert m["aggregate_procedure"]["std"] == "sample std, ddof=1"
    assert len(m["per_seed_metrics"]) == 5


def test_manifest_never_invents_missing_values(pack):
    m = pack["manifest"]
    by_seed = {r["seed"]: r for r in m["per_seed_metrics"]}
    # seed 43's manifest recorded UNKNOWN producer identity; that gap must be
    # preserved rather than back-filled with the retrain base commit.
    assert by_seed[43]["producer_git_sha"] == rrp.UNKNOWN
    assert "producer_git_sha_note" in by_seed[43]
    assert by_seed[42]["producer_git_sha"] != rrp.UNKNOWN
    assert "producer_git_sha_note" not in by_seed[42]
    assert m["reproducibility_level"] == "EVIDENCE_RECOMPUTABLE_ONLY"
    assert any("per_seed_producer_identity_missing" in d
               for d in m["reproducibility_downgrades"])
    assert any("checkpoint_sha256_cross_record_disagreement" in d
               for d in m["reproducibility_downgrades"])


def test_environment_matches_recorded_producer(pack):
    env = pack["manifest"]["environment"]
    rec, obs = env["recorded_by_producer"], env["observed_in_this_clean_clone"]
    assert obs["python_version"] == rec["python_version"]
    assert obs["torch_version"] == rec["torch_version"]
    assert obs["torch_geometric_version"] == rec["torch_geometric_version"]


def test_recompute_code_paths_all_present(pack):
    for entry in pack["manifest"]["code_paths_for_recomputation"]:
        assert entry["present"] is True, entry["path"]
        assert len(entry["sha256"]) == 64


# ---------------------------------------------------------------------------
# claim boundary
# ---------------------------------------------------------------------------

def test_claim_boundary_is_not_an_rq5_transfer_claim(pack):
    cb = pack["manifest"]["claim_boundary"]
    assert cb["rq4_latent_separation_is_not"] == "HELD_OUT_PERCEPTION_ACCURACY"
    assert "RQ5" in cb["forbidden_promotion"]
    pt = cb["permutation_pvalue_transfer"]
    assert pt["transfer_to_leak_free_metric"] is False
    assert pt["thesis_lineage"] == "PRE_LEAK_FIX"
    assert "n=5" in pt["n_seed_caveat"]


# ---------------------------------------------------------------------------
# inventory and supersession
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def inventory(pack):
    return rrp.build_evidence_inventory(WORKTREE, pack["manifest"],
                                        pack["durability"])


def test_inventory_classifies_stale_and_contradictory_artifacts(inventory):
    by = {e["artifact"]: e for e in inventory["artifacts"]}
    assert by["RQ4_SEED_RECOVERY.json"]["classification"] == rrp.STALE
    assert by[rrp.LEAKY_AGGREGATE.as_posix()]["classification"] == rrp.SUPERSEDED
    assert by[rrp.PREBUGFIX_AGGREGATE.as_posix()]["classification"] == rrp.SUPERSEDED
    contra = [e for e in inventory["artifacts"]
              if e["classification"] == rrp.CONTRADICTORY]
    assert contra, "the placeholder-hash / 1.1537 artifacts must be flagged"
    for e in inventory["artifacts"]:
        if e["exists"]:
            assert len(e["sha256"]) == 64


def test_inventory_records_missing_sources(inventory):
    missing = {m["artifact"]: m for m in inventory["missing_sources"]}
    assert missing["cities/ingolstadt/manual_grid0821.xodr"]["status"] == rrp.MISSING_SOURCE
    assert str(rrp.PRODUCER_ROOT) in missing
    assert missing[str(rrp.PRODUCER_ROOT)]["status"] == rrp.EXTERNAL_PATH_UNAVAILABLE
    assert inventory["read_only_guarantee"].startswith("No pre-existing RQ4 artifact")


def test_supersession_plan_flags_the_stale_seed_recovery(pack, inventory):
    plan = rrp.build_supersession_plan(WORKTREE, inventory, pack["manifest"])
    assert plan["promotion_performed_in_this_lane"] is False
    by = {i["artifact"]: i for i in plan["items"]}
    stale = by["RQ4_SEED_RECOVERY.json"]
    assert stale["current_classification"] == rrp.STALE
    assert stale["current_sha256"] != rrp.MISSING
    assert stale["action_in_this_lane"].startswith("NONE")
    assert plan["superseded_artifact_count"] >= 5
    assert plan["stale_artifact_count"] >= 2
    assert plan["contradictory_artifact_count"] >= 2


def test_supersession_plan_never_deletes_canonical_artifacts(pack, inventory):
    plan = rrp.build_supersession_plan(WORKTREE, inventory, pack["manifest"])
    for item in plan["items"]:
        action = item["action_in_this_lane"].upper()
        assert "DELETE" not in action
        assert "QUARANTINE" not in action
        assert "EDIT" not in action
    assert (plan["current_authority"]["sha256"]
            == rrp.sha256_file(WORKTREE / rrp.LEAKFREE_AGGREGATE))


# ---------------------------------------------------------------------------
# clean-clone classification
# ---------------------------------------------------------------------------

def test_clean_clone_classification_is_honest(pack):
    cc = rrp.assess_clean_clone(WORKTREE, pack["manifest"], pack["leakage"],
                                pack["recomputation"])
    assert cc["full_retrain_attempted"] is False
    assert cc["classification"] == rrp.EVIDENCE_RECOMPUTABLE_ONLY
    assert cc["classification"] != rrp.FULL_REEXECUTION_CAPABLE
    assert cc["inputs_present"][
        "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles"
    ] is False
    assert cc["unverifiable_here"]
    training = [s for s in cc["steps"] if s["step"] == "execute_training_5x50_epochs"][0]
    assert training["capable"] is False
    assert training["status"] == "INCOMPLETE"


def test_executed_lightweight_checks_pass(pack):
    cc = rrp.assess_clean_clone(WORKTREE, pack["manifest"], pack["leakage"],
                                pack["recomputation"])
    names = {c["check"] for c in cc["executed_lightweight_checks"]}
    assert names == {"summarize_runs_is_deterministic",
                     "environment_matches_recorded_producer_environment"}
    for c in cc["executed_lightweight_checks"]:
        assert c["result"] == "PASS"


# ---------------------------------------------------------------------------
# negative controls -- each must REJECT a mutated record
# ---------------------------------------------------------------------------

def test_all_negative_controls_detect_failure():
    controls = rrp.run_negative_controls()
    assert len(controls) >= 8
    for c in controls:
        assert c["result"] == "PASS", c
        assert c["observed"] == "FAIL_DETECTED", c


def test_negative_control_corpus_covers_required_scenarios():
    names = {c["control"] for c in rrp.run_negative_controls()}
    required = {
        "train_eval_hash_overlap",
        "missing_exclusion_list",
        "wrong_checkpoint_sha",
        "wrong_seed",
        "wrong_training_manifest",
        "duplicate_checkpoint_reused_for_two_seeds",
        "missing_producer_identity",
        "aggregate_inconsistent_with_per_seed_values",
    }
    assert required <= names


def test_primitives_reject_each_tampering():
    assert rrp._mean_consistent([1.0, 2.0, 3.0], 2.0) is True
    assert rrp._mean_consistent([1.0, 2.0, 3.0], 0.9206715822219849) is False
    assert rrp._exclusion_covers_eval_pair(["a"], ["a", "b"]) is False
    assert rrp._exclusion_covers_eval_pair([], ["a"]) is False
    assert rrp._exclusion_covers_eval_pair(["a", "b"], ["b", "a"]) is True
    assert rrp._sha_agrees("a" * 64, "a" * 64) is True
    assert rrp._sha_agrees("a" * 64, "b" * 64) is False
    assert rrp._sha_agrees(None, "b" * 64) is False
    assert rrp._producer_identity_present(["x"]) is True
    assert rrp._producer_identity_present(["x", rrp.UNKNOWN]) is False
    assert rrp._producer_identity_present([]) is False
    assert rrp._single_manifest({"a" * 64}, "a" * 64) is True
    assert rrp._single_manifest({"a" * 64, "b" * 64}, "a" * 64) is False
    assert rrp._single_manifest(set(), "a" * 64) is False


def test_mutated_live_campaign_is_rejected_not_absorbed(pack):
    """A tampered overlap list must be rejected by the same primitive."""
    post = json.loads(
        (WORKTREE / rrp.LEAKFREE_POST_AUDIT).read_text(encoding="utf-8"))
    eval_pair = post["eval_pair_sha256"].values()
    per_seed = post["per_seed_checkpoint_source_hash_check"]

    # genuine campaign still verifies
    assert rrp._seed_identity_ok(
        json.loads((WORKTREE / rrp.LEAKFREE_AGGREGATE).read_text(encoding="utf-8")),
        per_seed) is True
    assert rrp._overlap_is_clean(per_seed["42"]["eval_pair_hash_overlap"],
                                 eval_pair) is True

    # tampered overlap is rejected
    tampered = dict(per_seed)
    tampered["42"] = dict(per_seed["42"])
    tampered["42"]["eval_pair_hash_overlap"] = [sorted(post["eval_pair_sha256"])[0]]
    assert rrp._overlap_is_clean(tampered["42"]["eval_pair_hash_overlap"],
                                 eval_pair) is False


def test_recomputation_never_tuned_to_historical_output(pack):
    assert pack["recomputation"]["tuned_toward_historical_output"] is False
    assert pack["manifest"]["reproducibility_level"] in (
        "FULL_REEXECUTION_CAPABLE",
        "REGENERATION_CAPABLE_CHECKPOINTS_EXTERNAL",
        "EVIDENCE_RECOMPUTABLE_ONLY", "INCOMPLETE")


# ---------------------------------------------------------------------------
# emitted artifacts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", EMITTED)
def test_emitted_artifact_is_self_describing(name):
    p = WORKTREE / OUT / name
    assert p.is_file(), f"missing emitted artifact: {name}"
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert "schema" in doc


def test_final_verdict_token_is_from_the_allowed_set():
    doc = json.loads((WORKTREE / OUT / "FINAL_VERDICT.json").read_text(
        encoding="utf-8"))
    assert doc["final_verdict"] in {
        "RQ4_REPRODUCIBILITY_PASS",
        "RQ4_RESULT_VALID_REPRODUCIBILITY_PARTIAL",
        "RQ4_EVIDENCE_CONTRADICTION_FOUND",
        "RQ4_LEAKAGE_REVERIFICATION_FAIL",
        "PARTIAL_WITH_EXACT_BLOCKERS",
    }
    assert doc["claim_boundary_preserved"] is True
    assert doc["full_retrain_attempted"] is False
    assert doc["base_sha"] == "7fbd33ffc952aaafaca199f8e4939b1757cb94d6"
    assert doc["seeds_verified"] == 5
    assert doc["leakage_content_overlap_zero"] is True
    assert doc["verdict_reasons"]


def test_final_verdict_matches_the_underlying_evidence():
    """The verdict must be derivable, not asserted."""
    doc = json.loads((WORKTREE / OUT / "FINAL_VERDICT.json").read_text(
        encoding="utf-8"))
    durability = json.loads(
        (WORKTREE / OUT / "RQ4_CHECKPOINT_DURABILITY.json").read_text(
            encoding="utf-8"))
    recomputation = json.loads(
        (WORKTREE / OUT / "RQ4_AGGREGATE_RECOMPUTATION.json").read_text(
            encoding="utf-8"))
    leakage = json.loads(
        (WORKTREE / OUT / "RQ4_LEAKAGE_REVERIFICATION.json").read_text(
            encoding="utf-8"))

    assert doc["checkpoint_durability"] == durability["status"]
    assert doc["aggregate_recomputation"] == recomputation["status"]
    assert doc["leakage_status"] == leakage["overall_status"]

    if durability["integrity_anomalies"]:
        assert doc["final_verdict"] == "RQ4_EVIDENCE_CONTRADICTION_FOUND"
    elif leakage["overall_status"] == "FAIL":
        assert doc["final_verdict"] == "RQ4_LEAKAGE_REVERIFICATION_FAIL"
    elif recomputation["status"] != "RECOMPUTED_MATCHES_COMMITTED":
        assert doc["final_verdict"] == "RQ4_EVIDENCE_CONTRADICTION_FOUND"
    else:
        assert doc["final_verdict"] in ("RQ4_REPRODUCIBILITY_PASS",
                                        "RQ4_RESULT_VALID_REPRODUCIBILITY_PARTIAL")


def test_emitted_manifest_binds_its_own_recorded_hashes():
    """Every emitted artifact hash in FINAL_VERDICT must match the file."""
    final = json.loads((WORKTREE / OUT / "FINAL_VERDICT.json").read_text(
        encoding="utf-8"))
    for name, sha in final["emitted_artifacts_sha256"].items():
        assert rrp.sha256_file(WORKTREE / OUT / name) == sha, name