"""ultimate_pipeline/tools/validate_governance.py -- validates AGENT_TASK_LEDGER.md /
AGENT_SYNC.md format compliance for this repo's own multi-agent coordination process (task
statuses, tmp-path labeling rules, patch-quality metadata). This is process governance for the
development workflow itself, not CARLA/OpenDRIVE pipeline correctness -- lower priority than
the rest of this sweep, but still a real, currently-untested, self-contained gap.

This pass covers the pure markdown/git-status-line parsing and validation functions.
Out of scope (matching this sweep's established pattern): _git_porcelain (subprocess),
_iter_static_scan_targets/_iter_repo_owned_production_modules/_validate_static_scan_scope/
_validate_no_sys_path_mutation/_validate_namespace_import_drift (scan the real repo tree
rather than operating on pure inputs), and validate()/main() (top-level orchestration).
Found untested via the orphaned-.pyc sweep.
"""
from __future__ import annotations

from ultimate_pipeline.tools.validate_governance import (
    _extract_target_file_values,
    _extract_task_blocks,
    _is_blank_or_tbd,
    _is_excluded_scan_path,
    _line_has_allowed_tmp_label,
    _looks_like_file_path,
    _normalize_status_token,
    _parse_git_status_path,
    _resolved_tmp_is_diagnostic_promoted,
    _section_allows_tmp,
    _validate_active_patch_metadata,
    _validate_evidence_paths,
    _validate_ledger_resolved_section,
    _validate_patch_quality_rules,
    _validate_primary_task_statuses,
    _validate_tmp_paths_with_labels,
)
from pathlib import Path


# ---------------------------------------------------------------------------
# _parse_git_status_path
# ---------------------------------------------------------------------------

def test_parse_git_status_path_simple_modified():
    assert _parse_git_status_path(" M path/to/file.py") == "path/to/file.py"


def test_parse_git_status_path_rename_uses_destination():
    assert _parse_git_status_path("R  old/name.py -> new/name.py") == "new/name.py"


def test_parse_git_status_path_quoted_path_unescaped():
    # git C-quotes paths containing special chars; parser must unescape and strip quotes.
    assert _parse_git_status_path(' M "path/with space.py"') == "path/with space.py"


def test_parse_git_status_path_normalizes_backslashes():
    assert _parse_git_status_path(" M path\\to\\file.py") == "path/to/file.py"


def test_parse_git_status_path_too_short_returns_empty():
    assert _parse_git_status_path("MM") == ""


# ---------------------------------------------------------------------------
# _extract_task_blocks
# ---------------------------------------------------------------------------

def test_extract_task_blocks_finds_all_primary_headers():
    ledger = "## T-001\nbody1\n### T-002\nbody2\n"
    blocks = _extract_task_blocks(ledger)
    assert [b[0] for b in blocks] == ["T-001", "T-002"]


def test_extract_task_blocks_captures_line_numbers():
    ledger = "intro\n\n## T-001\nbody\n"
    blocks = _extract_task_blocks(ledger)
    assert blocks[0][1] == 3  # 1-indexed line of the "## T-001" header


def test_extract_task_blocks_no_headers_returns_empty():
    assert _extract_task_blocks("just some text, no task headers") == []


def test_extract_task_blocks_last_block_runs_to_end_of_document():
    ledger = "## T-001\nline1\nline2\n"
    blocks = _extract_task_blocks(ledger)
    assert "line2" in blocks[0][2]


# ---------------------------------------------------------------------------
# _is_excluded_scan_path
# ---------------------------------------------------------------------------

def test_is_excluded_scan_path_excludes_pycache():
    assert _is_excluded_scan_path(Path("ultimate_pipeline/__pycache__/x.py")) is True


def test_is_excluded_scan_path_excludes_vendored_hint():
    assert _is_excluded_scan_path(Path("ultimate_pipeline/vendored_lib/x.py")) is True


def test_is_excluded_scan_path_normal_module_not_excluded():
    assert _is_excluded_scan_path(Path("ultimate_pipeline/quality/x.py")) is False


# ---------------------------------------------------------------------------
# _line_has_allowed_tmp_label / _section_allows_tmp / _resolved_tmp_is_diagnostic_promoted
# ---------------------------------------------------------------------------

def test_line_has_allowed_tmp_label_detects_any_of_the_three():
    assert _line_has_allowed_tmp_label("some line [WIP] more text") is True
    assert _line_has_allowed_tmp_label("some line [DIAGNOSTIC] more") is True
    assert _line_has_allowed_tmp_label("some line [POC] more") is True
    assert _line_has_allowed_tmp_label("no label here") is False


def test_section_allows_tmp_active_tasks_or_changelog():
    assert _section_allows_tmp("Active Tasks", "") is True
    assert _section_allows_tmp("Changelog", "") is True
    assert _section_allows_tmp("Diagnostic Evidence", "") is False  # only valid as h3


def test_section_allows_tmp_diagnostic_evidence_as_h3():
    assert _section_allows_tmp("Some Other Section", "Diagnostic Evidence") is True


def test_section_allows_tmp_unrelated_section_disallowed():
    assert _section_allows_tmp("Resolved Tasks", "Notes") is False


def test_resolved_tmp_is_diagnostic_promoted_requires_both_label_and_promoted_path():
    line_ok = "| R-001 | RESOLVED | [DIAGNOSTIC] original: `_tmp/x.json` promoted to `artifacts/x.json` |"
    assert _resolved_tmp_is_diagnostic_promoted(line_ok) is True


def test_resolved_tmp_is_diagnostic_promoted_missing_label_fails():
    line = "| R-001 | RESOLVED | promoted to `artifacts/x.json` |"
    assert _resolved_tmp_is_diagnostic_promoted(line) is False


def test_resolved_tmp_is_diagnostic_promoted_missing_promoted_path_fails():
    line = "| R-001 | RESOLVED | [DIAGNOSTIC] original: `_tmp/x.json` |"
    assert _resolved_tmp_is_diagnostic_promoted(line) is False


# ---------------------------------------------------------------------------
# _is_blank_or_tbd / _looks_like_file_path
# ---------------------------------------------------------------------------

def test_is_blank_or_tbd_empty_and_whitespace():
    assert _is_blank_or_tbd("") is True
    assert _is_blank_or_tbd("   ") is True


def test_is_blank_or_tbd_tbd_case_insensitive():
    assert _is_blank_or_tbd("tbd") is True
    assert _is_blank_or_tbd("TBD") is True


def test_is_blank_or_tbd_real_value_is_false():
    assert _is_blank_or_tbd("some/real/path.py") is False


def test_looks_like_file_path_requires_a_separator():
    assert _looks_like_file_path("not_a_path") is False
    assert _looks_like_file_path("some/path.py") is True


def test_looks_like_file_path_rejects_values_with_spaces():
    assert _looks_like_file_path("some path/with spaces.py") is False


def test_looks_like_file_path_strips_backticks():
    assert _looks_like_file_path("`some/path.py`") is True


def test_looks_like_file_path_rejects_blank_or_tbd():
    assert _looks_like_file_path("TBD") is False


# ---------------------------------------------------------------------------
# _extract_target_file_values
# ---------------------------------------------------------------------------

def test_extract_target_file_values_inline_comma_separated():
    block = "## T-001\n- Target Files: `a/b.py`, `c/d.py`\n"
    assert _extract_target_file_values(block) == ["a/b.py", "c/d.py"]


def test_extract_target_file_values_tbd_inline_falls_through_to_bullets():
    block = "## T-001\n- Target Files: TBD\n  - `a/b.py`\n  - `c/d.py`\n- Status: OPEN\n"
    assert _extract_target_file_values(block) == ["a/b.py", "c/d.py"]


def test_extract_target_file_values_no_target_files_line_returns_empty():
    assert _extract_target_file_values("## T-001\n- Status: OPEN\n") == []


def test_extract_target_file_values_bullets_stop_at_next_metadata_field():
    block = "## T-001\n- Target Files:\n  - `a/b.py`\n- Status: OPEN\n  - not_a_target.py\n"
    assert _extract_target_file_values(block) == ["a/b.py"]


# ---------------------------------------------------------------------------
# _normalize_status_token
# ---------------------------------------------------------------------------

def test_normalize_status_token_strips_markdown_backticks_and_uppercases():
    # [A-Z_]+ includes underscore, so the whole "IN_PROGRESS" token is captured, not truncated.
    assert _normalize_status_token("`IN_PROGRESS`") == "IN_PROGRESS"
    assert _normalize_status_token("in_progress") == "IN_PROGRESS"


def test_normalize_status_token_stops_before_trailing_free_text():
    assert _normalize_status_token("RESOLVED (see PR #42)") == "RESOLVED"


def test_normalize_status_token_empty_returns_empty():
    assert _normalize_status_token("") == ""
    assert _normalize_status_token(None) == ""


def test_normalize_status_token_strips_asterisks_and_spaces():
    assert _normalize_status_token("  *BLOCKED*  ") == "BLOCKED"


# ---------------------------------------------------------------------------
# _validate_ledger_resolved_section
# ---------------------------------------------------------------------------

def test_validate_ledger_resolved_section_no_headers_ok():
    assert _validate_ledger_resolved_section("just some text") == []


def test_validate_ledger_resolved_section_flags_resolved_header_inside_active():
    ledger = (
        "## Active Tasks\n"
        "### R-001\nbody\n"
        "## Resolved Tasks\n"
    )
    errors = _validate_ledger_resolved_section(ledger)
    assert len(errors) == 1
    assert "R-001" in errors[0]


def test_validate_ledger_resolved_section_resolved_header_after_resolved_section_ok():
    ledger = (
        "## Active Tasks\n"
        "## Resolved Tasks\n"
        "### R-001\nbody\n"
    )
    assert _validate_ledger_resolved_section(ledger) == []


def test_validate_ledger_resolved_section_missing_either_header_is_noop():
    assert _validate_ledger_resolved_section("## Active Tasks\nno resolved section here\n") == []


# ---------------------------------------------------------------------------
# _validate_primary_task_statuses
# ---------------------------------------------------------------------------

def test_validate_primary_task_statuses_valid_status_ok():
    ledger = "## T-001\n- Status: IN_PROGRESS\n"
    assert _validate_primary_task_statuses(ledger) == []


def test_validate_primary_task_statuses_illegal_status_flagged():
    ledger = "## T-001\n- Status: MADE_UP_STATUS\n"
    errors = _validate_primary_task_statuses(ledger)
    assert len(errors) == 1
    assert "illegal Status" in errors[0]


def test_validate_primary_task_statuses_missing_status_ok_unless_patch_ready():
    ledger_no_patch_ready = "## T-001\n- Task Class: PATCH\n"
    assert _validate_primary_task_statuses(ledger_no_patch_ready) == []

    ledger_patch_ready = "## T-001\n- Patch Ready: yes\n"
    errors = _validate_primary_task_statuses(ledger_patch_ready)
    assert len(errors) == 1
    assert "missing Status" in errors[0]


# ---------------------------------------------------------------------------
# _validate_active_patch_metadata
# ---------------------------------------------------------------------------

def test_validate_active_patch_metadata_resolved_task_skipped():
    ledger = "## T-001\n- Status: RESOLVED\n- Task Class: PATCH\n"
    assert _validate_active_patch_metadata(ledger) == []


def test_validate_active_patch_metadata_active_patch_missing_fields_flagged():
    ledger = "## T-001\n- Status: IN_PROGRESS\n- Task Class: PATCH\n"
    errors = _validate_active_patch_metadata(ledger)
    assert any("Active Branch" in e for e in errors)
    assert any("Patch Ready" in e for e in errors)
    assert any("Minimum Verification" in e for e in errors)


def test_validate_active_patch_metadata_complete_active_patch_ok():
    ledger = (
        "## T-001\n"
        "- Status: IN_PROGRESS\n"
        "- Task Class: PATCH\n"
        "- Active Branch: fix/thing\n"
        "- Patch Ready: no\n"
        "- Minimum Verification: pytest tests/unit\n"
    )
    assert _validate_active_patch_metadata(ledger) == []


def test_validate_active_patch_metadata_contradictory_gemini_routing_flagged():
    ledger = (
        "## T-001\n"
        "- Status: IN_PROGRESS\n"
        "- Gemini First: no\n"
        "- Gemini Output Required: diagnosis and sync plan\n"
    )
    errors = _validate_active_patch_metadata(ledger)
    assert any("contradictory routing" in e for e in errors)


# ---------------------------------------------------------------------------
# _validate_patch_quality_rules
# ---------------------------------------------------------------------------

def test_validate_patch_quality_rules_non_patch_task_skipped():
    ledger = "## T-001\n- Task Class: RESEARCH\n- Priority: P0\n- Patch Ready: yes\n"
    assert _validate_patch_quality_rules(ledger) == []


def test_validate_patch_quality_rules_low_priority_patch_skipped():
    ledger = "## T-001\n- Task Class: PATCH\n- Priority: P2\n- Patch Ready: yes\n"
    assert _validate_patch_quality_rules(ledger) == []


def test_validate_patch_quality_rules_not_patch_ready_skipped():
    ledger = "## T-001\n- Task Class: PATCH\n- Priority: P0\n- Patch Ready: no\n"
    assert _validate_patch_quality_rules(ledger) == []


def test_validate_patch_quality_rules_p0_ready_patch_missing_everything_flagged():
    ledger = "## T-001\n- Task Class: PATCH\n- Priority: P0\n- Patch Ready: yes\n"
    errors = _validate_patch_quality_rules(ledger)
    assert any("Active Branch" in e for e in errors)
    assert any("Target Files" in e for e in errors)
    assert any("Minimum Verification" in e for e in errors)


def test_validate_patch_quality_rules_complete_p1_ready_patch_ok():
    ledger = (
        "## T-001\n"
        "- Task Class: PATCH\n"
        "- Priority: P1\n"
        "- Patch Ready: yes\n"
        "- Active Branch: fix/thing\n"
        "- Target Files: `a/b.py`\n"
        "- Minimum Verification: pytest tests/unit/test_thing.py\n"
    )
    assert _validate_patch_quality_rules(ledger) == []


def test_validate_patch_quality_rules_placeholder_min_verification_flagged():
    ledger = (
        "## T-001\n"
        "- Task Class: PATCH\n"
        "- Priority: P0\n"
        "- Patch Ready: yes\n"
        "- Active Branch: fix/thing\n"
        "- Target Files: `a/b.py`\n"
        "- Minimum Verification: <...>\n"
    )
    errors = _validate_patch_quality_rules(ledger)
    assert any("placeholder text" in e for e in errors)


# ---------------------------------------------------------------------------
# _validate_evidence_paths / _validate_tmp_paths_with_labels
# ---------------------------------------------------------------------------

def test_validate_evidence_paths_absolute_windows_path_flagged():
    ledger = "## Active Tasks\nSee C:\\Users\\admin\\file.txt for details\n"
    errors = _validate_evidence_paths(ledger)
    assert any("absolute path forbidden" in e for e in errors)


def test_validate_evidence_paths_tmp_path_in_active_tasks_with_label_ok():
    ledger = "## Active Tasks\n[WIP] see `_tmp/scratch/data.json`\n"
    assert _validate_evidence_paths(ledger) == []


def test_validate_evidence_paths_tmp_path_in_active_tasks_without_label_flagged():
    ledger = "## Active Tasks\nsee `_tmp/scratch/data.json`\n"
    errors = _validate_evidence_paths(ledger)
    assert any("requires allowed section" in e for e in errors)


def test_validate_evidence_paths_tmp_path_in_scenario_b_section_always_forbidden():
    ledger = "## Scenario B Completion\n[WIP] `_tmp/scratch/data.json`\n"
    errors = _validate_evidence_paths(ledger)
    assert any("Scenario B / Evidence Pack / Thesis Claim" in e for e in errors)


def test_validate_evidence_paths_resolved_row_tmp_requires_diagnostic_promotion():
    ledger = "## Resolved Tasks\n| R-001 | RESOLVED | `_tmp/scratch/data.json` |\n"
    errors = _validate_evidence_paths(ledger)
    assert any("RESOLVED evidence row" in e for e in errors)


def test_validate_tmp_paths_with_labels_flags_unlabeled_tmp_path():
    errors = _validate_tmp_paths_with_labels("AGENT_SYNC.md", "see `_tmp/x/y.json` for context")
    assert len(errors) == 1
    assert "GOV-TMP-EXT" in errors[0]


def test_validate_tmp_paths_with_labels_labeled_tmp_path_ok():
    errors = _validate_tmp_paths_with_labels("AGENT_SYNC.md", "[WIP] see `_tmp/x/y.json`")
    assert errors == []
