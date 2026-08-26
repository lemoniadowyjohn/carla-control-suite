"""C23 — audit_thesis_topic_contract run_11 supersession tests.

Context: the legacy structural-gap result `thesis_results/structural_gap_v1/run_11`
is unprovenanced in this worktree (its data files are gitignored and not present on
disk) and has been functionally superseded as the *canonical RQ1 result* by
`reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/` (whole-map gap + curvature fix
+ local_registration). This does NOT touch `run_full_domain_gap.py`'s live
`use_authoritative_alignment_bundle` short-circuit, which is a separate, file-gated
alignment-cache consumer of the same directory and is out of scope here.

These tests assert:
  1. The `run11` audit section reports an explicit `superseded_by` pointer to C14.
  2. The missing-provenance flags (source_available=False etc.) are no longer
     surfaced as a silent/unaddressed gap: `unresolved_or_unverified` must contain
     an explicit entry documenting the supersession (status class distinct from a
     live blocking gap), not omit run_11 from that list entirely.
  3. `_current_rq_tables_audit` (the separate C19 honesty gate) is untouched and
     still passes ok=True with 0 violations against the real repo rq_tables.json.
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.tools.audit_thesis_topic_contract import (
    _current_rq_tables_audit,
    _main_payload,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    # ultimate_pipeline/tests/unit/<file> -> repo root is 3 parents up
    return here.parents[3]


def test_run11_reports_explicit_supersession_by_c14() -> None:
    payload = _main_payload(_repo_root())
    run11 = payload["run11"]

    assert run11.get("superseded_by") == "C14_RQ1_STRUCTURAL_GAP"
    assert "local_registration" in str(run11.get("superseded_by_detail", "")).lower()


def test_run11_missing_provenance_not_silently_dropped_from_unresolved_list() -> None:
    payload = _main_payload(_repo_root())
    topics = {item["topic"]: item for item in payload["unresolved_or_unverified"]}

    assert "run11_provenance_gap" in topics
    entry = topics["run11_provenance_gap"]
    # Explicitly resolved-via-supersession, not a live blocking gap.
    assert entry["status"] == "resolved_via_supersession"
    assert "C14" in entry["detail"]


def test_run11_superseded_flag_does_not_depend_on_source_presence() -> None:
    """Whether or not the legacy run_11 data files happen to exist on this
    machine, the supersession pointer must be reported (it is a statement about
    which result is canonical for RQ1 reporting, not about file presence)."""
    payload = _main_payload(_repo_root())
    run11 = payload["run11"]

    # source_available reflects real on-disk state (may be True or False
    # depending on the machine); superseded_by must be present regardless.
    assert isinstance(run11.get("source_available"), bool)
    assert run11.get("superseded_by") == "C14_RQ1_STRUCTURAL_GAP"


def test_current_rq_tables_audit_untouched_and_still_passes() -> None:
    """C19 honesty gate must remain green and unaffected by the run_11 changes."""
    result = _current_rq_tables_audit(_repo_root())

    assert result["rq_tables_found"] is True
    assert result["violations"] == []
    assert result["ok"] is True
