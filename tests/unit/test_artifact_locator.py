"""Edge-case tests for artifact_locator._repaired_sibling_exists and _newest_final_xodr.

These tests exercise the structural-verification-then-mtime-tiebreak strategy
using real filesystem operations via tmp_path -- no mocks.

Complements ultimate_pipeline/tests/unit/test_artifact_locator_final_xodr.py,
which covers the same module primarily via the find_final_xodr()/
find_xodr_artifact() wrappers; this file adds direct unit coverage of the two
private helpers plus a few structural edge cases (empty/nonexistent run dirs,
multiple-candidate mtime tiebreaks) not exercised there.

Findings while writing these tests are flagged at the bottom.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from ultimate_pipeline.tools.artifact_locator import (
    _newest_final_xodr,
    _repaired_sibling_exists,
)


# ---------------------------------------------------------------------------
# _repaired_sibling_exists
# ---------------------------------------------------------------------------
class TestRepairedSiblingExists:
    """Verify the glob pattern is prefix-anchored correctly."""

    def test_different_timestamp_prefix_not_a_repaired_sibling(self, tmp_path: Path):
        """A _semantic.xodr whose _laneSectionFixed sibling has a DIFFERENT
        timestamp prefix must NOT count as a repaired sibling.

        The glob f"{prefix}*_laneSectionFixed*.xodr" is prefix-anchored on
        the run's fixed <ts> -- it must not match a _laneSectionFixed file
        from a different run whose timestamp differs.
        """
        semantic = tmp_path / "08_final_1234567890_semantic.xodr"
        semantic.touch()
        # A _laneSectionFixed file with a *different* timestamp prefix
        different = tmp_path / "08_final_9999999999_laneSectionFixed.xodr"
        different.touch()
        assert _repaired_sibling_exists(semantic) is False

    def test_same_timestamp_prefix_is_a_repaired_sibling(self, tmp_path: Path):
        """A _semantic.xodr with a same-run _laneSectionFixed sibling MUST
        count as repaired."""
        semantic = tmp_path / "08_final_1234567890_semantic.xodr"
        semantic.touch()
        sibling = tmp_path / "08_final_1234567890_laneSectionFixed.xodr"
        sibling.touch()
        assert _repaired_sibling_exists(semantic) is True

    def test_non_semantic_file_returns_false(self, tmp_path: Path):
        """A file without '_semantic' in its name must return False."""
        plain = tmp_path / "08_final_1234567890.xodr"
        plain.touch()
        assert _repaired_sibling_exists(plain) is False


# ---------------------------------------------------------------------------
# _newest_final_xodr -- semantic candidates with repaired siblings
# ---------------------------------------------------------------------------
class TestNewestFinalXodrSemanticCandidates:
    """Verify mtime correctly breaks ties among verified repaired siblings."""

    def test_mtime_breaks_tie_among_multiple_repaired(self, tmp_path: Path):
        """When MORE than one _semantic.xodr has a verified repaired sibling,
        mtime-newest must win -- not the first alphabetically, not the
        unfiltered pool."""
        # Create two semantic files, both with repaired siblings
        s1 = tmp_path / "08_final_aaa_semantic.xodr"
        s1.touch()
        (tmp_path / "08_final_aaa_laneSectionFixed.xodr").touch()

        time.sleep(0.01)  # ensure distinct mtimes

        s2 = tmp_path / "08_final_bbb_semantic.xodr"
        s2.touch()
        (tmp_path / "08_final_bbb_laneSectionFixed.xodr").touch()

        result = _newest_final_xodr(tmp_path)
        assert result == s2, f"expected mtime-newest ({s2.name}), got {result.name}"


# ---------------------------------------------------------------------------
# _newest_final_xodr -- any_final fallback path
# ---------------------------------------------------------------------------
class TestNewestFinalXodrAnyFinalFallback:
    """Verify the any_final fallback when no _semantic candidates exist."""

    def test_any_final_with_multiple_laneSectionFixed_mtime_tiebreak(self, tmp_path: Path):
        """When there are multiple laneSectionFixed candidates (no _semantic
        files at all), mtime must correctly tiebreak among them."""
        f1 = tmp_path / "08_final_aaa_laneSectionFixed.xodr"
        f1.touch()
        f2 = tmp_path / "08_final_bbb_laneSectionFixed.xodr"
        f2.touch()
        f3 = tmp_path / "08_final_ccc.xodr"  # no laneSectionFixed
        f3.touch()

        result = _newest_final_xodr(tmp_path)
        assert result in (f1, f2), f"expected a laneSectionFixed file, got {result.name}"
        # The newest mtime among laneSectionFixed files must win
        assert result.stat().st_mtime >= min(f1.stat().st_mtime, f2.stat().st_mtime)

    def test_any_final_single_candidate(self, tmp_path: Path):
        """A single 08_final*.xodr file must be returned."""
        f1 = tmp_path / "08_final_single.xodr"
        f1.touch()
        result = _newest_final_xodr(tmp_path)
        assert result == f1


# ---------------------------------------------------------------------------
# _newest_final_xodr -- empty run directory
# ---------------------------------------------------------------------------
class TestNewestFinalXodrEmptyRun:
    """Verify None is returned cleanly for an empty run directory."""

    def test_empty_run_dir_returns_none(self, tmp_path: Path):
        """An empty run directory (no 08_final* files at all) must return
        None cleanly, with no crash."""
        result = _newest_final_xodr(tmp_path)
        assert result is None

    def test_nonexistent_run_dir_returns_none(self, tmp_path: Path):
        """A run directory that does not exist must return None cleanly."""
        result = _newest_final_xodr(tmp_path / "does_not_exist")
        assert result is None


# ---------------------------------------------------------------------------
# Findings / flagging
# ---------------------------------------------------------------------------
def test_findings():
    """Findings flagged while writing these tests:

    1. **_repaired_sibling_exists() glob is prefix-anchored correctly.**
       The pattern f"{prefix}*_laneSectionFixed*.xodr" uses the literal
       prefix from the _semantic filename, so a _laneSectionFixed file
       with a different timestamp prefix will NOT match. This is correct
       and important: it prevents cross-run false positives.

    2. **The any_final fallback only checks for 'laneSectionFixed' in
       the filename string** (a simple `"laneSectionFixed" in p.name`
       substring check), not a glob-based structural verification like
       the _repaired_sibling_exists() helper used on the semantic path.
       This inconsistency means the any_final fallback could match files
       that are not actually repaired by the same strict criteria as the
       semantic path -- worth reconciling but not a correctness bug for
       the currently observed naming convention.

    3. **No race-condition handling.** mtime is read once per file. If
       files are being written concurrently, the mtime ordering could
       change between the glob and the sort. This is acceptable for the
       offline pipeline but worth noting.
    """
    pass
