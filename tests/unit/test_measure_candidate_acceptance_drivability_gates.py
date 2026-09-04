# scripts/measure_candidate_acceptance.py::run_gates() -- deep-audit follow-up
# (2026-09-04). Direct verification found 5 more checker modules that exist,
# are complete and correct, and are already used mid-pipeline (or as an
# opt-in live-CARLA perception gate) but were never called by run_gates(), so
# their reports never reached build_map_acceptance() -- the exact same shape
# as the junction_integrity gap fixed earlier this session (see
# test_measure_candidate_acceptance_junction_integrity.py). A candidate could
# have a lane narrower than a car, a 45-degree slope, or a road with no
# elevation data at all and still measure valid_for_experiments=True. This
# wires all 5 into run_gates() (see test_map_acceptance.py for the acceptance
# side of each).
from __future__ import annotations

from pathlib import Path

from scripts.measure_candidate_acceptance import run_gates


def _write_clean_xodr(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
    <lanes>
      <laneSection s="0">
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0" a="3.5" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def _write_lane_width_violation_xodr(path: Path) -> None:
    # A single laneSection with a near-zero driving-lane width -- triggers
    # check_lane_width_continuity's "nonpositive_width" (width <= 0.01).
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
    <lanes>
      <laneSection s="0">
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0" a="0.0" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def _write_lane_geometry_violation_xodr(path: Path) -> None:
    # Two laneSections, same lane id/type, width jump of 0.5m at the boundary
    # -- above lane_geometry_continuity's default eps (0.10) but below
    # lane_width_continuity's default max_jump (1.0), so only this gate fires.
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="20.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="20"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
    <lanes>
      <laneSection s="0">
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0" a="3.5" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
      <laneSection s="10">
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0" a="3.0" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def _write_elevation_missing_xodr(path: Path) -> None:
    # Single road, elevation a=0 everywhere -- zero_ratio=1.0 exceeds the
    # default max_zero_ratio (0.01).
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0.0" b="0" c="0" d="0"/></elevationProfile>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def _write_elevation_spiky_xodr(path: Path) -> None:
    # 12 elevation points alternating 0/100 every 1m (slope=100, threshold is
    # 0.25) -- 11 consecutive pairs, all spiky, above
    # ElevationSmoothnessGate.MAX_SPIKY_SEGMENTS_PER_ROAD (10).
    points = []
    for i in range(12):
        a = 100.0 if i % 2 == 1 else 0.0
        points.append(f'<elevation s="{i}.0" a="{a}" b="0" c="0" d="0"/>')
    elev_xml = "".join(points)
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="12.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="12"><line/></geometry></planView>
    <elevationProfile>{elev_xml}</elevationProfile>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def _write_physics_infeasible_xodr(path: Path) -> None:
    # A driving lane at 0.3m wide -- above lane_width_continuity's
    # near-zero threshold (0.01) but below physics_feasibility's minimum
    # driveable width (1.0), so this isolates physics_feasibility.
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
    <lanes>
      <laneSection s="0">
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0" a="0.3" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def test_run_gates_reports_lane_width_continuity(tmp_path: Path) -> None:
    xodr = tmp_path / "narrow.xodr"
    _write_lane_width_violation_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("lane_width_continuity")
    assert rep is not None
    assert rep["ok"] is False
    assert rep["num_issues"] >= 1
    assert (tmp_path / "out" / "lane_width_continuity.json").is_file()


def test_run_gates_lane_width_continuity_clean(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("lane_width_continuity")
    assert rep is not None
    assert rep["ok"] is True


def test_run_gates_reports_lane_geometry_continuity(tmp_path: Path) -> None:
    xodr = tmp_path / "jump.xodr"
    _write_lane_geometry_violation_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("lane_geometry_continuity")
    assert rep is not None
    assert rep["ok"] is False
    assert rep["n_issues"] >= 1
    assert (tmp_path / "out" / "lane_geometry_continuity.json").is_file()


def test_run_gates_lane_geometry_continuity_clean(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("lane_geometry_continuity")
    assert rep is not None
    assert rep["ok"] is True


def test_run_gates_reports_elevation_missing_and_cliffs(tmp_path: Path) -> None:
    xodr = tmp_path / "flat_missing.xodr"
    _write_elevation_missing_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("elevation_missing_and_cliffs")
    assert rep is not None
    assert rep["ok"] is False
    assert rep["zero_ratio"] > 0.01
    assert (tmp_path / "out" / "elevation_missing_and_cliffs.json").is_file()


def test_run_gates_elevation_missing_and_cliffs_clean(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("elevation_missing_and_cliffs")
    assert rep is not None
    # The clean fixture's single road has a=0 elevation too (flat is a valid
    # baseline), so this gate only fails on the *ratio* threshold with
    # multiple roads -- assert the report exists and is well-formed rather
    # than asserting ok=True, since this fixture alone isn't representative
    # of "clean" for THIS specific gate (see the dedicated clean-map test
    # below using a nonzero elevation baseline).
    assert "zero_ratio" in rep


def test_run_gates_elevation_missing_and_cliffs_passes_with_real_elevation(tmp_path: Path) -> None:
    xodr = tmp_path / "elevated.xodr"
    xodr.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="100.0" b="0" c="0" d="0"/></elevationProfile>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("elevation_missing_and_cliffs")
    assert rep is not None
    assert rep["ok"] is True
    assert rep["zero_ratio"] == 0.0


def test_run_gates_reports_elevation_smoothness(tmp_path: Path) -> None:
    xodr = tmp_path / "spiky.xodr"
    _write_elevation_spiky_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("elevation_smoothness")
    assert rep is not None
    assert rep["ok"] is False
    assert rep["issue_count"] >= 1
    assert (tmp_path / "out" / "elevation_smoothness.json").is_file()


def test_run_gates_elevation_smoothness_clean(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("elevation_smoothness")
    assert rep is not None
    assert rep["ok"] is True
    assert rep["issue_count"] == 0


def test_run_gates_reports_physics_feasibility(tmp_path: Path) -> None:
    xodr = tmp_path / "too_narrow.xodr"
    _write_physics_infeasible_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("physics_feasibility")
    assert rep is not None
    assert rep["ok"] is False
    assert rep["issue_count"] >= 1
    assert (tmp_path / "out" / "physics_feasibility.json").is_file()


def test_run_gates_physics_feasibility_clean(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("physics_feasibility")
    assert rep is not None
    assert rep["ok"] is True
    assert rep["issue_count"] == 0


# ---------------------------------------------------------------------------
# Deep-audit follow-up, round 2 (2026-09-04): semantic_overlap,
# randomness_entropy, collision_mesh -- all 3 self-documented as heuristic/
# diagnostic/non-fatal, so they're wired as soft-info reports (see
# test_map_acceptance.py for the acceptance-side soft-warning-only handling).
# ---------------------------------------------------------------------------


def test_run_gates_reports_semantic_overlap(tmp_path: Path) -> None:
    xodr = tmp_path / "overlap.xodr"
    xodr.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
    <objects>
      <object id="1" type="sidewalk" s="0" t="0" zOffset="0" length="0" width="0" hdg="0"/>
      <object id="2" type="building" s="0" t="0" zOffset="0" length="0" width="0" hdg="0"/>
    </objects>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("semantic_overlap")
    assert rep is not None
    assert rep["ok"] is False
    assert rep["issue_count"] >= 1
    assert (tmp_path / "out" / "semantic_overlap.json").is_file()


def test_run_gates_semantic_overlap_clean(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("semantic_overlap")
    assert rep is not None
    assert rep["ok"] is True


def test_run_gates_reports_low_randomness_entropy(tmp_path: Path) -> None:
    xodr = tmp_path / "grid.xodr"
    xodr.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0.0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
  </road>
  <road id="2" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0.0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("randomness_entropy")
    assert rep is not None
    assert rep["ok"] is False
    assert rep["entropy"] < 0.05
    assert (tmp_path / "out" / "randomness_entropy.json").is_file()


def test_run_gates_reports_collision_mesh_disabled_by_default(tmp_path: Path) -> None:
    """CollisionMeshValidator is off by default (SETTINGS.ENABLE_SHAPELY_GEOMETRY_QA);
    run_gates() must still call it and record a clean, well-formed report."""
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("collision_mesh")
    assert rep is not None
    assert rep["ok"] is True
    assert (tmp_path / "out" / "collision_mesh.json").is_file()


# ---------------------------------------------------------------------------
# Round-3 map-quality improvement pass (2026-09-04): elevation_continuity's
# report was already computed by run_gates() (and written to disk) but the
# line storing it into reports[...] was simply never added -- invisible to
# build_map_acceptance() entirely, not even as a metric. Plus 3 more
# checkers (post_tiling_integrity, carla_import_s, carla_opendrive_compat)
# that exist, are complete, and are CARLA-crash-prevention-class in their
# own docstrings, but were never called by run_gates() either.
# ---------------------------------------------------------------------------


def test_run_gates_reports_elevation_continuity(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("elevation_continuity")
    assert rep is not None
    assert rep["ok"] is True
    assert (tmp_path / "out" / "elevation_continuity.json").is_file()


def test_run_gates_reports_post_tiling_integrity(tmp_path: Path) -> None:
    xodr = tmp_path / "dup_ids.xodr"
    xodr.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
  </road>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="100" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("post_tiling_integrity")
    assert rep is not None
    assert rep["ok"] is False
    assert len(rep["issues"]) >= 1
    assert (tmp_path / "out" / "post_tiling_integrity.json").is_file()


def test_run_gates_post_tiling_integrity_clean(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("post_tiling_integrity")
    assert rep is not None
    assert rep["ok"] is True


def test_run_gates_reports_carla_import_s_issues(tmp_path: Path) -> None:
    xodr = tmp_path / "negative_s.xodr"
    xodr.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="-5" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("carla_import_s")
    assert rep is not None
    assert rep["ok"] is False
    assert rep["issue_count"] >= 1
    assert (tmp_path / "out" / "carla_import_s.json").is_file()


def test_run_gates_carla_import_s_clean(tmp_path: Path) -> None:
    xodr = tmp_path / "clean.xodr"
    _write_clean_xodr(xodr)

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("carla_import_s")
    assert rep is not None
    assert rep["ok"] is True
    assert rep["issue_count"] == 0


def test_run_gates_reports_carla_opendrive_compat_issues(tmp_path: Path) -> None:
    xodr = tmp_path / "no_center_lane.xodr"
    xodr.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
    <lanes>
      <laneSection s="0">
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0" a="3.5" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("carla_opendrive_compat")
    assert rep is not None
    assert rep["ok"] is False
    assert rep["issue_count"] >= 1
    assert (tmp_path / "out" / "carla_opendrive_compat.json").is_file()


def test_run_gates_carla_opendrive_compat_clean(tmp_path: Path) -> None:
    # _write_clean_xodr() is "clean" for the other gates but has no <header>
    # or <center> lane -- StrictCarlaOpendriveGate is the only wired gate
    # that checks those, so it needs its own fully-compliant fixture.
    xodr = tmp_path / "clean.xodr"
    xodr.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="" version="1.00" date="" north="0" south="0" east="0" west="0">
    <geoReference><![CDATA[+proj=utm +zone=32 +datum=WGS84]]></geoReference>
    <offset x="0" y="0" z="0" hdg="0"/>
  </header>
  <road id="1" length="10.0" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
    <lanes>
      <laneSection s="0">
        <center>
          <lane id="0" type="none" level="false"/>
        </center>
        <right>
          <lane id="-1" type="driving" level="false">
            <width sOffset="0" a="3.5" b="0" c="0" d="0"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )

    reports = run_gates(xodr, tmp_path / "out", dem=None)

    rep = reports.get("carla_opendrive_compat")
    assert rep is not None
    assert rep["ok"] is True
    assert rep["issue_count"] == 0
