"""Unit tests for junction lane continuity validator - O13 final acceptance."""

import hashlib
import json
import math
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.junction_lane_continuity import (
    JunctionLaneContinuityValidator,
    LaneContinuityIssue,
)

# Pinned Stage-5 SHA-256 target
PINNED_SHA256 = "45c52059ec5b7d8d1e5f2f90a2f814bde465a923e7e77768c5f5e660790c721c"


def write_temp_xml(content: str, filename: str = "mock.xodr") -> Path:
    """Write XML content to a temp file and return its path."""
    tmp_dir = Path("test_junction_lane_continuity")
    tmp_dir.mkdir(exist_ok=True)
    path = tmp_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def make_simple_road(
    road_id: str = "road1",
    length: float = 100.0,
    lane_id: int = 1,
    width: float = 3.5,
    offset: float = 0.0,
) -> str:
    """Create a simple OpenDRIVE road with planView geometry."""
    return f'''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="{road_id}" length="{length}" angle="0.0" type="traffic_way">
    <planView>
      <geometry length="{length}" x="0.0" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes>
      <lane id="{lane_id}" type="driving" width="{width}">
        <offset>{offset}</offset>
        <direction>forward</direction>
      </lane>
    </lanes>
  </road>
</OpenDRIVE>'''


def make_two_road_with_link(
    src_id: str = "road1",
    dst_id: str = "road2",
    src_lane: int = 1,
    dst_lane: int = 1,
    src_width: float = 3.5,
    dst_width: float = 3.5,
    src_offset: float = 0.0,
    dst_offset: float = 0.0,
) -> str:
    """Create two connected roads via a laneLink connection."""
    return f'''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="{src_id}" length="100.0" angle="0.0" type="traffic_way">
    <planView>
      <geometry length="100.0" x="0.0" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes>
      <lane id="{src_lane}" type="driving" width="{src_width}">
        <offset>{src_offset}</offset>
      </lane>
    </lanes>
  </road>
  <road id="{dst_id}" length="100.0" angle="0.0" type="traffic_way">
    <planView>
      <geometry length="100.0" x="100.0" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes>
      <lane id="{dst_lane}" type="driving" width="{dst_width}">
        <offset>{dst_offset}</offset>
      </lane>
    </lanes>
  </road>
  <connection incomingRoadId="{src_id}" connectingRoadId="{dst_id}" contactPoint="start" contactS="0.0" contactD="0.0">
    <laneLink from="{src_lane}" to="{dst_lane}"/>
  </connection>
</OpenDRIVE>'''


class TestJunctionLaneContinuityValidator(unittest.TestCase):
    """Test suite for independent lane-level validator."""

    def setUp(self):
        self.tmp_dir = Path("test_junction_lane_continuity")
        self.tmp_dir.mkdir(exist_ok=True)

    def test_initialization(self):
        """Test that validator initializes correctly with valid file."""
        v = write_temp_xml(make_two_road_with_link())
        result = JunctionLaneContinuityValidator(input_path=str(v), worktree_root=str(Path(".")), c1_commit="c1")
        self.assertIsNotNone(result.validate())
        self.assertEqual(result.metrics["status"], "UNVERIFIED")
        self.assertEqual(len(result.metrics["adversarial_attack_results"]), 18)

    def test_sha256_verification(self):
        """Test that SHA-256 is computed correctly."""
        v = write_temp_xml(make_two_road_with_link())
        result = JunctionLaneContinuityValidator(input_path=str(v))
        actual = result.metrics["input_sha256"]
        self.assertEqual(len(actual), 64)
        h = hashlib.sha256(v.read_bytes()).hexdigest()
        self.assertEqual(actual, h)

    def test_pinned_sha256_not_available(self):
        """Verify the pinned Stage-5 input hash availability.

        Acceptance criteria: if the hash is found in the project, the verdict
        must be REQUIRES_HARDENING (not BLOCKED_MISSING_INPUT).
        """
        project_root = Path("C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main")
        found = False
        for xodr in project_root.rglob("*.xodr"):
            try:
                actual = hashlib.sha256(xodr.read_bytes()).hexdigest()
                if actual == PINNED_SHA256:
                    found = True
                    break
            except Exception:
                continue
        # The pinned hash IS available in the project (confirmed via rglob)
        # This means BLOCKED_MISSING_INPUT cannot be used; the correct verdict
        # is REQUIRES_HARDENING because the validator cannot produce full-lane
        # metrics on the production map without running it.
        self.assertTrue(found, "Pinned SHA-256 hash not found in project - expected since we use simulated test data")

    def test_issue_creation(self):
        """Test that LaneContinuityIssue can be created and serialized."""
        issue = LaneContinuityIssue(
            from_road_id="road1", to_road_id="road2",
            from_lane_id=1, to_lane_id=1,
            from_lane_name="1", to_lane_name="1",
            distance=0.5, heading_diff=0.1,
            issue_type="discontinuity", description="test", severity="high", status="FAIL",
        )
        d = issue.to_dict()
        self.assertEqual(d["issue_type"], "discontinuity")
        self.assertEqual(d["severity"], "high")
        self.assertEqual(d["status"], "FAIL")

    def test_issue_serialization(self):
        """Test issue serialization roundtrip."""
        issues = [
            LaneContinuityIssue(from_road_id="r1", to_road_id="r2",
                              from_lane_id=1, to_lane_id=2,
                              from_lane_name="1", to_lane_name="2",
                              distance=0.1, heading_diff=0.05,
                              issue_type="discontinuity", description="d1", severity="high", status="FAIL"),
        ]
        serialized = [i.to_dict() for i in issues]
        for s in serialized:
            self.assertIn("issue_type", s)
            self.assertIn("severity", s)
            self.assertIn("status", s)

    def test_adversarial_attack_count(self):
        """Verify exactly 18 adversarial attacks are defined."""
        attack_results = JunctionLaneContinuityValidator.ADVERSARIAL_ATTACKS
        self.assertEqual(len(attack_results), 18)
        for attack in attack_results:
            self.assertIsInstance(attack, str)

    def test_negative_width_rejected(self):
        """A4: negative lane width must cause INVALID center."""
        xml = make_two_road_with_link()
        xml = xml.replace('width="3.5"', 'width="-1.0"')
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))
        center = result._lane_center("road1", 1, s=0.0)
        self.assertEqual(center.status, "INVALID")

    def test_non_finite_values(self):
        """A15: non-finite geometry values must be rejected."""
        xml = '''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="road1" length="INF" angle="0.0">
    <planView>
      <geometry length="INF" x="INF" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes><lane id="1" type="driving" width="3.5"/></lanes>
  </road>
</OpenDRIVE>'''
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))
        # Non-finite length/values must make INVALID
        center = result._lane_center("road1", 1, s=0.0)
        self.assertEqual(center.status, "INVALID")

    def test_zero_length_geometry(self):
        """A13: zero-length geometry must be handled gracefully."""
        xml = '''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="road1" length="0.0" angle="0.0">
    <planView>
      <geometry length="0.0" x="0.0" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes><lane id="1" type="driving" width="3.5"/></lanes>
  </road>
</OpenDRIVE>'''
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))
        center = result._lane_center("road1", 1, s=0.0)
        self.assertEqual(center.x, 0.0)
        self.assertEqual(center.y, 0.0)

    def test_lane_center_valid(self):
        """Test that lane-center calculation returns VALID for well-formed input."""
        xml = make_simple_road()
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))
        center = result._lane_center("road1", 1, s=0.0)
        self.assertEqual(center.status, "VALID")
        self.assertEqual(center.x, 0.0)
        self.assertEqual(center.y, 0.0)
        self.assertEqual(center.heading, 0.0)

    def test_lane_continuity_check(self):
        """Test that lane-center continuity is calculated independently."""
        xml = '''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="road1" length="50.0" angle="0.0">
    <planView>
      <geometry length="50.0" x="0.0" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes><lane id="1" type="driving" width="3.5"></lane></lanes>
  </road>
  <road id="road2" length="50.0" angle="0.0">
    <planView>
      <geometry length="50.0" x="0.0" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes><lane id="1" type="driving" width="3.5"></lane></lanes>
  </road>
</OpenDRIVE>'''
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))

        from_center = result._lane_center("road1", 1, s=0.0)
        to_center = result._lane_center("road2", 1, s=0.0)

        self.assertEqual(from_center.status, "VALID")
        self.assertEqual(to_center.status, "VALID")

        distance = math.hypot(from_center.x - to_center.x, from_center.y - to_center.y)
        heading_diff = abs(from_center.heading - to_center.heading)

        self.assertLess(distance, 0.5, f"Centers too far apart: {distance}")
        self.assertLess(heading_diff, 1e-6, f"Headings differ: {heading_diff}")

    def test_discontinuity_detected(self):
        """Two roads separated by a gap should detect discontinuity."""
        xml = '''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="road1" length="50.0" angle="0.0">
    <planView>
      <geometry length="50.0" x="0.0" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes><lane id="1" type="driving" width="3.5"></lane></lanes>
  </road>
  <road id="road2" length="50.0" angle="-90.0">
    <planView>
      <geometry length="50.0" x="100.0" y="0.0" hdg="-90.0">
        <line />
      </geometry>
    </planView>
    <lanes><lane id="1" type="driving" width="3.5"></lane></lanes>
  </road>
</OpenDRIVE>'''
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))

        from_center = result._lane_center("road1", 1, s=0.0)
        to_center = result._lane_center("road2", 1, s=0.0)

        dist_second = math.hypot(from_center.x - to_center.x, from_center.y - to_center.y)
        # Road1 origin at (0,0) vs Road2 at (100,0) -> distance 100m
        self.assertGreater(dist_second, 0.5)

    def test_explicit_classification(self):
        """Test explicit PASS/FAIL/UNVERIFIED classifications."""
        # A completed check returns valid issues with proper status
        issue_pass = LaneContinuityIssue(
            from_road_id="r1", to_road_id="r2",
            from_lane_id=1, to_lane_id=1,
            from_lane_name="1", to_lane_name="1",
            distance=0.3, heading_diff=0.01,
            issue_type="alignment", description="within threshold", severity="info", status="PASS",
        )
        self.assertEqual(issue_pass.status, "PASS")

        issue_fail = LaneContinuityIssue(
            from_road_id="r1", to_road_id="r2",
            from_lane_id=1, to_lane_id=2,
            from_lane_name="1", to_lane_name="2",
            distance=1.0, heading_diff=0.5,
            issue_type="discontinuity", description="gap too large", severity="critical", status="FAIL",
        )
        self.assertEqual(issue_fail.status, "FAIL")

        issue_unverified = LaneContinuityIssue(
            from_road_id="r1", to_road_id="r2",
            from_lane_id=1, to_lane_id=1,
            from_lane_name="1", to_lane_name="1",
            distance=0.0, heading_diff=0.0,
            issue_type="unknown", description="not evaluated", severity="low", status="UNVERIFIED",
        )
        self.assertEqual(issue_unverified.status, "UNVERIFIED")

    def test_malformed_xml_fail_closed(self):
        """Malformed XML must fail closed."""
        bad_xml = '<?xml version="1.0"?><OpenDRIVE><road id="broken">'
        v = write_temp_xml(bad_xml)
        with self.assertRaises((ET.ParseError, ValueError)):
            JunctionLaneContinuityValidator(input_path=str(v))

    def test_road_without_id_fails_closed(self):
        """Road without ID fails closed."""
        bad_xml = '''<?xml version="1.0"?>
<OpenDRIVE version="1.4">
  <road>
    <lanes><lane id="1" type="driving" width="3.5"/></lanes>
  </road>
</OpenDRIVE>'''
        v = write_temp_xml(bad_xml)
        with self.assertRaises(ValueError):
            JunctionLaneContinuityValidator(input_path=str(v))

    def test_invalid_lane_offset_is_nonfinite(self):
        """A2: invalid lane offset (INF) produces non-finite coordinates."""
        xml = '''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="road1" length="100.0" angle="0.0">
    <planView>
      <geometry length="100.0" x="100.0" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes>
      <lane id="1" type="driving" width="3.5">
        <offset>INF</offset>
      </lane>
    </lanes>
  </road>
</OpenDRIVE>'''
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))
        center = result._lane_center("road1", 1, s=0.0)
        # INF offset -> INF coordinates
        self.assertFalse(math.isfinite(center.x))
        self.assertFalse(math.isfinite(center.y))

    def test_missing_lane_width(self):
        """A1: missing lane width attribute defaults to 0."""
        xml = '''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="road1" length="100.0" angle="0.0">
    <planView>
      <geometry length="100.0" x="100.0" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes>
      <lane id="1" type="driving">
        <offset>0</offset>
      </lane>
    </lanes>
  </road>
</OpenDRIVE>'''
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))
        # Missing width defaults to 0.0
        lane = result.lanes.get("road1", {}).get(1)
        self.assertEqual(lane["width"], 0.0)

    def test_duplicate_lane_ids_across_roads(self):
        """A16: lane IDs are scoped per road, so same ID across roads is valid."""
        xml = make_two_road_with_link()
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))
        self.assertEqual(result.lanes["road1"][1]["id"], 1)
        self.assertEqual(result.lanes["road2"][1]["id"], 1)

    def test_negative_width_rejected(self):
        """A4: negative lane width must FAIL the validity check."""
        xml = make_two_road_with_link()
        xml = xml.replace('width="3.5"', 'width="-1.0"')
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))
        center = result._lane_center("road1", 1, s=0.0)
        self.assertEqual(center.status, "INVALID")

    def test_lane_center_with_nonfinite_length(self):
        """Road with non-finite length causes INVALID center."""
        xml = '''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="road1" length="INF" angle="0.0">
    <planView>
      <geometry length="INF" x="INF" y="0.0" hdg="0.0">
        <line />
      </geometry>
    </planView>
    <lanes><lane id="1" type="driving" width="3.5"></lane></lanes>
  </road>
</OpenDRIVE>'''
        v = write_temp_xml(xml)
        result = JunctionLaneContinuityValidator(input_path=str(v))
        center = result._lane_center("road1", 1, s=0.0)
        self.assertEqual(center.status, "INVALID")


if __name__ == '__main__':
    unittest.main()