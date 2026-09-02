# scripts/regen_map_of_record.py::_find_final_xodr() -- zero prior test
# coverage. WS1.4 (map-quality/RQ hardening plan, 2026-09-02): discovered
# via a real, live canonical regen (not a synthetic reproduction) that this
# function has NEVER picked up C10 map-hygiene's (stage_08_hygiene.py,
# added 2026-08-19) corrected output.
#
# stage_08_hygiene.py writes 08h1_island_quarantined.xodr ->
# 08h2_degenerate_lanes_repaired.xodr -> 08h3_zseams_repaired.xodr, none of
# which match "08_final*" (prefix "08h", not "08_final") or
# "*DROP_BAD_LINKS*". _find_final_xodr()'s glob only matched those two
# patterns, so it always silently fell back to the PRE-hygiene
# 08_final*_linkpatched.xodr -- every governed regen since hygiene was
# wired in has emitted a candidate with island quarantine, degenerate-lane
# repair, and z-seam repair silently discarded, despite the hygiene stage
# genuinely running and producing correct output.
#
# Directly reproduced against a real regen run
# (campaigns/.../regen/20260902T151513Z/): 08h1_island_quarantined.xodr had
# 30 fewer roads (32267 vs 32297) than the pre-hygiene file this function
# picked; the emitted candidate matched the pre-hygiene file's road count,
# confirming the hygiene repairs never reached the final artifact.
from __future__ import annotations

import time
from pathlib import Path

import scripts.regen_map_of_record as regen


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_picks_hygiene_output_over_pre_hygiene_final_when_newer(tmp_path: Path):
    _write(tmp_path / "08_final_X.xodr", "pre-repair")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_laneSectionFixed_lane_successor_fixed_linkpatched.xodr", "pre-hygiene final")
    time.sleep(0.02)
    _write(tmp_path / "08h1_island_quarantined.xodr", "hygiene step 1")
    time.sleep(0.02)
    _write(tmp_path / "08h2_degenerate_lanes_repaired.xodr", "hygiene step 2")
    time.sleep(0.02)
    _write(tmp_path / "08h3_zseams_repaired.xodr", "hygiene step 3 -- the real final output")

    result = regen._find_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "hygiene step 3 -- the real final output"


def test_falls_back_to_pre_hygiene_final_when_no_hygiene_output_present(tmp_path: Path):
    # ENABLE_MAP_HYGIENE=0 runs, or a run that predates stage_08_hygiene.py
    # entirely: no 08h*.xodr files exist at all.
    _write(tmp_path / "08_final_X.xodr", "pre-repair")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_laneSectionFixed.xodr", "the correct fallback")

    result = regen._find_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "the correct fallback"


def test_hygiene_quarantine_only_still_picked_if_that_is_the_newest_stage(tmp_path: Path):
    # If a later hygiene sub-step never ran (e.g. degenerate-lane repair
    # threw and _step8h_map_hygiene fell back to the island-quarantine
    # output), the newest hygiene file that DOES exist must still win over
    # the older pre-hygiene final.
    _write(tmp_path / "08_final_X_linkpatched.xodr", "pre-hygiene final")
    time.sleep(0.02)
    _write(tmp_path / "08h1_island_quarantined.xodr", "only hygiene step that completed")

    result = regen._find_final_xodr(tmp_path)

    assert result.read_text(encoding="utf-8") == "only hygiene step that completed"


def test_no_candidates_raises_filenotfounderror(tmp_path: Path):
    import pytest

    with pytest.raises(FileNotFoundError, match="08h"):
        regen._find_final_xodr(tmp_path)
