# scripts/measure_candidate_acceptance.py::run_gates() -- zero prior coverage
# of JunctionIntegrityGate. WS1.4 follow-up (2026-09-02): a real regen's
# hygiene-corrected candidate had 28 JunctionIntegrityGate issues (dangling
# <junction><connection> references left behind by a separate,
# now-fixed map_hygiene.py bug -- see test_map_hygiene.py's
# test_quarantine_island_roads_drops_dangling_connections_both_ends_quarantined),
# but run_gates() never ran that checker at all, so
# _measure_acceptance()/build_map_acceptance() still reported
# valid_for_experiments=True. This wires JunctionIntegrityGate into run_gates()
# so its report reaches build_map_acceptance() and can hard-fail (see
# test_map_acceptance.py's junction_integrity tests for the acceptance side).
from __future__ import annotations

from pathlib import Path

from scripts.measure_candidate_acceptance import run_gates


def _write_xodr_with_dangling_junction(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
  </road>
  <junction id="500" name="J500">
    <connection id="0" incomingRoad="101" connectingRoad="102" contactPoint="start"/>
  </junction>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def _write_clean_xodr(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def test_run_gates_reports_dangling_junction_connections(tmp_path: Path) -> None:
    xodr = tmp_path / "dangling.xodr"
    _write_xodr_with_dangling_junction(xodr)
    out_dir = tmp_path / "out"

    reports = run_gates(xodr, out_dir, dem=None)

    ji = reports.get("junction_integrity")
    assert ji is not None
    assert ji["ok"] is False
    assert ji["issue_count"] == 2  # missing_incoming_road + missing_connecting_road
    assert (out_dir / "junction_integrity.json").is_file()


def test_run_gates_junction_integrity_clean_map(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)
    out_dir = tmp_path / "out"

    reports = run_gates(xodr, out_dir, dem=None)

    ji = reports.get("junction_integrity")
    assert ji is not None
    assert ji["ok"] is True
    assert ji["issue_count"] == 0
