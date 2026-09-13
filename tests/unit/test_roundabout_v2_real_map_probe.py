from __future__ import annotations

import hashlib
from pathlib import Path

from ultimate_pipeline.tools.roundabout_v2_real_map_probe import probe_xodr


def test_probe_reports_empty_candidate_set_without_mutating_input(tmp_path: Path) -> None:
    xodr = tmp_path / "empty.xodr"
    payload = b"<?xml version='1.0' encoding='UTF-8'?><OpenDRIVE/>"
    xodr.write_bytes(payload)

    report = probe_xodr(xodr)

    assert report["input"]["xodr_sha256"] == hashlib.sha256(payload).hexdigest()
    assert report["analysis"]["candidate_count"] == 0
    assert report["analysis"]["action_counts"] == {}
    assert report["transaction"]["clone_distinct"] is True
    assert report["transaction"]["source_tree_unchanged"] is True
    assert report["acceptance_delta"] == {
        "status": "NOT_RUN",
        "reason": "no_reconstructed_roundabout_candidates",
    }
    assert report["map_of_record_mutated"] == "NO"
    assert report["live_carla"] == "NOT_RUN"


def test_probe_counts_source_roundabout_semantics_without_using_them_for_detection(
    tmp_path: Path,
) -> None:
    xodr = tmp_path / "empty.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    osm = tmp_path / "source.osm"
    osm.write_text(
        "<osm>"
        "<way id='1'><tag k='junction' v='roundabout'/></way>"
        "<way id='2'><tag k='junction' v='circular'/></way>"
        "<way id='3'><tag k='highway' v='residential'/></way>"
        "</osm>",
        encoding="utf-8",
    )

    report = probe_xodr(xodr, osm_path=osm)

    assert report["analysis"]["candidate_count"] == 0
    assert report["source_osm"]["ways_scanned"] == 3
    assert report["source_osm"]["roundabout_way_counts"] == {
        "circular": 1,
        "roundabout": 1,
    }
    assert report["source_osm"]["roundabout_way_total"] == 2
