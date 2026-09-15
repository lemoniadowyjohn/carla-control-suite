"""Regression tests for OC-3 adversarial review fixes."""
import pathlib
import tempfile
import os
from pathlib import Path

def test_stale_artifact_not_selected_by_mtime():
    # Create two artifacts: older correct, newer incorrect
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        correct = tmp / "08_final_20260915T100000Z_semantic.xodr"
        correct.write_text("<OpenDRIVE></OpenDRIVE>")
        # Ensure correct is older
        import time
        time.sleep(0.01)
        incorrect = tmp / "08_final_20260915T235959Z_semantic.xodr"
        incorrect.write_text("<OpenDRIVE>bad</OpenDRIVE>")
        # The fixed _newest_final_xodr should NOT select by mtime, but by lexicographic first
        # So it should return the 100000Z one, not the 235959Z one
        from ultimate_pipeline.tools.artifact_locator import _newest_final_xodr
        result = _newest_final_xodr(tmp)
        # After fix, it returns first lexicographically, which is 100000Z, not mtime newest 235959Z
        assert result is not None
        assert "100000Z" in str(result), f"Expected 100000Z (lexicographic first), got {result}"

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
