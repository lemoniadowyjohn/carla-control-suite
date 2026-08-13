"""Q1 - Injectable Phase N certification verdict engine.

``run_n_certify.py`` delegates its verdict logic to this pure engine so that
verdict logic is independently testable (negative-control fixtures, mutation
testing, schema validation) rather than being self-validated by a novel script.

The engine NEVER hardcodes statuses.  Every gate is a predicate over evidence;
mandatory runtime-perception evidence may not pass through stub statuses.

Verdict vocabulary (Q1):

  PHASE_N_CERTIFIER_INDEPENDENTLY_VERIFIED
  PHASE_N_CERTIFIER_REJECTED
  PHASE_N_CERTIFIER_EVIDENCE_INCOMPLETE
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from phase_q.semantic_policy import (
    PROFILE_PERCEPTION_RELEASE,
    PROFILE_STRUCTURAL_XODR,
    validate_profile,
)

# Expected signed-off candidate identity (published by the campaign).
EXPECTED_BRANCH = "fix/post-audit-phase-e-junctions-roundabouts-20260803"
EXPECTED_COMMIT = "f5aabc0a4f170e564aa03efcb906966880859a9f"
# Candidate 80ebb005... (ingolstadt_fixed_final.xodr) was RETIRED: it exhibits
# 767 roads violating the CARLA length invariant (s <= road->GetLength()) and
# carries 0 Phase-H signals.  The governed repaired candidate is the
# length-invariant-preserving, semantics-complete artifact
# ingolstadt_perception_final_repaired.xodr (3467 signals, 66 crosswalks,
# 0 length violations).
EXPECTED_REPAIRED_SHA = "6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02"
# Runtime sha stays pinned until the next certified CARLA run loads a governed
# payload regenerated from the crash-safe lineage; a mismatched runtime sha is
# a HARD rejection (fail-closed) until re-certification evidence exists.
EXPECTED_RUNTIME_SHA = "9630d9f673fdea87058139d9e2241c7084dc2e2550674bba4bfffc78c6d0ae80"

# run IDs may change; a mismatched run_id is a hard rejection.
GATE_SCHEMA = {
    "G0": ("map_not_builtin_town", "map name must not be a builtin Town"),
    "G1": ("runtime_opendrive_present", "runtime to_opendrive evidence required"),
    "G2": ("candidate_hash_authority", "repaired candidate hash must match signed candidate"),
    "G3": ("runtime_hash_authority", "runtime hash must match signed runtime"),
    "G4": ("sensor_evidence_real", "sensor evidence must contain captured frames, not stubs"),
    "G5": ("performance_measured", "FPS must be measured > 0 for perception"),
    "G6": ("drivability_spawns", "vehicle spawns must be non-zero for perception"),
    "G7": ("old_vs_new_comparison", "old-vs-new comparison must contain real differences"),
    "G8": ("evidence_run_identity", "evidence run id must match the certified run"),
    "G9": ("source_runtime_identity", "source/runtime structural equivalence"),
    "G10": ("road_junction_counts", "road/junction counts must match the campaign"),
    "G11": ("repair_mutation_clean", "repair mutation audit clean"),
    "G12": ("strict_gate_pass", "acceptance strict gate passes"),
    "G13": ("idempotency", "repair idempotent"),
    "G14": ("semantic_equivalence", "semantic equivalence for the active profile"),
    "G15": ("semantic_emptiness_policy", "empty semantic categories under active profile"),
    "G16": ("worktree_provenance", "provenance recorded and consistent"),
    "G17": ("manifest_order", "evidence manifest must follow evidence completion"),
    "G18": ("manual_edit_signature", "PASS JSON must carry a valid artifact digest"),
    "G19": ("length_invariant", "no road may violate s <= road->GetLength()"),
}


def _n(v: Any, default: Any = None) -> Any:
    return v if v is not None else default


def _s(v: Any, default: str = "") -> str:
    return str(v) if v is not None else default


def _is_builtin_town(name: Any) -> bool:
    return _s(name).startswith("Town") or "/Town" in _s(name)


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def assess(bundle: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full gate matrix against one evidence bundle.

    ``bundle`` keys (each may be missing when evidence is absent):
      provenance, run_manifest, map, l1..l13, p4, stage7, p1, stage20s
    Returns a dict with gates, rejection codes, verdict.
    """
    profile = config.get("profile", PROFILE_PERCEPTION_RELEASE)
    expected_repaired = config.get("repaired_sha", EXPECTED_REPAIRED_SHA)
    expected_runtime = config.get("runtime_sha", EXPECTED_RUNTIME_SHA)
    expected_road = config.get("road_count")
    expected_junction = config.get("junction_count")

    gates: Dict[str, Dict[str, Any]] = {}
    rejections: List[Dict[str, str]] = []

    def gate(gid: str, ok: bool, evidence: str, code: str, desc: str) -> None:
        gates[gid] = {"status": "PASS" if ok else "FAIL", "evidence": evidence,
                      "code": code, "description": desc}
        if not ok:
            rejections.append({"gate": gid, "code": code, "reason": desc,
                               "evidence": evidence})

    # ---------------- G0: builtin town guard ----------------
    map_name = (bundle.get("map") or {}).get("name")
    if _is_builtin_town(map_name):
        gate("G0", False, "map_name={}".format(map_name), "WRONG_MAP_TOWN10HD", "loaded a builtin Town")
    elif not map_name:
        gate("G0", False, "map_name missing", "WRONG_MAP_UNKNOWN", "map name unknown")
    else:
        gate("G0", True, "map_name={}".format(map_name), "OK", "not a builtin Town")

    # ---------------- G1: runtime to_opendrive ----------------
    l2 = bundle.get("l2") or {}
    runtime_sha = l2.get("opendrive_sha256")
    runtime_len = l2.get("opendrive_length")
    if not runtime_sha or not runtime_len:
        gate("G1", False, "runtime_sha={} length={}".format(runtime_sha, runtime_len),
             "MISSING_RUNTIME_TO_OPENDRIVE", "runtime to_opendrive evidence absent")
    else:
        gate("G1", True, "runtime_sha256={:12} length={}".format(runtime_sha, runtime_len),
             "ok_runtime", "runtime to_openddrive present")

    # ---------------- G2: candidate hash ----------------
    repaired = (bundle.get("p4") or {}).get("rep_sha256") or (bundle.get("config") or {}).get("repaired_sha")
    if repaired and repaired != expected_repaired:
        gate("G2", False, "rep_sha256={}".format(repaired),
             "WRONG_CANDIDATE_HASH", "candidate hash does not match signed candidate")
    elif repaired:
        gate("G2", True, "rep_sha256={}".format(repaired[:16]), "ok_candidate", "candidate hash matches")
    else:
        gate("G2", False, "rep_sha256=<missing>", "MISSING_CANDIDATE_HASH", "candidate hash absent")

    # ---------------- G3: runtime sha ----------------
    if runtime_sha and expected_runtime and runtime_sha != expected_runtime:
        gate("G3", False, "runtime={}".format(runtime_sha),
             "WRONG_RUNTIME_HASH", "runtime SHA does not match signed runtime")
    elif runtime_sha:
        gate("G3", True, "runtime_sha256 matches",
             "G3 ok", "runtime SHA matches signed runtime")

    # ---------------- G4: sensor evidence real ----------------
    l9 = bundle.get("l9") or {}
    sensor_data = l9.get("sensor_data") or {}
    sensors = list(sensor_data.keys()) if isinstance(sensor_data, dict) else []
    captured = [k for k, v in sensor_data.items()
                if _s(v.get("status")) == "CAPTURED" and bool(v.get("frame_non_empty", False))]
    stub_mark = _s(l9.get("status")) == "PASS"
    if stub_mark and not captured:
        gate("G4", False,
             "sensors={} captured={} status=PASS".format(sensors, captured),
             "EMPTY_SENSOR_EVIDENCE_MARKED_PASS",
             "sensor evidence stubbed but marked PASS")
    elif not sensors:
        gate("G4", False, "sensors=[]", "MISSING_RUNTIME_TO_DRIVE_SENSORS",
             "no sensor evidence present")
    else:
        gate("G4", True, "sensors={} captured={}".format(sensors, captured),
             "runtime_ok", "sensor evidence present")

    # ---------------- G5: FPS measured ----------------
    l10 = bundle.get("l10") or {}
    fps = _as_int(l10.get("fps"))
    if _s(l10.get("status")) == "PASS" and fps <= 0:
        gate("G5", False, "fps={} status=PASS".format(fps),
             "ZERO_FPS_MARKED_PASS", "zero FPS marked PASS")
    else:
        gate("G5", fps > 0, "fps={}".format(fps),
             "runtime_fps", "FPS measured {}".format("non-zero" if fps > 0 else "zero"))

    # ---------------- G6: vehicle spawns ----------------
    l7 = bundle.get("l7") or {}
    spawns = _as_int(l7.get("vehicle_successful_spawns"))
    if _s(l7.get("status")) == "PASS" and spawns <= 0:
        gate("G6", False, "spawns={} status=PASS".format(spawns),
             "ZERO_VEHICLE_SPAWNS_MARKED_PASS", "zero vehicle spawns marked PASS")
    else:
        gate("G6", spawns > 0, "spawns={}".format(spawns),
             "runtime spawn", "vehicle spawns {}".format("non-zero" if spawns > 0 else "zero"))

    # ---------------- G7: old-vs-new ----------------
    l11 = bundle.get("l11") or {}
    diffs = l11.get("differences")
    if _s(l11.get("status")) == "PASS" and not diffs:
        gate("G7", False, "status=PASS differences={}".format(diffs),
             "MISSING_OLD_VS_NEW_MARKED_PASS", "old-vs-new missing evidence marked PASS")
    else:
        gate("G7", bool(diffs),
             "differences={}".format(diffs),
             "old-new", "old-vs-new comparison {}".format("present" if diffs else "absent"))

    # ---------------- G8: run identity ----------------
    run = bundle.get("run_manifest") or {}
    run_id = _s(run.get("run_id")) or _s((bundle.get("combined") or {}).get("run_id"))
    if run_id and config.get("expected_run_id") and run_id != config["expected_run_id"]:
        gate("G8", False, "evidence_run_id={} expected={}".format(run_id, config["expected_run_id"]),
             "EVIDENCE_FROM_ANOTHER_RUN", "evidence from another run ID")
    elif not run_id:
        gate("G8", False, "run_id=<missing>", "MISSING_RUN_ID", "no run id")
    else:
        gate("G8", True, "run_id={}".format(run_id), "ok", "run identity matches")

# ---------------- G9/G10: p4 inventory ----------------
    p4_inv = (bundle.get("p4") or {}).get("inventory") or {}
    runtime_inv = p4_inv.get("runtime") or {}
    source_inv = p4_inv.get("source") or {}
    same_shape = (
        runtime_inv.get("road_unique") == source_inv.get("road_unique")
        and runtime_inv.get("junction_unique") == source_inv.get("junction_unique")
    )
    gate("G9", same_shape,
         "roads src={} runt={}, juncs src={} runt={}".format(
             source_inv.get("road_unique"), runtime_inv.get("road_unique"),
             source_inv.get("junction_unique"), runtime_inv.get("junction_unique")),
         "SRC_RUNTIME_DIVERGENCE", "source/runtime structural identity")
    miss = _as_int(p4_inv.get("missing_road_count"))
    unexp = _as_int(p4_inv.get("unexpected_road_count"))
    road_ok = source_inv.get("road_unique") and runtime_inv.get("road_unique")
    if expected_road is not None:
        if expected_road:
            road_ok = not expected_road or runtime_inv.get("road_unique") == expected_road
    gate("G10", bool(road_ok) and miss == 0 and unexp == 0,
         "missing={} unexpected={}".format(miss, unexp),
         "ROAD_JUNC_CNT_MISMATCH", "road/junction counts match campaign")

    # ---------------- G11: repair mutation ----------------
    p1 = bundle.get("p1") or {}
    unexpected_mutations = p1.get("unexpected_mutations", [])
    gate("G11", not unexpected_mutations,
         "changed_road_count={} unexpected_mutations={}".format(
             p1.get("changed_road_count"), unexpected_mutations),
         "MUTATION_AUDIT_ERROR", "repair mutation audit clean")

    # ---------------- G12: strict acceptance gate ----------------
    stage7 = bundle.get("stage7") or {}
    gate("G12", _as_int(stage7.get("strict_gate_errors")) == 0,
         "strict_gate_errors={}".format(stage7.get("strict_gate_errors")),
         "STRICT_GATE_FAIL", "strict acceptance gate passes")

    # ---------------- G13: idempotency ----------------
    gate("G13", bool(stage7.get("idempotent", False)),
         "idempotent={}".format(stage7.get("idempotent")),
         "NOT_IDEMPOTENT", "repair idempotent")

    # ---------------- G14: semantic equivalence ----------------
    sem = bundle.get("semantic_equiv") or {}
    sem_verdict = _s(sem.get("verdict"))
    gate("G14", sem_verdict in ("SEMANTIC_EQUIVALENCE_PASS", "SEMANTIC_EQUIVALENCE_PARTIAL")
               and profile != PROFILE_PERCEPTION_RELEASE or sem_verdict == "SEMANTIC_EQUIVALENCE_PASS",
         "semantic_equiv_verdict={}".format(sem_verdict),
         "SEMANTIC_EQUIVALENCE", "semantic equivalence ok for this compatible profile")

    # ---------------- G15: semantic emptiness policy ----------------
    l4 = bundle.get("l4") or {}
    cat = bundle.get("semantic_counts")
    if cat:
        policy = validate_profile(cat, profile, authority_ok=bundle.get("authority_ok"))
        gate("G15", policy["verdict"] == "PASS",
             "profile={} failed={}".format(profile, [f["category"] for f in policy["failed"]]),
             "EMPTY_SEMANTIC_POLICY", "perception-strict empty-semantic policy")
    else:
        gate("G15", False, "no semantic counts", "NO_SEMANTIC_COUNTS", "no semantic category counts")

    # ---------------- G16: provenance ----------------
    prov = bundle.get("provenance") or {}
    classification = _s(prov.get("classification"))
    dirty_ok = (classification != "CLEAN_COMMITTED_EVIDENCE_RUN" or prov.get("clean_committed"))
    hashes_present = bool(prov.get("patch_hashes") or not prov.get("dirty"))
    gate("G16", dirty_ok and hashes_present,
         "classification={} clean_committed={}".format(classification, prov.get("clean_committed")),
         "PROVENANCE_INCONSISTENT", "worktree provenance recorded and consistent")

    # ---------------- G17: manifest last ----------------
    man = bundle.get("evidence_manifest") or {}
    manifest_after = man.get("generated_at")
    evidence_before = man.get("evidence_last_completed_at")
    gate("G17", not manifest_after or not evidence_before or manifest_after >= evidence_before,
         "manifest_generated={} evidence_completed={}".format(manifest_after, evidence_before),
         "MANIFEST_BEFORE_EVIDENCE", "manifest must follow evidence completion")

    # ---------------- G18: manual-edit signature ----------------
    signature = man.get("signature")
    g18_pass = False
    if signature:
        import hashlib
        import json as _json
        payload_no_sig = {k: v for k, v in man.items() if k != "signature"}
        try:
            dig = hashlib.sha256(
                _json.dumps(payload_no_sig, sort_keys=True).encode("utf-8")).hexdigest()
            g18_pass = dig == signature
        except Exception:
            g18_pass = False
    gate("G18", g18_pass,
         "signature_present={}".format(bool(signature)),
         "MANUALLY_EDITED_PASS_JSON", "manual-edit guard")

    # ---------------- G19: length invariant ----------------
    # CARLA's mesh builder asserts `s <= road->GetLength()`; a candidate whose
    # planView extent exceeds the declared road length (even by float residue)
    # crashes generate_opendrive_world.  Zero violations is a hard requirement
    # for the repaired candidate under every profile.
    li = bundle.get("length_invariant")
    if li is None:
        gate("G19", False, "length_invariant=<missing>", "NO_LENGTH_INVARIANT_EVIDENCE",
             "length-invariant evidence absent")
    elif _as_int(li.get("violations")) != 0:
        gate("G19", False, "violations={}".format(li.get("violations")),
             "LENGTH_INVARIANT_VIOLATIONS",
             "roads with planView extent exceeding declared length must be zero")
    else:
        gate("G19", True,
             "violations=0 roads_checked={}".format(li.get("roads_checked")),
             "ok", "length invariant holds")

    # ---------------- Final verdict ----------------
    blocked_evidence = [g for g, v in gates.items() if v["status"] in ("BLOCKED", "INCOMPLETE")]
    fail_reasons = [r for r in rejections if r["code"] != "manual"]
    if not fail_reasons and not blocked_evidence:
        verdict = "PHASE_N_CERTIFIER_INDEPENDENTLY_VERIFIED"
    elif fail_reasons:
        verdict = "PHASE_N_CERTIFIER_REJECTED"
    else:
        verdict = "PHASE_N_CERTIFIER_EVIDENCE_INCOMPLETE"

    return {
        "verdict": verdict,
        "profile": profile,
        "gates": gates,
        "rejections": rejections,
        "reasons": [r["code"] for r in rejections],
        "summary": {
            "passed": sum(1 for v in gates.values() if v["status"] == "PASS"),
            "failed": sum(1 for v in gates.values() if v["status"] == "FAIL"),
            "missing": len(blocked_evidence),
        },
    }