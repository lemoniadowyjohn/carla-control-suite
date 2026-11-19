"""Round-2 review (reproduced against a91ab428): ``validate_release_acceptance_
contract`` was looser than the real producer (``build_map_acceptance``).

Each case below was live-reproduced on a91ab428 (the reviewer's scratch
scripts, since deleted) and is recreated here as a permanent regression test:

(a) the gate-set check was superset-only (``set(RELEASE) - set(mandatory_
    gates)``), so an extra or duplicated gate still passed, while the
    producer (map_acceptance.py build_map_acceptance, ~684-690) requires the
    exact authoritative set with no duplicates.
(b) ``artifact_identity_verified`` was never read at all.
(c) ``mandatory_gate_status`` (every entry must be PASS) and
    ``hard_fail_reasons``/``failed_gates`` (both must be empty) were never
    cross-checked -- a payload with every gate FAIL plus non-empty
    hard_fail_reasons still passed as long as the three self-reported summary
    booleans were forged to True.
(d) with no ``expected_xodr_sha256`` passed (exactly how
    ``_require_valid_map_acceptance`` and ``signals.index.
    release_acceptance_status`` call it), two equal NON-hex digests such as
    ``"x"``/``"x"`` still passed.
(e) the ``run_id`` check was skipped entirely when the payload had no
    ``run_id`` at all (not merely "when present, must match an expected
    value" -- release payloads without any run_id passed).

Each negative test below must FAIL on a91ab428 and PASS on HEAD. A positive
control (a genuine ``build_map_acceptance`` release payload) and the F1
production-shaped-receipt regression (manifest outside run_dir still
resolves/publishes) are included so the stricter validator is proven not to
have become *too* strict.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ultimate_pipeline.quality.final_artifact_gates import RELEASE_MANDATORY_GATES
from ultimate_pipeline.quality.map_acceptance import (
    build_map_acceptance,
    validate_release_acceptance_contract,
)


def _write(tmp_path: Path, name: str = "final.xodr") -> Path:
    p = tmp_path / name
    p.write_text(
        '<?xml version="1.0" encoding="utf-8"?><OpenDRIVE>'
        '<header revMajor="1" revMinor="4" name="t"/>'
        '<road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><center><lane id="0" type="none"/></center>'
        '<right><lane id="-1" type="driving"><width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane></right>'
        "</laneSection></lanes></road></OpenDRIVE>",
        encoding="utf-8",
    )
    return p


def _genuine_full_payload(sha: str, run_id: str = "v125") -> dict:
    """A payload that satisfies every single check (the control shape)."""
    return {
        "valid_for_experiments": True,
        "release_eligible": True,
        "artifact_identity_verified": True,
        "acceptance_policy": {"purpose": "release"},
        "mandatory_gates": list(RELEASE_MANDATORY_GATES),
        "mandatory_gate_status": {gate: "PASS" for gate in RELEASE_MANDATORY_GATES},
        "hard_fail_reasons": [],
        "failed_gates": [],
        "final_xodr_sha256": sha,
        "evaluated_xodr_sha256": sha,
        "run_id": run_id,
    }


# ---------------------------------------------------------------------------
# Positive controls
# ---------------------------------------------------------------------------


def test_genuine_build_map_acceptance_release_payload_passes(tmp_path):
    """A real (not hand-crafted) build_map_acceptance release-purpose PASS
    must satisfy validate_release_acceptance_contract with zero problems."""
    final = _write(tmp_path)
    sha = hashlib.sha256(final.read_bytes()).hexdigest()
    reports = {gate: {"ok": True} for gate in RELEASE_MANDATORY_GATES}
    acceptance = build_map_acceptance(
        reports,
        run_id="v125-positive-control",
        final_xodr_path=str(final),
        mandatory_gates=RELEASE_MANDATORY_GATES,
        purpose="release",
        evaluated_xodr_sha256=sha,
    )
    assert acceptance["release_eligible"] is True
    assert validate_release_acceptance_contract(acceptance) == []


def test_f1_production_shaped_receipt_still_resolves_and_publishes(tmp_path):
    """F1 regression (manifest outside run_dir) must still give PUBLISHED and
    a resolvable receipt under the stricter validator -- not just "rejects
    forged payloads", the genuine production shape must keep working."""
    from ultimate_pipeline.contracts.artifact_authority import (
        ArtifactAuthorityLedger,
        resolve_final_artifact_receipt,
        sha256_file,
        write_receipt,
    )
    from ultimate_pipeline.contracts.stage_capabilities import (
        GEOMETRY_FROZEN,
        HYGIENE_COMPLETE,
        LANES_FINAL,
        STRUCTURE_FROZEN,
    )
    from ultimate_pipeline.contracts.stage_contracts import QualityStatus

    campaign_root = tmp_path / "campaigns" / "some_campaign"
    campaign_root.mkdir(parents=True)
    run_dir = tmp_path / "ultimate_pipeline_out" / "run_f1"
    run_dir.mkdir(parents=True)

    final = _write(run_dir)
    ledger = ArtifactAuthorityLedger()
    ledger.provide(GEOMETRY_FROZEN, "geometry")
    ledger.provide(LANES_FINAL, "map_hygiene")
    ledger.provide(HYGIENE_COMPLETE, "map_hygiene")
    ledger.freeze_structure(str(final), stage="final_artifact_authority")
    ledger.record_evidence(
        "map_acceptance", str(final), stage="final_artifact_authority",
        depends_on=(STRUCTURE_FROZEN,),
    )

    sha = sha256_file(str(final))
    acceptance_payload = _genuine_full_payload(sha, run_dir.name)
    acceptance_path = run_dir / "map_acceptance.json"
    acceptance_path.write_text(json.dumps(acceptance_payload), encoding="utf-8")

    # THE external-input shape: INPUTS_MANIFEST.json is a SIBLING of the run
    # directory under campaigns/, never nested inside it.
    source_manifest = campaign_root / "INPUTS_MANIFEST.json"
    source_manifest.write_text('{"inputs": {}}', encoding="utf-8")
    source_manifest_identity = {
        "inputs_manifest_path": str(source_manifest),
        "inputs_manifest_sha256": sha256_file(str(source_manifest)),
    }

    receipt = ledger.build_receipt(
        final_artifact_path=str(final),
        map_acceptance=acceptance_payload,
        topology_certification={"SPEC_TOPOLOGY": QualityStatus.PASS.value},
        source_manifest_identity=source_manifest_identity,
        receipt_root=str(run_dir),
        run_id=run_dir.name,
        acceptance_receipt_path=str(acceptance_path),
    )
    assert receipt["publication_status"] == "PUBLISHED", receipt["publication_reasons"]

    write_receipt(str(run_dir), receipt)
    resolved = resolve_final_artifact_receipt(str(run_dir))
    assert resolved == final


# ---------------------------------------------------------------------------
# (a) exact gate set: extra gate / duplicated gate
# ---------------------------------------------------------------------------


def test_extra_gate_is_rejected_not_accepted_as_a_superset():
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    payload["mandatory_gates"] = list(RELEASE_MANDATORY_GATES) + ["unrelated_extra_gate"]
    payload["mandatory_gate_status"]["unrelated_extra_gate"] = "PASS"
    problems = validate_release_acceptance_contract(payload)
    assert problems, "an extra gate must not be accepted as a mere superset"
    assert any("mandatory_gates" in p for p in problems)


def test_duplicated_gate_is_rejected():
    """Reproduces the reviewer's exact "duplicated gates gave [] PASS" case:
    the full authoritative set is still COVERED (so a superset-only check
    like the old ``set(RELEASE) - set(mandatory_gates)`` sees nothing
    missing and passes), but one gate is listed twice -- which the real
    producer (build_map_acceptance's exact length+set check) rejects."""
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    gates = list(RELEASE_MANDATORY_GATES) + [RELEASE_MANDATORY_GATES[0]]
    payload["mandatory_gates"] = gates
    problems = validate_release_acceptance_contract(payload)
    assert problems, "a duplicated gate must not silently pass as a covered superset"
    assert any("mandatory_gates" in p for p in problems)


# ---------------------------------------------------------------------------
# (b) artifact_identity_verified must be read
# ---------------------------------------------------------------------------


def test_artifact_identity_verified_false_is_rejected():
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    payload["artifact_identity_verified"] = False
    problems = validate_release_acceptance_contract(payload)
    assert any("artifact_identity_verified" in p for p in problems)


def test_artifact_identity_verified_missing_is_rejected():
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    del payload["artifact_identity_verified"]
    problems = validate_release_acceptance_contract(payload)
    assert any("artifact_identity_verified" in p for p in problems)


# ---------------------------------------------------------------------------
# (c) mandatory_gate_status / hard_fail_reasons / failed_gates must be
# cross-checked, not merely summarized by the self-reported booleans
# ---------------------------------------------------------------------------


def test_every_gate_fail_with_forged_summary_booleans_is_rejected():
    """Reproduces the exact a91ab428 escape: artifact_identity_verified=False
    (also wrong on its own, per (b)) plus every mandatory gate FAIL plus a
    non-empty hard_fail_reasons/failed_gates -- but valid_for_experiments,
    release_eligible and acceptance_policy.purpose are all forged to the
    passing shape."""
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    payload["artifact_identity_verified"] = False
    payload["mandatory_gate_status"] = {gate: "FAIL" for gate in RELEASE_MANDATORY_GATES}
    payload["hard_fail_reasons"] = [{"gate": g, "reason": "FAIL"} for g in RELEASE_MANDATORY_GATES]
    payload["failed_gates"] = list(RELEASE_MANDATORY_GATES)
    problems = validate_release_acceptance_contract(payload)
    assert problems
    joined = " ".join(problems)
    assert "mandatory_gate_status" in joined
    assert "hard_fail_reasons" in joined
    assert "failed_gates" in joined


def test_nonempty_hard_fail_reasons_alone_is_rejected():
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    payload["hard_fail_reasons"] = [{"gate": "artifact_structure", "reason": "FAIL"}]
    problems = validate_release_acceptance_contract(payload)
    assert any("hard_fail_reasons" in p for p in problems)


def test_nonempty_failed_gates_alone_is_rejected():
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    payload["failed_gates"] = ["artifact_structure"]
    problems = validate_release_acceptance_contract(payload)
    assert any("failed_gates" in p for p in problems)


def test_single_gate_not_pass_is_rejected():
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    payload["mandatory_gate_status"]["physics_feasibility"] = "NOT_RUN"
    problems = validate_release_acceptance_contract(payload)
    assert any("physics_feasibility" in p for p in problems)


# ---------------------------------------------------------------------------
# (d) sha256 fields must be genuine 64-char lowercase hex digests, not
# merely equal to each other
# ---------------------------------------------------------------------------


def test_equal_non_hex_digests_are_rejected_with_no_expected_sha():
    """Exactly how _require_valid_map_acceptance and signals.index call this
    (no expected_xodr_sha256 passed): two equal non-hex strings must not
    pass."""
    payload = _genuine_full_payload("a" * 64)
    payload["final_xodr_sha256"] = "x"
    payload["evaluated_xodr_sha256"] = "x"
    problems = validate_release_acceptance_contract(payload)
    assert problems
    joined = " ".join(problems)
    assert "final_xodr_sha256" in joined or "evaluated_xodr_sha256" in joined


def test_equal_uppercase_hex_digests_are_rejected():
    sha_upper = ("A" * 64)
    payload = _genuine_full_payload(sha_upper)
    problems = validate_release_acceptance_contract(payload)
    assert problems


def test_short_equal_digests_are_rejected():
    payload = _genuine_full_payload("a" * 64)
    payload["final_xodr_sha256"] = "abc"
    payload["evaluated_xodr_sha256"] = "abc"
    problems = validate_release_acceptance_contract(payload)
    assert problems


# ---------------------------------------------------------------------------
# (e) run_id is REQUIRED, not merely checked when present
# ---------------------------------------------------------------------------


def test_missing_run_id_is_rejected():
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    del payload["run_id"]
    problems = validate_release_acceptance_contract(payload)
    assert any("run_id" in p for p in problems)


def test_none_run_id_is_rejected():
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    payload["run_id"] = None
    problems = validate_release_acceptance_contract(payload)
    assert any("run_id" in p for p in problems)


def test_empty_string_run_id_is_rejected():
    sha = "a" * 64
    payload = _genuine_full_payload(sha)
    payload["run_id"] = ""
    problems = validate_release_acceptance_contract(payload)
    assert any("run_id" in p for p in problems)


# --- review P3 follow-ups (1e902cfd re-review) -------------------------------


def test_digest_with_trailing_newline_is_rejected():
    """``$`` matches before a trailing newline; the digest check must use
    a full match so ``"<64 hex>\n"`` is not accepted as a digest."""
    payload = _genuine_full_payload("a" * 64)
    payload["final_xodr_sha256"] = "a" * 64 + "\n"
    payload["evaluated_xodr_sha256"] = "a" * 64 + "\n"
    problems = validate_release_acceptance_contract(payload)
    assert problems
    joined = " ".join(problems)
    assert "final_xodr_sha256" in joined or "evaluated_xodr_sha256" in joined


@pytest.mark.parametrize("key", ["hard_fail_reasons", "failed_gates"])
@pytest.mark.parametrize("bad", ["__missing__", {}, 0, "", None])
def test_fail_lists_must_be_present_empty_lists(key, bad):
    """A missing key or a falsy non-list must not read as an empty list."""
    payload = _genuine_full_payload("a" * 64)
    if bad == "__missing__":
        payload.pop(key, None)
    else:
        payload[key] = bad
    problems = validate_release_acceptance_contract(payload)
    assert any(key in p for p in problems)
