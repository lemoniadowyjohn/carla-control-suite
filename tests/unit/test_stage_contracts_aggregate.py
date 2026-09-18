# tests/unit/test_stage_contracts_aggregate.py
# -*- coding: utf-8 -*-

"""
OC-35 aggregate/waiver precedence regression tests.

Contracted semantics of `promote_aggregate` / `promote_aggregate_detailed` in
`ultimate_pipeline.contracts.stage_contracts`:

- Every child is converted per-child BEFORE any reduction.
- A FAIL child may only become WAIVED through an explicit governed waiver that
  names that exact child AND that child is on the `mandatory_children`
  allow-list. Waivers are single-use: one failing child per waiver.
- Waivers can never convert INCOMPLETE / NOT_RUN / BLOCKED_EXTERNAL to WAIVED.
- Unkwnown / ungoverned inputs coerce to INCOMPLETE (fail-closed).
- The aggregate is the worst remaining status under the ordered severity
  FAIL > INCOMPLETE > BLOCKED_EXTERNAL > WAIVED > NOT_RUN > PASS, and is never
  PASS while any child is non-PASS.
"""

import pytest

from ultimate_pipeline.contracts.stage_contracts import (
    QualityStatus,
    promote_aggregate,
    promote_aggregate_detailed,
)

P = QualityStatus.PASS
F = QualityStatus.FAIL
INC = QualityStatus.INCOMPLETE
NR = QualityStatus.NOT_RUN
BLK = QualityStatus.BLOCKED_EXTERNAL
W = QualityStatus.WAIVED

GOVERNED = {"carburetor": "Research regression requires the old carburetor."}


# ---------------------------------------------------------------------------
# A. Uncrunched pass chain: every child passes before any level change.
# ---------------------------------------------------------------------------


def test_a_uncorrupted_pass_chain_stays_pass():
    for children in ([P, P, P], [P], [True, True]):
        assert promote_aggregate(children) == P


def test_a_per_child_conversion_preserves_components():
    detail = promote_aggregate_detailed(
        [P, F, INC],
        mandatory_children=["part_a", "part_b", "part_c"],
        waivers={"part_b": GOVERNED["carburetor"]},
    )
    assert [row["status"] for row in detail["children"]] == [P, W, INC]
    assert [row["name"] for row in detail["children"]] == [
        "part_a",
        "part_b",
        "part_c",
    ]


# ---------------------------------------------------------------------------
# B. Severity reduction is enforced AFTER per-child conversion.
# ---------------------------------------------------------------------------


def test_b_waived_fail_and_incomplete_elsewhere_reduces_to_incomplete():
    assert (
        promote_aggregate(
            [F, INC],
            mandatory_children=["speed", "due_diligence"],
            waivers={"speed": GOVERNED["carburetor"]},
        )
        == INC
    )


def test_b_blocked_external_outranks_waived():
    assert (
        promote_aggregate(
            [F, BLK],
            mandatory_children=["speed", "tracks"],
            waivers={"speed": GOVERNED["carburetor"]},
        )
        == BLK
    )


# ---------------------------------------------------------------------------
# C. A waivable FAIL with an explicit governed waiver becomes WAIVED.
# ---------------------------------------------------------------------------


def test_c_waivable_fail_with_waiver_is_waived():
    assert (
        promote_aggregate(
            [F],
            mandatory_children=["speed"],
            waivers={"speed": GOVERNED["carburetor"]},
        )
        == W
    )


# ---------------------------------------------------------------------------
# D. Unwaivable FAIL remains FAIL.
# ---------------------------------------------------------------------------


def test_d_fail_without_waiver_stays_fail():
    assert promote_aggregate([F], mandatory_children=["speed"]) == F


def test_d_fail_outside_allow_list_stays_fail_even_with_waiver():
    assert (
        promote_aggregate(
            [F],
            mandatory_children=["unrelated"],
            waivers={"speed": GOVERNED["carburetor"]},
        )
        == F
    )


def test_d_waivable_fail_flag_off_keeps_fail():
    assert (
        promote_aggregate(
            [F],
            mandatory_children=["speed"],
            waivers={"speed": GOVERNED["carburetor"]},
            waivable_fail=False,
        )
        == F
    )


# ---------------------------------------------------------------------------
# E. A waiver can never convert INCOMPLETE/NOT_RUN/BLOCKED_EXTERNAL to WAIVED.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [INC, NR, BLK],
    ids=["incomplete", "not_run", "blocked_external"],
)
def test_e_waiver_never_converts_non_fail_evidence_gaps(status):
    assert (
        promote_aggregate(
            [status],
            mandatory_children=["speed"],
            waivers={"speed": GOVERNED["carburetor"]},
        )
        == status
    )


def test_e_mixed_with_waived_fail_missing_child_is_waived_not_run():
    # NOT_RUN sits BELOW WAIVED in the mandated severity order
    # (FAIL > INCOMPLETE > BLOCKED_EXTERNAL > WAIVED > NOT_RUN > PASS), so the
    # trained waiver governs; the never-run child must still be surfaced.
    result = promote_aggregate(
        [F, NR],
        mandatory_children=["speed", "sensor"],
        waivers={"speed": GOVERNED["carburetor"]},
    )
    assert result in (W, NR)
    assert result == W


# ---------------------------------------------------------------------------
# F. Waivers are single-use: every failing child needs its own waiver.
# ---------------------------------------------------------------------------


def test_f_partial_waiver_coverage_stays_fail():
    assert (
        promote_aggregate(
            [F, F],
            mandatory_children=["a", "b"],
            waivers={"a": "covered"},
        )
        == F
    )


def test_f_full_waiver_coverage_is_waived():
    assert (
        promote_aggregate(
            [F, F],
            mandatory_children=["a", "b"],
            waivers={"a": "covered", "b": "covered"},
        )
        == W
    )


# ---------------------------------------------------------------------------
# G. Ungoverned / unknown values coerce to INCOMPLETE (never PASS).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unknown",
    [None, 3.14, object(), "not_a_status", [], {}],
    ids=["none", "float", "object", "bogus_string", "empty_list", "empty_dict"],
)
def test_g_unknown_values_map_to_incomplete(unknown):
    assert promote_aggregate([unknown]) == INC


def test_g_unknown_string_child_row_reports_coercion():
    detail = promote_aggregate_detailed(["bogus_status"])
    row = detail["children"][0]
    assert row["status"] == INC
    assert row["coerced_from"] == "incomplete"


# ---------------------------------------------------------------------------
# H. Aggregate is never PASS while any child is non-PASS.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "non_pass", [W, NR, BLK, INC, F], ids=["waived", "not_run", "blocked", "incomplete", "fail"]
)
def test_h_mixed_pass_and_non_pass_is_never_pass(non_pass):
    assert promote_aggregate([P, P, non_pass]) != P


def test_h_waived_non_pass_still_blocks_pass():
    assert promote_aggregate([P, W, P], mandatory_children=["x"], waivers={"x": "doc"}) == W


# ---------------------------------------------------------------------------
# I. A name-only waiver with no FAILing child does nothing (nothing to waive).
# ---------------------------------------------------------------------------


def test_i_name_only_waiver_without_fail_is_inert():
    result = promote_aggregate(
        [P, P],
        mandatory_children=["speed", "sensor"],
        waivers={"sensor": GOVERNED["carburetor"]},
    )
    assert result == P
    detail = promote_aggregate_detailed(
        [P, P],
        mandatory_children=["speed", "sensor"],
        waivers={"sensor": GOVERNED["carburetor"]},
    )
    assert "sensor" in detail["unused_waiver_keys"]
    assert {row["name"] for row in detail["children"]} >= {"sensor"}


# ---------------------------------------------------------------------------
# J. Positional/label mismatch: a waiver can never waive the wrong child.
# ---------------------------------------------------------------------------


def test_j_waiver_for_passing_position_does_not_waive_failing_sibling():
    assert (
        promote_aggregate(
            [P, F],
            mandatory_children=["alpha", "beta"],
            waivers={"alpha": GOVERNED["carburetor"]},
        )
        == F
    )


def test_j_waiver_keyed_to_missing_name_waives_nothing():
    assert (
        promote_aggregate(
            [F],
            mandatory_children=["alpha"],
            waivers={"beta": GOVERNED["carburetor"]},
        )
        == F
    )


# ---------------------------------------------------------------------------
# K. Boolean coercion True->PASS / False->FAIL.
# ---------------------------------------------------------------------------


def test_k_boolean_coercion():
    assert promote_aggregate([False, True]) == F
    assert promote_aggregate([True, True]) == P
    assert promote_aggregate([True, False, False]) == F


# ---------------------------------------------------------------------------
# L. Named-child ordering divergence audit + strict explicit naming.
# ---------------------------------------------------------------------------


def test_l_explicit_child_names_override_positional_order():
    assert (
        promote_aggregate(
            [P, F],
            mandatory_children=["alpha", "beta"],
            child_names=["beta", "alpha"],
            waivers={"alpha": GOVERNED["carburetor"]},
        )
        == W
    )


def test_l_explicit_child_names_mismatch_length_raises():
    with pytest.raises(ValueError):
        promote_aggregate_detailed([P, F], child_names=["only_one"])


def test_l_duplicate_child_names_raise_ambiguity():
    with pytest.raises(ValueError):
        promote_aggregate_detailed([P, F], child_names=["dup", "dup"])


def test_l_positional_audit_reported():
    detail = promote_aggregate_detailed([P, F], mandatory_children=["a", "b", "c", "d"])
    audit = detail["positional_audit"]
    assert audit["children_count"] == 2
    assert audit["mandatory_children_count"] == 4
    assert audit["overflow_names"] == ["c", "d"]
    assert audit["ambiguous"] is True


def test_l_empty_children_are_incomplete():
    assert promote_aggregate([]) == INC
    detail = promote_aggregate_detailed([])
    assert detail["aggregate"] == INC
    assert detail["children"] == []