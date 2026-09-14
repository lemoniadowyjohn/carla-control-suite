from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.domain_gap_gnn.graph_builder import MapGraphBuilder, node_feature_dim
from ultimate_pipeline.geometry.lane_seam_checker import _sample_geometry as seam_sample
from ultimate_pipeline.geometry.planview_smoother import _line_end_xy
from ultimate_pipeline.pipeline_stages.stage_06_links import _geom_endpoint
from ultimate_pipeline.roadrunner.alignment import _extract_xodr_planview_points
from ultimate_pipeline.topology.topology_repair import _geometry_endpoint, _road_end_heading_deg
from ultimate_pipeline.topology.topology_validation import road_endpoint_pose
from ultimate_pipeline.visualization.curvature_drift_plot import _road_curvature
from ultimate_pipeline.visualization.heatmap_generator import HeatmapGenerator
from ultimate_pipeline.visualization.lane_overlay import LaneOverlay
from ultimate_pipeline.visualization.map_diff import _sample_geometry as diff_sample
from ultimate_pipeline.visualization.map_plotter import MapPlotter


def _parampoly3_geometry() -> ET.Element:
    return ET.fromstring(
        '<geometry s="0" x="100" y="200" hdg="0" length="10">'
        '<paramPoly3 aU="0" bU="10" cU="0" dU="0" '
        'aV="0" bV="0" cV="0" dV="2" pRange="normalized"/>'
        '</geometry>'
    )


def _road_with_parampoly3() -> ET.Element:
    root = ET.fromstring(
        '<OpenDRIVE><road id="1" length="10" junction="-1">'
        '<planView><geometry s="0" x="100" y="200" hdg="0" length="10">'
        '<paramPoly3 aU="0" bU="10" cU="0" dU="0" '
        'aV="0" bV="0" cV="0" dV="2" pRange="normalized"/>'
        '</geometry></planView>'
        '<lanes><laneSection s="0"><center><lane id="0" type="none"/>'
        '</center><right><lane id="-1" type="driving">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        '</lane></right></laneSection></lanes>'
        '</road></OpenDRIVE>'
    )
    return root.find("road")


def test_parampoly3_endpoint_is_used_by_structural_consumers():
    geometry = _parampoly3_geometry()
    road = _road_with_parampoly3()
    expected_heading = math.atan2(6.0, 10.0)

    assert seam_sample(geometry)[-1] == pytest.approx((110.0, 202.0))
    assert _geom_endpoint(geometry) == pytest.approx((110.0, 202.0, expected_heading))
    assert _line_end_xy(geometry) == pytest.approx((110.0, 202.0))
    assert _geometry_endpoint(geometry) == pytest.approx((110.0, 202.0))
    assert _road_end_heading_deg(road) == pytest.approx(math.degrees(expected_heading))
    endpoint = road_endpoint_pose(road, "end")
    assert (endpoint.x, endpoint.y, endpoint.hdg) == pytest.approx(
        (110.0, 202.0, expected_heading)
    )


def test_parampoly3_alignment_and_gnn_features_are_not_flattened(tmp_path):
    road = _road_with_parampoly3()
    root = ET.Element("OpenDRIVE")
    root.append(road)
    points = _extract_xodr_planview_points(root)
    assert points[-1] == pytest.approx((110.0, 202.0))

    xodr = tmp_path / "parampoly3.xodr"
    ET.ElementTree(root).write(xodr, encoding="utf-8")
    graph = MapGraphBuilder.build_from_xodr(str(xodr))
    curvature_mean_index = node_feature_dim() - 3
    assert graph.x[0, curvature_mean_index].item() > 0.0


def test_parampoly3_quality_visualizations_use_true_geometry():
    geometry = _parampoly3_geometry()
    road = _road_with_parampoly3()
    expected = (110.0, 202.0, math.atan2(6.0, 10.0))

    assert HeatmapGenerator._endpoint(0.0, 0.0, 0.0, 10.0, geometry) == pytest.approx(expected)
    assert LaneOverlay._endpoint(0.0, 0.0, 0.0, 10.0, geometry) == pytest.approx(expected)
    assert diff_sample(geometry)[-1] == pytest.approx((110.0, 202.0))
    xs, ys = MapPlotter._sample_geometry(geometry)
    assert (xs[-1], ys[-1]) == pytest.approx((110.0, 202.0))
    assert _road_curvature(road)
    assert max(_road_curvature(road)) > 0.0


def test_unknown_primitive_retains_explicit_line_fallback():
    geometry = ET.fromstring(
        '<geometry s="0" x="1" y="2" hdg="0" length="3"><unknown/></geometry>'
    )
    assert seam_sample(geometry)[-1] == pytest.approx((4.0, 2.0))
