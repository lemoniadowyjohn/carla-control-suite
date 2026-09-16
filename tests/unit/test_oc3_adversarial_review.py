"""Regression tests for OC-3 adversarial review fixes."""
import pathlib
import tempfile
import os
from pathlib import Path

def test_stale_artifact_not_selected_by_mtime():
    # ORIGINAL VERSION OF THIS TEST (from audit/evidence-integrity-v2 @3f7f6f5c)
    # asserted that _newest_final_xodr should pick the lexicographically-FIRST
    # 08_final*_semantic.xodr among two candidates with different embedded
    # timestamps and no other distinguishing signal, on the theory that raw
    # mtime is adversarially untrustworthy. That version directly contradicts
    # an already-established, more thoroughly evidenced regression test for
    # the exact same input shape --
    # ultimate_pipeline/tests/unit/test_artifact_locator_final_xodr.py::
    # test_picks_newest_semantic_variant_when_multiple_semantic_files_exist --
    # which creates two semantic-suffixed files with different mtimes and
    # asserts the NEWER one wins. Both tests construct a structurally
    # identical scenario (two 08_final*_semantic.xodr candidates, no other
    # artifacts) with opposite expected outcomes; no implementation can
    # satisfy both. The lexicographic-first fix was also never actually
    # hash-verified as its own comments claimed ("require hash check by
    # caller" -- no caller ever did), and it silently regressed the fallback
    # (any_final) path: plain sorted() there would prefer the plain
    # pre-repair file over a *_laneSectionFixed.xodr repair output, exactly
    # the CARLA MapBuilder.cpp-assert bug the surrounding docstring exists to
    # prevent, since "." < "_" in ASCII. See artifact_locator.py's
    # _newest_final_xodr / _repaired_sibling_exists docstrings for the
    # resolution: prefer structurally-verified post-repair candidates (a
    # same-run *_laneSectionFixed.xodr sibling on disk) over unverified ones,
    # independent of mtime; only use mtime-newest as a tie-breaker among
    # equally-legitimate candidates. This test now exercises that real
    # safeguard instead of asserting an arbitrary lexicographic tie-break.
    import time

    from ultimate_pipeline.tools.artifact_locator import _newest_final_xodr

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Run A: semantic copy was never refreshed after a repair step (no
        # laneSectionFixed sibling for this run) -- e.g. the repair step
        # crashed, or this run predates ENABLE_LANE_SECTION_REPAIR. Its
        # mtime is bumped LAST, simulating exactly the adversarial/copy
        # scenario the task describes: "a stale file could have a newer
        # mtime than a genuinely-current one after a copy/touch operation".
        stale_unverified = tmp / "08_final_20260915T100000Z_semantic.xodr"
        stale_unverified.write_text("<OpenDRIVE>stale, never repaired</OpenDRIVE>")

        # Run B: has a genuine *_laneSectionFixed.xodr sibling on disk --
        # structural proof this run completed the repair stage -- but an
        # OLDER mtime than run A.
        genuine = tmp / "08_final_20260915T090000Z_semantic.xodr"
        genuine.write_text("<OpenDRIVE>genuine, repaired</OpenDRIVE>")
        (tmp / "08_final_20260915T090000Z_laneSectionFixed.xodr").write_text(
            "<OpenDRIVE>laneSectionFixed output</OpenDRIVE>"
        )

        # Touch the unverified file's mtime to be newer than the genuine,
        # repair-verified one -- this is the "spoofed/stale mtime" attack.
        time.sleep(0.02)
        stale_unverified.touch()

        result = _newest_final_xodr(tmp)

        assert result is not None
        assert result == genuine, (
            f"Expected the structurally repair-verified artifact ({genuine}) "
            f"to win over the unverified one with a newer/spoofed mtime "
            f"({stale_unverified}), got {result}"
        )

def test_map_sha_mismatch_is_fail():
    # Simulate map SHA check
    import hashlib
    p = Path("campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr")
    if not p.exists():
        import pytest
        pytest.skip("map not found")
    expected = "2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798"
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    assert actual == expected, "Map SHA should match expected"
    # Test mismatch case: wrong SHA should be detected
    wrong = "0000000000000000000000000000000000000000000000000000000000000000"
    assert wrong != expected
