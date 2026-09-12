from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.tools.phase_g3_cross_section import audit_full_map


def _write_map(path: Path, *, road_length: float, geometry_length: float) -> None:
    path.write_text(
        f"""<OpenDRIVE><road id="1" length="{road_length}">
        <planView><geometry s="0" x="0" y="0" hdg="0" length="{geometry_length}"><line/></geometry></planView>
        <lanes><laneSection s="0"><right><lane id="-1" type="driving">
        <width sOffset="0" a="3.5" b="0" c="0" d="0"/>
        </lane></right></laneSection></lanes>
        </road></OpenDRIVE>""",
        encoding="utf-8",
    )


def test_cross_section_coverage_is_complete_when_planview_covers_declared_length(tmp_path):
    xodr = tmp_path / "complete.xodr"
    _write_map(xodr, road_length=10.0, geometry_length=10.0)

    report = audit_full_map(xodr)

    assert report["coverage"]["status"] == "COMPLETE"
    assert report["coverage"]["non_stub_unavailable_section_count"] == 0
    assert report["g3_verdict"] == "PHASE_G_CROSS_SECTION_PASS"


def test_non_stub_planview_tail_gap_is_incomplete_not_a_cross_section_pass(tmp_path):
    xodr = tmp_path / "tail_gap.xodr"
    _write_map(xodr, road_length=10.0, geometry_length=9.95)

    report = audit_full_map(xodr)

    assert report["coverage"]["status"] == "INCOMPLETE"
    assert report["coverage"]["non_stub_unavailable_section_count"] == 1
    assert report["checks"]["no_non_stub_unavailable_sections"] is False
    assert report["g3_verdict"] == "PHASE_G_CROSS_SECTION_INCOMPLETE"


# --------------------------------------------------------------------------
# ultimate_pipeline/core/carla_opendrive_loader.py::repair_road_lengths
# deliberately pads a road's declared length to (true geometry end + 1e-3) to
# stop a real CARLA 0.9.16 LowLevelFatalError (s > road->GetLength() during
# generate_opendrive_world). Verified directly against the pinned map-of-record:
# all 751 roads G3 was reporting INCOMPLETE for have exactly this signature --
# a 0.001 m tail gap, one sample, always at s == declared length. That margin
# is load-bearing and must not be removed at the source; G3's sampler must
# instead tolerate landing inside it. _ROAD_END_TOLERANCE_M (0.01 m) absorbs
# this with headroom while the 0.05 m case above proves a genuine gap still
# fails closed.
# --------------------------------------------------------------------------

def test_known_repair_road_lengths_margin_is_tolerated_as_complete(tmp_path):
    xodr = tmp_path / "repair_margin.xodr"
    _write_map(xodr, road_length=10.001, geometry_length=10.0)

    report = audit_full_map(xodr)

    assert report["coverage"]["status"] == "COMPLETE"
    assert report["coverage"]["non_stub_unavailable_section_count"] == 0
    assert report["g3_verdict"] == "PHASE_G_CROSS_SECTION_PASS"


def test_gap_exactly_at_tolerance_boundary_is_still_tolerated(tmp_path):
    xodr = tmp_path / "boundary.xodr"
    _write_map(xodr, road_length=10.01, geometry_length=10.0)

    report = audit_full_map(xodr)

    assert report["coverage"]["status"] == "COMPLETE"
    assert report["coverage"]["non_stub_unavailable_section_count"] == 0


def test_gap_just_past_tolerance_boundary_still_fails_closed(tmp_path):
    xodr = tmp_path / "just_past_boundary.xodr"
    _write_map(xodr, road_length=10.011, geometry_length=10.0)

    report = audit_full_map(xodr)

    assert report["coverage"]["status"] == "INCOMPLETE"
    assert report["coverage"]["non_stub_unavailable_section_count"] == 1
    assert report["g3_verdict"] == "PHASE_G_CROSS_SECTION_INCOMPLETE"
