"""C23 -- extract_elevation_stats.py's `thesis_impact` note must point at the
current canonical RQ1 result (C14_RQ1_STRUCTURAL_GAP), not the superseded
legacy `run_11` artifact.

run_11 is still a real, valid input to run_full_domain_gap.py's
use_authoritative_alignment_bundle short-circuit (a separate, file-gated
alignment-cache consumer) -- that is untouched. This test only covers the
human-readable "which result is thesis-authoritative" claim string emitted by
this DEM/elevation verifier tool.
"""
from __future__ import annotations

from ultimate_pipeline.tools.extract_elevation_stats import THESIS_IMPACT_NOTE


def test_thesis_impact_note_points_at_c14_not_run11() -> None:
    assert "C14_RQ1_STRUCTURAL_GAP" in THESIS_IMPACT_NOTE
    assert "run_11" not in THESIS_IMPACT_NOTE


def test_thesis_impact_note_still_scopes_this_tool_as_supplementary() -> None:
    assert "supplementary" in THESIS_IMPACT_NOTE.lower()
