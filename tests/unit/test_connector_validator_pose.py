import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.topology.junction_connector_rebuild import ConnectorValidator, Pose


def _road(with_lanes=True):
    lanes = (
        '<lanes><laneSection s="0"><right><lane id="-1" type="driving">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'
        '</right></laneSection></lanes>'
        if with_lanes else ""
    )
    return ET.fromstring(
        '<road id="10" length="10"><planView><geometry s="0" x="0" y="0" '
        'hdg="0" length="10"><line/></geometry></planView>' + lanes + '</road>'
    )


def test_validator_requires_valid_lane_section():
    assert not ConnectorValidator(_road(False)).validate()
    assert ConnectorValidator(_road()).validate()


def test_validator_checks_both_attachment_position_and_heading():
    road = _road()
    assert ConnectorValidator(
        road,
        attach_pose=Pose(0, 0, 0),
        opposite_pose=Pose(10, 0, 0),
    ).validate()
    assert not ConnectorValidator(
        road,
        attach_pose=Pose(0, 0, math.pi / 2),
        opposite_pose=Pose(10, 0, 0),
    ).validate()
    assert not ConnectorValidator(
        road,
        attach_pose=Pose(0.2, 0, 0),
        opposite_pose=Pose(10, 0, 0),
    ).validate()
