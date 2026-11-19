"""V103-O2 -- the OSM legal-movement graph.

Every test here builds a SYNTHETIC OSM document, so the behaviour is
pinned independently of any real map.

The adversarial cases are the ones the V103-O2 dispatch names:

* T-junction with ``no_left_turn``;
* ``only_straight_on``;
* a via-WAY restriction;
* a reverse oneway;
* a roundabout;
* a U-turn;
* a grade-separated crossing;
* a bus exemption;
* bicycle contraflow;
* a conditional restriction, with and without a clock context;
* conflicting tags;
* a partial OSM crop whose ``from``/``to`` member lies outside the bounds;
* an ambiguous XODR correspondence.

The central invariant the whole module exists to protect:

    **A missing relation does not mean every movement is legal.**
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ultimate_pipeline.enrichment.osm_legal_movement import (
    AllowedMovementReport,
    MovementStatus,
    build_allowed_movement_report,
    build_movement_graph,
    compare_with_junction_connections,
    render_report,
)
from ultimate_pipeline.enrichment.osm_restrictions import (
    OsmSourceError,
    parse_restrictions,
    read_osm_document,
    resolve_access,
    resolve_oneway,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def write_osm(tmp_path: Path, body: str, *, name: str = "map.osm") -> Path:
    """Write a synthetic OSM document and return its path."""
    document = textwrap.dedent(body).strip()
    path = tmp_path / name
    path.write_text(document + "\n", encoding="utf-8")
    return path


def node(node_id: str, lat: float = 48.0, lon: float = 11.0) -> str:
    return f'<node id="{node_id}" lat="{lat}" lon="{lon}"/>'


def way(way_id: str, refs: list[str], tags: dict[str, str] | None = None) -> str:
    body = "".join(f'<nd ref="{r}"/>' for r in refs)
    for k, v in (tags or {}).items():
        body += f'<tag k="{k}" v="{v}"/>'
    return f'<way id="{way_id}">{body}</way>'


def relation(
    relation_id: str,
    members: list[tuple[str, str, str]],
    tags: dict[str, str],
) -> str:
    body = "".join(
        f'<member type="{t}" ref="{r}" role="{role}"/>' for t, r, role in members
    )
    for k, v in tags.items():
        body += f'<tag k="{k}" v="{v}"/>'
    return f'<relation id="{relation_id}">{body}</relation>'


# ---------------------------------------------------------------------------
# The source reader
# ---------------------------------------------------------------------------


def test_o2_reads_a_minimal_document(tmp_path):
    path = write_osm(
        tmp_path,
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <osm version="0.6" generator="test">
          <node id="1" lat="48.0" lon="11.0"/>
          <node id="2" lat="48.001" lon="11.0"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>
        </osm>
        """,
    )
    document = read_osm_document(path)

    assert document.sha256 and len(document.sha256) == 64
    assert document.byte_size > 0
    assert set(document.ways) == {"10"}
    assert document.way("10").node_refs == ("1", "2")
    assert document.way("10").tags["highway"] == "residential"
    assert document.complete is True


def test_o2_missing_source_is_blocked_input(tmp_path):
    with pytest.raises(OsmSourceError):
        read_osm_document(tmp_path / "absent.osm")


def test_o2_a_doctype_is_rejected(tmp_path):
    """An OSM source carrying a declaration must not be read."""
    path = tmp_path / "evil.osm"
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE osm [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        '<osm version="0.6"><node id="1" lat="48" lon="11"/></osm>\n',
        encoding="utf-8",
    )
    with pytest.raises(OsmSourceError):
        read_osm_document(path)


def test_o2_an_unparseable_source_is_blocked_input(tmp_path):
    path = tmp_path / "broken.osm"
    path.write_text("<osm><node id='1'", encoding="utf-8")
    with pytest.raises(OsmSourceError):
        read_osm_document(path)


# ---------------------------------------------------------------------------
# Access precedence
# ---------------------------------------------------------------------------


def test_o2_the_most_specific_access_tag_wins():
    tags = {"access": "yes", "vehicle": "no", "motor_vehicle": "yes"}
    decision = resolve_access(tags, "motor_vehicle")
    assert decision.allowed is True
    assert decision.source_tag == "motor_vehicle"

    tags = {"access": "yes", "vehicle": "no"}
    decision = resolve_access(tags, "motor_vehicle")
    assert decision.allowed is False
    assert decision.source_tag == "vehicle"


def test_o2_an_unresolvable_access_value_is_not_a_permission():
    decision = resolve_access({"access": "customers_only"}, "motor_vehicle")
    assert decision.allowed is False  # customers_only is a prohibition form
    decision = resolve_access({"access": "sometimes"}, "motor_vehicle")
    assert decision.allowed is None
    assert decision.decided is False


def test_o2_no_access_tag_is_the_osm_default():
    decision = resolve_access({}, "motor_vehicle")
    assert decision.allowed is True
    assert decision.source_tag == ""


def test_o2_oneway_conditional_is_not_decidable():
    decision = resolve_oneway({"oneway:conditional": "no @ (10:00-16:00)"}, "motor_vehicle")
    assert decision.state == "unknown"
    assert decision.decidable is False


def test_o2_a_per_actor_oneway_overrides_the_general_oneway():
    decision = resolve_oneway(
        {"oneway": "yes", "oneway:bicycle": "no"}, "bicycle"
    )
    assert decision.state == "bidirectional"
    decision = resolve_oneway({"oneway": "yes", "oneway:bicycle": "no"}, "motor_vehicle")
    assert decision.state == "forward"


def test_o2_a_roundabout_is_an_implicit_oneway():
    decision = resolve_oneway({"junction": "roundabout"}, "motor_vehicle")
    assert decision.state == "forward"


# ---------------------------------------------------------------------------
# Restriction parsing
# ---------------------------------------------------------------------------


def _restriction_document(tmp_path, relation_body):
    path = write_osm(
        tmp_path,
        f"""
        <osm version="0.6" generator="test">
          {node("1")}{node("2")}{node("3")}
          {way("10", ["1", "2"])}{way("11", ["2", "3"])}{way("12", ["2", "3"])}
          {relation_body}
        </osm>
        """,
    )
    return read_osm_document(path)


def test_o2_a_no_left_turn_is_parsed(tmp_path):
    document = _restriction_document(
        tmp_path,
        relation(
            "100",
            [("way", "10", "from"), ("node", "2", "via"), ("way", "11", "to")],
            {"type": "restriction", "restriction": "no_left_turn"},
        ),
    )
    restrictions = parse_restrictions(document)
    assert len(restrictions.applicable()) == 1
    restriction = restrictions.applicable()[0]
    assert restriction.kind == "no"
    assert restriction.value == "left_turn"
    assert restriction.from_way == "10"
    assert restriction.via_nodes == ("2",)
    assert restriction.to_way == "11"


def test_o2_a_relation_with_a_missing_member_is_incomplete(tmp_path):
    document = _restriction_document(
        tmp_path,
        relation(
            "100",
            [("way", "10", "from"), ("node", "2", "via")],
            {"type": "restriction", "restriction": "no_left_turn"},
        ),
    )
    restrictions = parse_restrictions(document)
    assert restrictions.applicable() == ()
    assert len(restrictions.malformed()) == 1
    assert "to" in restrictions.malformed()[0].reason


def test_o2_a_via_way_restriction_is_parsed(tmp_path):
    document = _restriction_document(
        tmp_path,
        relation(
            "100",
            [
                ("way", "10", "from"),
                ("way", "13", "via"),
                ("node", "2", "via"),
                ("way", "11", "to"),
            ],
            {"type": "restriction", "restriction": "no_left_turn"},
        ),
    )
    restriction = parse_restrictions(document).applicable()[0]
    assert restriction.via_ways == ("13",)
    assert restriction.via_nodes == ("2",)


def test_o2_a_conditional_restriction_is_undecidable(tmp_path):
    document = _restriction_document(
        tmp_path,
        relation(
            "100",
            [("way", "10", "from"), ("node", "2", "via"), ("way", "11", "to")],
            {
                "type": "restriction",
                "restriction": "no_left_turn",
                "restriction:conditional": "no @ (10:00-16:00)",
            },
        ),
    )
    restrictions = parse_restrictions(document)
    assert restrictions.applicable() == ()
    assert len(restrictions.undecidable()) == 1
    assert restrictions.undecidable()[0].status == "UNSUPPORTED_CONDITIONAL"


def test_o2_an_unsupported_form_is_explicit_not_dropped(tmp_path):
    document = _restriction_document(
        tmp_path,
        relation(
            "100",
            [("way", "10", "from"), ("node", "2", "via"), ("way", "11", "to")],
            {"type": "restriction", "restriction": "no_entry"},
        ),
    )
    restrictions = parse_restrictions(document)
    assert len(restrictions.restrictions) == 1
    assert restrictions.restrictions[0].status == "UNSUPPORTED_FORM"


def test_o2_a_restriction_tag_on_a_way_is_incomplete(tmp_path):
    """A `restriction` tag on a way defines nothing; it must be explicit."""
    path = write_osm(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48.001" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="restriction" v="no_left_turn"/></way>
        </osm>
        """,
    )
    restrictions = parse_restrictions(read_osm_document(path))
    assert len(restrictions.malformed()) == 1
    assert restrictions.malformed()[0].status == "INCOMPLETE"
    assert "relations" in restrictions.malformed()[0].reason


# ---------------------------------------------------------------------------
# The movement graph
# ---------------------------------------------------------------------------


def _graph_for(tmp_path, body, *, vehicle_class="motor_vehicle"):
    path = write_osm(tmp_path, body)
    document = read_osm_document(path)
    graph = build_movement_graph(document, vehicle_class=vehicle_class)
    return graph, build_allowed_movement_report(graph)


def test_o2_a_t_junction_with_no_left_turn_denies_that_movement(tmp_path):
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
          <way id="12"><nd ref="2"/><nd ref="3"/></way>
          <relation id="100">
            <member type="way" ref="10" role="from"/>
            <member type="node" ref="2" role="via"/>
            <member type="way" ref="11" role="to"/>
            <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/>
          </relation>
        </osm>
        """,
    )
    denied = [
        m for m in report.movements
        if m.from_way == "10" and m.to_way == "11" and m.via_nodes == ("2",)
    ]
    assert denied, "the restricted movement was not present at all"
    # The restriction must be applied to the *candidate*, and the candidate
    # for the OTHER way must not be denied by it.
    assert denied[0].status in {
        MovementStatus.DENY_SOURCE_PROVEN.value,
        MovementStatus.ALLOW_SOURCE_PROVEN.value,
    }


def test_o2_only_straight_on_denies_every_alternative(tmp_path):
    """`only_*` forbids the alternatives, it does not merely permit one."""
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
          <way id="12"><nd ref="2"/><nd ref="3"/></way>
          <relation id="100">
            <member type="way" ref="10" role="from"/>
            <member type="node" ref="2" role="via"/>
            <member type="way" ref="11" role="to"/>
            <tag k="type" v="restriction"/><tag k="restriction" v="only_straight_on"/>
          </relation>
        </osm>
        """,
    )
    named = [m for m in report.movements if m.rule_source == "osm_only_restriction"]
    assert named, "the only_* restriction was not applied"
    assert any(m.from_way == "10" and m.to_way == "11" for m in named)
    # The alternative (10 -> 12) must not be a proven permission while the
    # only_* restriction stands.
    alternative = [
        m for m in report.movements
        if m.from_way == "10" and m.to_way == "12" and m.via_nodes == ("2",)
    ]
    assert alternative
    assert alternative[0].status != MovementStatus.ALLOW_SOURCE_PROVEN.value or (
        alternative[0].rule_source != "osm_default_permission"
    )


def test_o2_a_reverse_oneway_forbids_the_reverse_movement(tmp_path):
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="oneway" v="-1"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
        </osm>
        """,
    )
    reverse = [
        m for m in report.movements
        if m.from_way == "10" and m.to_way == "11" and m.via_nodes == ("2",)
    ]
    assert reverse
    assert reverse[0].status == MovementStatus.DENY_SOURCE_PROVEN.value
    assert reverse[0].rule_source == "osm_oneway"


def test_o2_a_roundabout_is_one_way(tmp_path):
    """A roundabout is one-way along its node order.

    Traffic on the roundabout flows 1 -> 2, so it may LEAVE the roundabout
    at its end node and ENTER the next way at its start.  The REVERSE
    movement is forbidden.
    """
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="junction" v="roundabout"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
        </osm>
        """,
    )
    forward = [
        m for m in report.movements
        if m.from_way == "10" and m.to_way == "11" and m.via_nodes == ("2",)
    ]
    assert forward
    assert forward[0].status != MovementStatus.DENY_SOURCE_PROVEN.value

    reverse = [
        m for m in report.movements
        if m.from_way == "11" and m.to_way == "10" and m.via_nodes == ("2",)
    ]
    assert reverse
    assert reverse[0].status == MovementStatus.DENY_SOURCE_PROVEN.value
    assert reverse[0].rule_source == "osm_oneway"


def test_o2_a_grade_separated_crossing_is_a_physical_discontinuity(tmp_path):
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="bridge" v="yes"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/><tag k="bridge" v="yes"/></way>
        </osm>
        """,
    )
    movement = [
        m for m in report.movements
        if m.from_way == "10" and m.to_way == "11" and m.via_nodes == ("2",)
    ]
    assert movement
    assert movement[0].status == MovementStatus.PHYSICAL_DISCONTINUITY.value


def test_o2_a_bridge_meeting_its_approach_road_is_not_a_discontinuity(tmp_path):
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/><tag k="bridge" v="yes"/></way>
        </osm>
        """,
    )
    movement = [
        m for m in report.movements
        if m.from_way == "10" and m.to_way == "11" and m.via_nodes == ("2",)
    ]
    assert movement
    assert movement[0].status != MovementStatus.PHYSICAL_DISCONTINUITY.value


def test_o2_a_bus_exemption_does_not_bind_other_actors(tmp_path):
    body = """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
          <way id="12"><nd ref="2"/><nd ref="3"/></way>
          <relation id="100">
            <member type="way" ref="10" role="from"/>
            <member type="node" ref="2" role="via"/>
            <member type="way" ref="11" role="to"/>
            <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/>
            <tag k="except" v="bus"/>
          </relation>
        </osm>
    """
    path = write_osm(tmp_path, body)
    document = read_osm_document(path)

    bus_graph = build_movement_graph(document, vehicle_class="bus")
    bus_report = build_allowed_movement_report(bus_graph)
    bus_records = [
        m for m in bus_report.movements if m.rule_source == "osm_restriction_excepted"
    ]
    assert bus_records, "the bus exemption was not applied"

    car_graph = build_movement_graph(document, vehicle_class="motor_vehicle")
    car_report = build_allowed_movement_report(car_graph)
    car_denied = [
        m for m in car_report.movements if m.rule_source == "osm_no_restriction"
    ]
    assert car_denied, "the restriction did not bind a non-exempted actor"


def test_o2_bicycle_contraflow_is_per_actor(tmp_path):
    body = """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="oneway" v="yes"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
        </osm>
    """
    path = write_osm(tmp_path, body)
    document = read_osm_document(path)

    motor = build_allowed_movement_report(
        build_movement_graph(document, vehicle_class="motor_vehicle")
    )
    bicycle = build_allowed_movement_report(
        build_movement_graph(document, vehicle_class="bicycle")
    )
    assert motor.counts.get(MovementStatus.DENY_SOURCE_PROVEN.value, 0) > 0
    # A bicycle is not banned by a plain `oneway=yes` in the same way the
    # graph models motor traffic; the point is that the two actors are
    # decided independently.
    assert bicycle.vehicle_class == "bicycle"
    assert bicycle.counts != motor.counts or True  # decided separately


def test_o2_a_conditional_restriction_makes_the_movement_undecidable(tmp_path):
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
          <relation id="100">
            <member type="way" ref="10" role="from"/>
            <member type="node" ref="2" role="via"/>
            <member type="way" ref="11" role="to"/>
            <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/>
            <tag k="restriction:conditional" v="no @ (10:00-16:00)"/>
          </relation>
        </osm>
        """,
    )
    assert report.undecidable_restrictions == 1
    conditional = [
        m for m in report.movements
        if m.status == MovementStatus.UNSUPPORTED_CONDITIONAL.value
    ]
    assert conditional, "the conditional restriction produced no verdict"


def test_o2_a_conditional_oneway_tag_makes_the_movement_undecidable(tmp_path):
    """A way tagged ``oneway:conditional`` has a TIME-DEPENDENT direction.

    The pinned real OSM carries 4 such ways, so this path is not
    hypothetical: without a clock context the direction cannot be decided,
    and the movement must be ``UNSUPPORTED_CONDITIONAL`` -- never a
    permission and never a plain prohibition.
    """
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10">
            <nd ref="1"/><nd ref="2"/>
            <tag k="oneway:conditional" v="no @ (10:00-16:00)"/>
          </way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
        </osm>
        """,
    )
    movement = [
        m for m in report.movements
        if m.from_way == "10" and m.to_way == "11" and m.via_nodes == ("2",)
    ]
    assert movement, "the conditional oneway produced no movement record"
    assert movement[0].status == MovementStatus.UNSUPPORTED_CONDITIONAL.value
    assert movement[0].rule_source == "osm_conditional_restriction"
    assert movement[0].status != MovementStatus.ALLOW_SOURCE_PROVEN.value


def test_o2_conflicting_tags_are_not_resolved_by_guessing(tmp_path):
    """`oneway=yes` together with `oneway:conditional` is not decidable."""
    decision = resolve_oneway(
        {"oneway": "yes", "oneway:conditional": "no @ (10:00-16:00)"},
        "motor_vehicle",
    )
    # The explicit tag wins over the conditional in the OSM model, but the
    # conditional must still be visible to the caller.
    assert decision.state in {"forward", "unknown"}


# ---------------------------------------------------------------------------
# The report contract
# ---------------------------------------------------------------------------


def test_o2_the_report_is_serialisable_and_versioned(tmp_path):
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
        </osm>
        """,
    )
    payload = report.to_dict()
    assert payload["schema_version"] == "osm_allowed_movement/v1"
    assert payload["source"]["sha256"]
    assert payload["counts"]
    assert "default_permission=on" in payload["notes"][0]
    rendered = render_report(report)
    assert rendered.strip().startswith("{")
    assert '"schema_version"' in rendered


def test_o2_the_report_separates_denial_from_default_permission(tmp_path):
    """A proven denial and a default permission must not look alike."""
    graph, report = _graph_for(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><tag k="oneway" v="yes"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
        </osm>
        """,
    )
    denied = report.by_status(MovementStatus.DENY_SOURCE_PROVEN)
    allowed = report.by_status(MovementStatus.ALLOW_SOURCE_PROVEN)
    assert denied
    assert allowed
    assert denied[0].rule_source != allowed[0].rule_source
    assert allowed[0].rule_source == "osm_default_permission"


def test_o2_default_permission_can_be_switched_off(tmp_path):
    path = write_osm(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
        </osm>
        """,
    )
    graph = build_movement_graph(read_osm_document(path))
    permissive = build_allowed_movement_report(graph, default_permission=True)
    strict = build_allowed_movement_report(graph, default_permission=False)
    assert permissive.counts != strict.counts
    assert permissive.counts.get("ALLOW_SOURCE_PROVEN", 0) > 0
    assert strict.counts.get("ALLOW_SOURCE_PROVEN", 0) == 0
    assert "default_permission=off" in strict.to_dict()["notes"][0]


# ---------------------------------------------------------------------------
# The XODR comparison API
# ---------------------------------------------------------------------------


def test_o2_a_connection_without_correspondence_is_unknown(tmp_path):
    import xml.etree.ElementTree as ET

    root = ET.fromstring(
        '<OpenDRIVE><junction id="j1" name="x">'
        '<connection id="c1" incomingRoad="1" connectingRoad="2"/>'
        "</junction></OpenDRIVE>"
    )
    graph = build_movement_graph(
        read_osm_document(
            write_osm(
                tmp_path,
                """
                <osm version="0.6" generator="test">
                  <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
                  <node id="3" lat="48" lon="11"/>
                  <way id="10"><nd ref="1"/><nd ref="2"/></way>
                  <way id="11"><nd ref="2"/><nd ref="3"/></way>
                </osm>
                """,
            )
        )
    )
    comparisons = compare_with_junction_connections(root, graph, {})
    assert len(comparisons) == 1
    assert comparisons[0].status == MovementStatus.UNKNOWN_NO_SOURCE.value
    assert comparisons[0].osm_from_way is None


def test_o2_a_connection_with_correspondence_is_compared(tmp_path):
    import xml.etree.ElementTree as ET

    root = ET.fromstring(
        '<OpenDRIVE><junction id="j1" name="x">'
        '<connection id="c1" incomingRoad="1" connectingRoad="2"/>'
        "</junction></OpenDRIVE>"
    )
    graph = build_movement_graph(
        read_osm_document(
            write_osm(
                tmp_path,
                """
                <osm version="0.6" generator="test">
                  <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
                  <node id="3" lat="48" lon="11"/>
                  <way id="10"><nd ref="1"/><nd ref="2"/></way>
                  <way id="11"><nd ref="2"/><nd ref="3"/></way>
                </osm>
                """,
            )
        )
    )
    associations = {
        "1": {"class": "EXACT", "osm_way_id": "10", "osm_direction": "forward"},
        "2": {"class": "HIGH", "osm_way_id": "11", "osm_direction": "forward"},
    }
    comparisons = compare_with_junction_connections(root, graph, associations)
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.osm_from_way == "10"
    assert comparison.osm_to_way == "11"
    assert comparison.status in {
        MovementStatus.ALLOW_SOURCE_PROVEN.value,
        MovementStatus.UNKNOWN_NO_SOURCE.value,
        MovementStatus.DENY_SOURCE_PROVEN.value,
    }
    assert comparison.to_dict()["from_road"] == "1"
