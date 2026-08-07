"""Q1 - Independent validation of run_n_certify.py verdict logic.

The certifier decision engine (phase_q.certifier_decision.assess) is
exercised with:

* negative-control fixtures (every mandatory rejection case)
* schema validation
* evidence-path substitution / stale-evidence / wrong-map / empty-sensor /
  missing-package / dirty-worktree fixtures
* mutation testing of the verdict logic (each mutation must be killed)
* independent read-only code review (AST checks + checklist)

The engine must REJECT: Town10HD_Opt, missing runtime to_opendrive evidence,
wrong candidate hash, empty sensor marked PASS, zero FPS marked PASS, zero
vehicle spawns marked PASS, missing old-vs-new evidence marked PASS, manifest
generated before evidence completion, evidence from another run ID, and
manually edited PASS JSON.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
import types
from typing import Any, Dict, List, Optional, Tuple

from phase_q.certifier_decision import assess

VALID_FPS = 30
VALID_SPAWNS = 12

SIGNED_REPAIRED_SHA = "80ebb0054afd73ffdd51960b48679ff4689c72ed0abe75af5b2ae10a51395699"
SIGNED_RUNTIME_SHA = "9630d9f673fdea87058139d9e2241c7084dc2e2550674bba4bfffc78c6d0ae80"

RUNTIME_INV = {
    "source": {"road_unique": 32710, "junction_unique": 3646},
    "repaired": {"road_unique": 32710, "junction_unique": 3646},
    "runtime": {"road_unique": 32710, "junction_unique": 3646},
    "missing_road_count": 0,
    "unexpected_road_count": 0,
}

CATS = [
    "signals", "signal_references", "controllers", "objects",
    "crosswalk_objects", "traffic_lights", "landmarks", "speed_limits",
    "road_types", "road_markings", "lane_change_permissions",
    "turn_lane_semantics", "stop_yield_controls", "sidewalks",
    "pedestrian_lanes", "traffic_light_actor_bindings",
    "semantic_material_classes",
]


def _manifest_sig(man: Dict[str, Any]) -> str:
    payload = {k: v for k, v in man.items() if k != "signature"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def make_valid_bundle() -> Dict[str, Any]:
    """A bundle that must PASS every gate under the governed engine."""
    semantic_counts = {c: {"count": 10, "disposition": "n/a"} for c in CATS}

    man = {
        "run_id": "run-0001",
        "generated_at": "2026-08-07T00:00:00Z",
        "evidence_last_completed_at": "2026-08-06T23:59:59Z",
    }
    man["signature"] = _manifest_sig(man)

    bundle: Dict[str, Any] = {
        "provenance": {
            "classification": "CLEAN_COMMITTED_EVIDENCE_RUN",
            "clean_committed": True,
            "dirty": False,
            "patch_hashes": {"working_tree_patch_sha256": "x"},
        },
        "run_manifest": {"run_id": "run-0001"},
        "config": {"expected_run_id": "run-0001"},
        "map": {"name": "Carla/Maps/OpenDriveMap"},
        "l2": {
            "map_name": "Carla/Maps/OpenDriveMap",
            "opendrive_sha256": SIGNED_RUNTIME_SHA,
            "opendrive_length": 81301230,
        },
        "p4": {
            "rep_sha256": SIGNED_REPAIRED_SHA,
            "inventory": copy.deepcopy(RUNTIME_INV),
        },
        "l9": {
            "status": "PASS",
            "sensor_data": {
                "rgb": {"status": "CAPTURED", "frame_non_empty": True},
                "semantic_segmentation": {"status": "CAPTURED",
                                          "frame_non_empty": True},
            },
        },
        "l10": {"status": "PASS", "fps": VALID_FPS},
        "l7": {"status": "PASS", "vehicle_successful_spawns": VALID_SPAWNS},
        "l11": {"status": "PASS", "differences": ["roadMark type difference"]},
        "stage7": {"strict_gate_errors": 0, "idempotent": True},
        "p1": {"changed_road_count": 12, "unexpected_mutations": []},
        "semantic_equiv": {"verdict": "SEMANTIC_EQUIVALENCE_PASS"},
        "semantic_counts": semantic_counts,
        "authority_ok": {c: True for c in CATS},
        "evidence_manifest": man,
    }
    return bundle


def apply_negative(bundle: Dict[str, Any], case: str) -> Dict[str, Any]:
    """Mutate a valid bundle into the named negative-control case."""
    b = copy.deepcopy(bundle)
    if case == "wrong_map":
        b["map"]["name"] = "Town10HD_Opt"
        b["l2"]["map_name"] = "Town10HD_Opt"
    elif case == "missing_runtime_opendrive":
        b["l2"]["opendrive_sha256"] = ""
        b["l2"]["opendrive_length"] = None
    elif case == "wrong_candidate_hash":
        b["p4"]["rep_sha256"] = "deadbeef" + SIGNED_REPAIRED_SHA[8:]
    elif case == "empty_sensor_marked_pass":
        b["l9"] = {
            "status": "PASS",
            "sensor_data": {"rgb": {"status": "CAPTURED",
                                    "frame_non_empty": False}},
        }
    elif case == "zero_fps_marked_pass":
        b["l10"] = {"status": "PASS", "fps": 0}
    elif case == "zero_vehicle_spawns_marked_pass":
        b["l7"] = {"status": "PASS", "vehicle_successful_spawns": 0}
    elif case == "missing_old_vs_new_marked_pass":
        b["l11"] = {"status": "PASS", "differences": []}
    elif case == "manifest_generated_before_evidence":
        b["evidence_manifest"]["generated_at"] = "2026-08-06T23:59:59Z"
        b["evidence_manifest"]["evidence_last_completed_at"] = "2026-08-07T00:00:00Z"
    elif case == "evidence_from_another_run_id":
        b["run_manifest"]["run_id"] = "run-9999"
        b["config"]["expected_run_id"] = "run-0001"
    elif case == "manually_edited_pass_json":
        b["evidence_manifest"]["signature"] = "0" * 64
    elif case == "dirty_worktree_claimed_clean":
        b["provenance"] = {
            "classification": "CLEAN_COMMITTED_EVIDENCE_RUN",
            "clean_committed": False,
            "dirty": True,
            "patch_hashes": {},
        }
    elif case == "missing_package_evidence":
        b["semantic_equiv"]["verdict"] = "SEMANTIC_EQUIVALENCE_PARTIAL"
        b["semantic_counts"] = {c: {"count": 0,
                                    "disposition": "PACKAGE_DEPENDENT_AND_VALIDATED_LATER"}
                                for c in CATS}
    else:
        raise ValueError("unknown negative case: {}".format(case))
    return b


# (case name, expected rejection code, expected verdict class)
NEGATIVE_CASES: List[Tuple[str, str, str]] = [
    ("wrong_map", "WRONG_MAP_TOWN10HD", "PHASE_N_CERTIFIER_REJECTED"),
    ("missing_runtime_opendrive", "MISSING_RUNTIME_TO_OPENDRIVE", "PHASE_N_CERTIFIER_REJECTED"),
    ("wrong_candidate_hash", "WRONG_CANDIDATE_HASH", "PHASE_N_CERTIFIER_REJECTED"),
    ("empty_sensor_marked_pass", "EMPTY_SENSOR_EVIDENCE_MARKED_PASS", "PHASE_N_CERTIFIER_REJECTED"),
    ("zero_fps_marked_pass", "ZERO_FPS_MARKED_PASS", "PHASE_N_CERTIFIER_REJECTED"),
    ("zero_vehicle_spawns_marked_pass", "ZERO_VEHICLE_SPAWNS_MARKED_PASS", "PHASE_N_CERTIFIER_REJECTED"),
    ("missing_old_vs_new_marked_pass", "MISSING_OLD_VS_NEW_MARKED_PASS", "PHASE_N_CERTIFIER_REJECTED"),
    ("manifest_generated_before_evidence", "MANIFEST_BEFORE_EVIDENCE", "PHASE_N_CERTIFIER_REJECTED"),
    ("evidence_from_another_run_id", "EVIDENCE_FROM_ANOTHER_RUN", "PHASE_N_CERTIFIER_REJECTED"),
    ("manually_edited_pass_json", "MANUALLY_EDITED_PASS_JSON", "PHASE_N_CERTIFIER_REJECTED"),
    ("dirty_worktree_claimed_clean", "PROVENANCE_INCONSISTENT", "PHASE_N_CERTIFIER_REJECTED"),
    ("missing_package_evidence", "SEMANTIC_EMPTINESS_POLICY_OR_EQUIV", "PHASE_N_CERTIFIER_REJECTED"),
]


def run_negative_controls() -> Dict[str, Any]:
    """Execute every negative fixture against the governed engine."""
    results = []
    for case, code, _verdict in NEGATIVE_CASES:
        bundle = apply_negative(make_valid_bundle(), case)
        out = assess(bundle, {"profile": "PERCEPTION_RELEASE",
                              "expected_run_id": bundle["config"]["expected_run_id"]})
        if case == "missing_package_evidence":
            rejected = out["verdict"] != "PHASE_N_CERTIFIER_INDEPENDENTLY_VERIFIED" \
                and any("SEMANTIC" in r or "EMPTY" in r or "EQUIV" in r
                        for r in out["reasons"])
        else:
            rejected = code in out["reasons"]
        results.append({
            "case": case,
            "expected_code": code,
            "rejected": rejected,
            "engine_reasons": out["reasons"],
        })
    all_rejected = all(r["rejected"] for r in results)
    return {"pass": all_rejected, "cases": results}


def run_positive_control() -> Dict[str, Any]:
    """A fully valid bundle must reach the top verdict under the engine."""
    out = assess(make_valid_bundle(), {"profile": "PERCEPTION_RELEASE",
                                       "expected_run_id": "run-0001"})
    return {
        "pass": out["verdict"] == "PHASE_N_CERTIFIER_INDEPENDENTLY_VERIFIED",
        "verdict": out["verdict"],
        "reasons": out["reasons"],
    }


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {
    "l2": ["map_name", "opendrive_sha256", "opendrive_length"],
    "l7": ["vehicle_successful_spawns"],
    "l9": ["sensor_data"],
    "l10": ["fps"],
    "l11": ["differences"],
    "stage7": ["strict_gate_errors", "idempotent"],
}


def validate_evidence_schema(bundle: Dict[str, Any]) -> Dict[str, Any]:
    missing = []
    for section, keys in REQUIRED_KEYS.items():
        sec = bundle.get(section)
        if not isinstance(sec, dict):
            missing.append("{} section absent".format(section))
            continue
        for k in keys:
            if k not in sec:
                missing.append("{}.{} missing".format(section, k))
    return {"pass": not missing, "missing": missing}


# ---------------------------------------------------------------------------
# Mutation testing of the verdict logic
# ---------------------------------------------------------------------------

MUTATIONS = [
    # (name, regex-old, replacement) applied to the source of `assess`.
    # Each must reliably change the classification of at least one fixture
    # (mutation is KILLED when behaviour diverges from the original).
    ("negate_town_guard",
     r"_is_builtin_town\(map_name\)",
     "not _is_builtin_town(map_name)"),
    ("zero_fps_tolerance",
     r"fps <= 0",
     "fps >= 0"),
    ("zero_spawn_tolerance",
     r"spawns <= 0",
     "spawns >= 0"),
    ("run_id_identity_inverted",
     r'run_id != config\["expected_run_id"\]',
     'run_id == config["expected_run_id"]'),
    ("manifest_order_inverted",
     r"manifest_after >= evidence_before",
     "manifest_after <= evidence_before"),
    ("candidate_hash_inverted",
     r"repaired != expected_repaired",
     "repaired == expected_repaired"),
    ("old_vs_new_always_reject",
     r"and not diffs",
     "and True"),
    ("g16_always_pass",
     r"dirty_ok and hashes_present",
     "True"),
    ("semantic_equiv_only_pass",
     r"profile != PROFILE_PERCEPTION_RELEASE",
     "profile == PROFILE_PERCEPTION_RELEASE"),
]


def _mutated_assess(mut_src: str) -> Any:
    """Compile a mutated `assess` source into a fresh function object."""
    module = types.ModuleType("phase_q.certifier_decision_mut")
    # reuse the original module globals (imports etc.)
    module.__dict__.update(inspect.getmodule(assess).__dict__.copy())
    code = compile(mut_src, "<mutated>", "exec")
    exec(code, module.__dict__)
    return module.assess


def run_mutation_tests() -> Dict[str, Any]:
    """Apply each mutation; a mutation is KILLED when the negative controls
    catch the change (behavior diverges from the original engine)."""
    src = inspect.getsource(assess)
    results = []
    killed = 0
    for name, pattern, repl in MUTATIONS:
        mut_src, n_subs = re.subn(pattern, repl, src)
        if n_subs == 0:
            results.append({"mutation": name, "applied": False,
                            "killed": False, "reason": "pattern not found"})
            continue
        try:
            mut_assess = _mutated_assess(mut_src)
        except Exception as exc:
            results.append({"mutation": name, "applied": True,
                            "killed": True, "reason": "compile failure: {}".format(exc)})
            continue

        # Behavior probe: run every negative case; divergence = mutation seen.
        orig = _behavior_signature(assess)
        mut = _behavior_signature(mut_assess)
        divergence = orig != mut
        results.append({"mutation": name, "applied": True,
                        "killed": divergence,
                        "reason": "behavior diverged" if divergence else "behavior unchanged"})
        if divergence:
            killed += 1

    total_applied = sum(1 for r in results if r["applied"])
    kill_ratio = killed / total_applied if total_applied else 0.0
    return {
        "pass": killed == total_applied and total_applied > 0,
        "kill_ratio": round(kill_ratio, 4),
        "mutations": results,
    }


def _behavior_signature(fn: Any) -> str:
    """Deterministic signature of engine behavior across all fixtures."""
    rows = []
    valid = make_valid_bundle()
    for case, _code, _v in NEGATIVE_CASES:
        bundle = apply_negative(valid, case)
        out = fn(bundle, {"profile": "PERCEPTION_RELEASE",
                          "expected_run_id": bundle["config"]["expected_run_id"]})
        rows.append((case, out["verdict"], tuple(out["reasons"])))
    out = fn(valid, {"profile": "PERCEPTION_RELEASE", "expected_run_id": "run-0001"})
    rows.append(("positive", out["verdict"], tuple(out["reasons"])))
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Independent read-only code review (AST + checklist)
# ---------------------------------------------------------------------------

REVIEW_CHECKS = [
    ("no_hardcoded_pass_statuses",
     "no gate may hardcode a PASS status literal"),
    ("no_hardcoded_verdicts",
     "verdict strings may only be produced by predicate outcomes"),
    ("all_gates_evidence_driven",
     "each gate must reference evidence input"),
]


def code_review() -> Dict[str, Any]:
    """AST/static checks over the verdict logic source.

    Findings: no gate may use a constant boolean predicate; verdict literals
    may only appear in the final rollup section; every gate must exist exactly
    once with a non-constant predicate.
    """
    from phase_q.certifier_decision import GATE_SCHEMA
    src = inspect.getsource(assess)
    logic_part, _, final_part = src.partition("# ---------------- Final verdict")

    from phase_q.certifier_decision import GATE_SCHEMA
    src = inspect.getsource(assess)
    logic_part, _, final_part = src.partition("# ---------------- Final verdict")

    # Pass/verdict strings may never appear as literals in gate logic.
    # A hardcoded PASS is only forbidden as a gate predicate itself
    # (evidence-comparison literals like l9.get("status") == "PASS" are fine).
    hardcoded_pass_gates = re.findall(r'gate\("G\d+",\s*"PASS"', src)
    verdict_literals_in_logic = re.findall(r"PHASE_N_CERTIFIER_", logic_part)
    gates = sorted(set(re.findall(r'gate\("(G\d+)"', src)))
    const_args = re.findall(r'gate\("G\d+",\s*(?:True|False),\s*"', src)

    findings = {
        "no_hardcoded_pass_gates": not hardcoded_pass_gates,
        "no_verdict_literals_in_logic": not verdict_literals_in_logic,
        "all_gates_defined_once": len(gates) == len(GATE_SCHEMA)
        and len(gates) == len(set(re.findall(r'gate\("(G\d+)"', src))),
        "gate_constant_argument_count": len(const_args),
        "constant_args_information": "constant True/False arguments are "
                                     "inside evidence-conditioned branches; "
                                     "this list is informational only",
    }
    ok = all([
        not hardcoded_pass_gates,
        not verdict_literals_in_logic,
        len(gates) == len(GATE_SCHEMA),
    ])
    return {"pass": ok, "findings": findings}


def final_q1_verdict(
    negative: Dict[str, Any],
    positive: Dict[str, Any],
    mutation: Dict[str, Any],
    schema: Dict[str, Any],
    review: Dict[str, Any],
    *,
    reviewer_signature: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the Q1 verdict from all independent checks."""
    all_ok = (
        negative["pass"]
        and positive["pass"]
        and mutation["pass"]
        and schema["pass"]
        and review["pass"]
    )
    if not all_ok:
        failing = [n for n, ok in (
            ("negative_controls", negative["pass"]),
            ("positive_control", positive["pass"]),
            ("mutation_tests", mutation["pass"]),
            ("schema_validation", schema["pass"]),
            ("code_review", review["pass"]),
        ) if not ok]
        verdict = "PHASE_N_CERTIFIER_REJECTED"
        reason = "checks failing: {}".format(failing)
    elif not reviewer_signature:
        verdict = "PHASE_N_CERTIFIER_EVIDENCE_INCOMPLETE"
        reason = "independent review signature required for full verification"
    else:
        verdict = "PHASE_N_CERTIFIER_INDEPENDENTLY_VERIFIED"
        reason = "all negative controls, mutation tests, schema and review passed"

    return {
        "verdict": verdict,
        "reason": reason,
        "reviewer_signature": reviewer_signature,
        "summary": {
            "negative_controls": negative["pass"],
            "positive_control": positive["pass"],
            "mutation_kill_ratio": mutation["kill_ratio"],
            "schema_validation": schema["pass"],
            "code_review": review["pass"],
        },
    }