"""Regression tests for GAP-023: settings.py's
``_resolve_input_xodr_with_fallback`` picking the newest ``08_final*.xodr``
by raw filesystem mtime with zero structural/content verification.

Same defect class as GAP-012 (already fixed in
``ultimate_pipeline/domain_gap/run_alignment_and_matching.py``): a stale
file touched by an unrelated process, a clock skew, a rebase, or a restored
backup could win purely on mtime, even if it is a partial/incomplete run
and an older candidate is the structurally-complete (repaired) one.

These tests construct two candidate ``08_final*.xodr`` files under a fake
output root with the WRONG relative mtimes -- the OLDER one is the
structurally-complete (post-repair) run, the NEWER one is a partial run
that never reached the lane-section-repair step -- and assert the fallback
must pick the structurally-complete candidate regardless of mtime
ordering.
"""
from __future__ import annotations

import os
import time

from ultimate_pipeline.config.settings import _resolve_input_xodr_with_fallback


def _touch_with_mtime(path, content: bytes, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


class TestResolveInputXodrWithFallbackMtimeAuthority:
    def test_prefers_structurally_complete_candidate_over_newer_partial_one(
        self, tmp_path
    ):
        """GAP-023 RED/GREEN case.

        old_run/08_final_100_semantic.xodr is a genuinely completed run:
        it has a same-prefix *_laneSectionFixed*.xodr sibling on disk (the
        real structural signal used elsewhere in this codebase, see
        ultimate_pipeline/tools/artifact_locator.py::_repaired_sibling_exists).

        new_run/08_final_200_semantic.xodr is a partial run (never reached
        the repair step -- no laneSectionFixed sibling) but has a strictly
        newer mtime than old_run's files.

        A correct, structurally-guarded fallback must pick old_run's file.
        The unguarded raw-mtime implementation picks new_run's file instead
        -- this is the exact bug GAP-023 reports.
        """
        base = tmp_path / "ultimate_pipeline_out"
        now = time.time()

        old_run = base / "old_run_completed"
        old_semantic = old_run / "08_final_100_semantic.xodr"
        old_repaired_sibling = old_run / "08_final_100_laneSectionFixed.xodr"
        _touch_with_mtime(old_semantic, b"<OpenDRIVE complete/>", now - 3600)
        _touch_with_mtime(old_repaired_sibling, b"<OpenDRIVE repaired/>", now - 3600)

        new_run = base / "new_run_partial"
        new_semantic = new_run / "08_final_200_semantic.xodr"
        _touch_with_mtime(new_semantic, b"<OpenDRIVE partial/>", now)

        result = _resolve_input_xodr_with_fallback(str(base))

        assert result == str(old_semantic), (
            "_resolve_input_xodr_with_fallback must prefer the structurally "
            "-complete (repaired-sibling-verified) candidate over a newer "
            f"but partial one; got {result!r}, expected {str(old_semantic)!r}"
        )

    def test_mtime_is_still_the_tiebreaker_among_equally_valid_candidates(
        self, tmp_path
    ):
        """When multiple candidates are equally structurally valid (or none
        are), mtime remains the tiebreaker -- this is not a wholesale
        removal of mtime, only a demotion to secondary signal."""
        base = tmp_path / "ultimate_pipeline_out"
        now = time.time()

        run_a = base / "run_a"
        xodr_a = run_a / "08_final_100.xodr"
        _touch_with_mtime(xodr_a, b"<OpenDRIVE a/>", now - 100)

        run_b = base / "run_b"
        xodr_b = run_b / "08_final_200.xodr"
        _touch_with_mtime(xodr_b, b"<OpenDRIVE b/>", now)

        result = _resolve_input_xodr_with_fallback(str(base))

        assert result == str(xodr_b), (
            "with no structural signal on either candidate, the newer one "
            f"should still win as a tiebreaker; got {result!r}"
        )

    def test_no_candidates_returns_empty_string(self, tmp_path):
        base = tmp_path / "ultimate_pipeline_out"
        base.mkdir(parents=True)
        assert _resolve_input_xodr_with_fallback(str(base)) == ""

    def test_missing_base_dir_returns_empty_string(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        assert _resolve_input_xodr_with_fallback(str(missing)) == ""
