# WS1.1 (map-quality hardening plan, 2026-09-02): scripts/regen_map_of_record.py's
# _measure_acceptance() calls build_map_acceptance(..., require_enrichment=True) but
# never passed require_component_reachability=True -- so even though the
# component-reachability gate exists in map_acceptance.py (and run_gates()
# in measure_candidate_acceptance.py already computes the
# "component_reachability" report every time), the canonical regen path
# never actually enforced "no islands" as a hard fail. isolated lane
# components only ever produced a soft warning, never blocked candidate
# emission.
#
# _measure_acceptance() imports run_gates/build_map_acceptance INSIDE the
# function body (to avoid import cycles), so they're monkeypatched here at
# their DEFINING module (scripts.measure_candidate_acceptance,
# ultimate_pipeline.quality.map_acceptance) rather than on the regen module
# itself -- the local `from X import Y` re-resolves X.Y fresh on each call.
from __future__ import annotations

from pathlib import Path

import scripts.regen_map_of_record as regen
import scripts.measure_candidate_acceptance as measure_mod
import ultimate_pipeline.quality.map_acceptance as map_acceptance_mod


def test_measure_acceptance_passes_require_component_reachability(monkeypatch, tmp_path: Path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(measure_mod, "run_gates", lambda xodr, out_dir, dem: {"fake": "reports"})

    captured_kwargs: dict = {}

    def _fake_build_map_acceptance(reports, **kwargs):
        captured_kwargs.update(kwargs)
        return {
            "valid_for_experiments": True,
            "hard_fail_reasons": [],
            "soft_warnings": [],
            "metrics": {},
        }

    monkeypatch.setattr(map_acceptance_mod, "build_map_acceptance", _fake_build_map_acceptance)

    regen._measure_acceptance(xodr, out_dir)

    assert captured_kwargs.get("require_enrichment") is True
    assert captured_kwargs.get("require_component_reachability") is True


def test_measure_acceptance_hard_fails_on_fragmented_map(monkeypatch, tmp_path: Path):
    # End-to-end (through the real build_map_acceptance, only run_gates
    # mocked): a map whose component_reachability report shows a fragmented
    # drivable network must now make valid_for_experiments False, given the
    # fix under test wires require_component_reachability=True through.
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE/>", encoding="utf-8")
    out_dir = tmp_path / "out"

    fragmented_component_report = {
        "component_count": 2,
        "largest_component_fraction": 0.5,
        "largest_component_lane_count": 5,
        "lane_count": 10,
        "isolated_lane_component_count": 1,
        "unmatched_cross_links": 0,
    }
    monkeypatch.setattr(
        measure_mod,
        "run_gates",
        lambda xodr, out_dir, dem: {"component_reachability": fragmented_component_report},
    )

    acceptance = regen._measure_acceptance(xodr, out_dir)

    assert acceptance["valid_for_experiments"] is False
    assert any(g["gate"] == "component_reachability" for g in acceptance["hard_fail_reasons"])
