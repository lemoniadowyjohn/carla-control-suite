"""
RQ5 protocol v2 contract tests (batch 12).

v1 is immutable and stays exactly as frozen. v2 exists because v1 was
self-contradictory on checkpoint selection and unimplementable in several other
places. These tests pin three things:

* v1 was not edited,
* v2 records the contradiction and the amendment rationale explicitly,
* v2 changed the *minimum*: every v1 hyperparameter is carried over verbatim and
  the checkpoint rule is resolved by a non-post-hoc rule rather than by inventing
  early stopping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.perception.rq5_provenance import (
    PROTOCOL_V2_POLICY,
    PROTOCOL_V2_RELPATH,
    protocol_identity,
    sha256_file,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_PATH = REPO_ROOT / "configs" / "rq5_protocol_freeze_v1.json"
V2_PATH = REPO_ROOT / PROTOCOL_V2_RELPATH

#: SHA-256 of v1 as frozen on 2026-09-30. If this changes, v1 was edited.
V1_FROZEN_SHA256 = "35773ce46c84d806ee1f9e32a3af4fbfa3521c213fa4f85536afa95e0168996d"


@pytest.fixture(scope="module")
def v1() -> dict:
    return json.loads(V1_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def v2() -> dict:
    return json.loads(V2_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# v1 preservation
# ---------------------------------------------------------------------------


def test_v1_file_is_untouched():
    assert sha256_file(V1_PATH) == V1_FROZEN_SHA256, (
        "configs/rq5_protocol_freeze_v1.json must never be edited; an amendment is a new "
        "versioned contract, not an in-place edit"
    )


def test_v1_schema_and_status_are_unchanged(v1):
    assert v1["schema"] == "rq5_protocol_freeze/v1"
    assert v1["status"] == "FROZEN"


def test_v2_supersedes_v1_by_digest(v2):
    assert v2["supersedes"]["sha256"] == V1_FROZEN_SHA256
    assert v2["supersedes"]["file"] == "configs/rq5_protocol_freeze_v1.json"
    assert v2["schema"] == "rq5_protocol_freeze/v2"


# ---------------------------------------------------------------------------
# the contradiction
# ---------------------------------------------------------------------------


def test_v1_contradiction_is_preserved_verbatim(v1, v2):
    """v2 must quote v1's contradictory sentence, not paraphrase it away."""
    original = v1["decisions"]["checkpoint_selection"]["value"]
    assert original == (
        "final-epoch checkpoint only (model_last.pt); selection uses generated-validation "
        "loss; manual test split is never consulted for selection"
    )
    assert v2["v1_contradiction_found"]["v1_text"] == original
    assert v2["decisions"]["checkpoint_selection"]["supersedes_v1_value"] == original


def test_v2_records_the_amendment_rationale(v2):
    contradiction = v2["v1_contradiction_found"]
    assert "SELF_CONTRADICTORY" in contradiction["defect"]
    assert contradiction["resolution_strategy"] == "MINIMAL_NON_POST_HOC_RULE"
    assert "early stopping" in contradiction["why_not_early_stopping"]
    assert "patience" in contradiction["why_not_early_stopping"].lower()
    assert "RQ5_PROTOCOL_UNDERPOWERED" in contradiction["contingency"]
    assert "BEFORE viewing manual-target performance" in contradiction["contingency"]


def test_v2_declares_a_minimum_scientific_change_policy(v2):
    assert v2["scientific_change_policy"].startswith("MINIMUM_SCIENTIFIC_CHANGE")
    assert "No new hyperparameter is introduced" in v2["scientific_change_policy"]


def test_checkpoint_selection_is_resolved_without_inventing_a_rule(v2):
    value = v2["decisions"]["checkpoint_selection"]["value"]
    lowered = value.lower()
    assert "final-epoch checkpoint" in lowered
    assert "never selects a different epoch" in lowered
    assert "no early stopping" in lowered
    assert "never consulted" in lowered
    assert v2["decisions"]["checkpoint_selection"]["changed_in_v2"] is True


# ---------------------------------------------------------------------------
# v1 values preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("model_architecture", "fcn_resnet50"),
        ("optimizer", "Adam"),
        ("learning_rate", 0.0001),
        ("epochs", 3),
        ("batch_size", 4),
        ("augmentations", "none"),
    ],
)
def test_v1_hyperparameter_values_are_carried_over(v1, v2, name, expected):
    original = v1["decisions"][name]["value"]
    amended = v2["decisions"][name]["value"]
    assert v2["decisions"][name]["changed_in_v2"] is False, f"{name} must not be amended in v2"
    if isinstance(expected, float):
        assert float(amended) == pytest.approx(expected)
    elif isinstance(expected, int):
        assert int(amended) == expected
    else:
        assert expected.lower() in str(amended).lower()
    assert original == amended or (
        isinstance(original, str) and isinstance(amended, str) and original.strip() == amended.strip()
    )


def test_every_unchanged_v2_decision_is_verbatim_identical_to_v1(v1, v2):
    """No silent rewording of an unchanged decision."""
    for name, original in v1["decisions"].items():
        amended = v2["decisions"][name]
        if amended.get("changed_in_v2") is False:
            assert amended["value"] == original["value"], (
                f"{name} is marked unchanged in v2 but its text differs from v1"
            )


def test_v1_seed_list_is_preserved(v1, v2):
    original = v1["decisions"]["seed_policy"]["value"]
    amended = v2["decisions"]["seed_policy"]["value"]
    for seed in (7, 17, 42):
        assert str(seed) in original
        assert str(seed) in amended


def test_v1_unchanged_decisions_are_marked_unchanged(v2):
    changed = [k for k, v in v2["decisions"].items() if v.get("changed_in_v2") is True]
    unchanged = [k for k, v in v2["decisions"].items() if v.get("changed_in_v2") is False]
    assert set(changed) & set(unchanged) == set()
    assert len(changed) + len(unchanged) == len(v2["decisions"])
    for name in unchanged:
        assert "amendment" not in v2["decisions"][name]


# ---------------------------------------------------------------------------
# v2 additions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "validation_loop",
        "split_authority",
        "leakage_audit",
        "dataset_quality_gate",
        "dataset_identity_completeness",
        "research_strict_mode",
        "determinism_contract",
        "model_manifest",
        "checkpoint_policy",
        "convergence_gate",
        "evaluation_roles",
        "execution_status",
    ],
)
def test_v2_operational_decisions_are_present_and_amended(v2, name):
    decision = v2["decisions"][name]
    assert decision["changed_in_v2"] is True
    assert decision["value"]
    assert "amendment" in decision


def test_v2_claim_boundary_states_no_training_was_executed(v2):
    boundary = v2["claim_boundary"]
    assert "NO RQ5 model training has been executed" in boundary
    assert "TEST_FIXTURE_ONLY" in boundary


def test_v2_prohibits_town10hd_as_the_final_dataset(v2):
    assert "Town10HD" in v2["decisions"]["execution_status"]["value"]


def test_v2_routes_absent_rq3_data_to_a_blocked_status(v2):
    value = v2["decisions"]["execution_status"]["value"]
    assert "RQ5_OFFLINE_READY_DATASET_BLOCKED" in value
    assert "DEFERRED_RUNTIME" in value


# ---------------------------------------------------------------------------
# binding
# ---------------------------------------------------------------------------


def test_protocol_identity_binds_the_file_digest_not_the_version_string():
    identity = protocol_identity(V2_PATH)
    assert identity["schema"] == "rq5_protocol_freeze/v2"
    assert identity["status"] == "FROZEN"
    assert identity["relpath"] == PROTOCOL_V2_RELPATH
    assert identity["sha256_raw_bytes"] == sha256_file(V2_PATH)


def test_protocol_digest_is_independent_of_line_endings(tmp_path):
    """A CRLF checkout must not look like an amended protocol."""
    payload = json.loads(V2_PATH.read_text(encoding="utf-8"))
    lf = tmp_path / "lf.json"
    lf.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    crlf = tmp_path / "crlf.json"
    crlf.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\r\n")

    lf_identity = protocol_identity(lf)
    crlf_identity = protocol_identity(crlf)
    assert lf_identity["sha256"] == crlf_identity["sha256"]
    assert lf_identity["sha256_raw_bytes"] != crlf_identity["sha256_raw_bytes"]
    assert lf_identity["digest_normalizes_line_endings"] is True


def test_manifest_checkpoint_policy_matches_the_protocol_decision():
    assert PROTOCOL_V2_POLICY["protocol"] == "rq5_protocol_freeze/v2"
    assert PROTOCOL_V2_POLICY["checkpoint_policy"] == "final_epoch_only"
    assert PROTOCOL_V2_POLICY["validation_selects_epoch"] is False
    assert PROTOCOL_V2_POLICY["early_stopping"] is False
    assert PROTOCOL_V2_POLICY["selection_consults_manual"] is False


def test_missing_protocol_file_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        protocol_identity(tmp_path / "absent.json")