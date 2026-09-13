from __future__ import annotations

import hashlib
from pathlib import Path

from ultimate_pipeline.tools.structure_elevation_crs_probe import probe_xodr


def test_probe_records_unresolved_crs_without_mutating_source(tmp_path: Path) -> None:
    xodr = tmp_path / "map.xodr"
    payload = b"<?xml version='1.0' encoding='UTF-8'?><OpenDRIVE/>"
    xodr.write_bytes(payload)

    report = probe_xodr(xodr)

    assert report["input"]["xodr_sha256"] == hashlib.sha256(payload).hexdigest()
    assert report["crs_contract"]["verdict"] == "UNRESOLVED"
    assert report["structure_elevation_gate"] == {
        "status": "NOT_RUN",
        "reason": "run_gate_not_requested",
    }
    assert report["source_xodr_unchanged"] is True
    assert report["map_of_record_mutated"] == "NO"
    assert report["live_carla"] == "NOT_RUN"
