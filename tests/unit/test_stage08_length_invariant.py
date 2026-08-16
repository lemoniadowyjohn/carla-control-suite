from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.pipeline_stages.stage_08_integrity import (
    _enforce_final_length_invariant,
)
from ultimate_pipeline.tools.crash_safe_length_repair import length_invariant_summary


def test_stage08_enforces_final_length_invariant_and_writes_evidence(tmp_path: Path) -> None:
    xodr = tmp_path / "candidate.xodr"
    xodr.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        "<header/>"
        '<road id="1" length="1.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="1.1"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    assert length_invariant_summary(ET.parse(xodr).getroot())["violations"] == 1

    _enforce_final_length_invariant(str(xodr), str(tmp_path))

    assert length_invariant_summary(ET.parse(xodr).getroot())["violations"] == 0
    assert (tmp_path / "final_length_invariant_repair.json").exists()
