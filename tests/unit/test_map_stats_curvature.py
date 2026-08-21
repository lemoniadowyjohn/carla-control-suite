"""RQ1 curvature-sampling fix (map_stats_xodr).

BUG: `XODRMapStatsExtractor._collect_curvatures` read curvature ONLY from `<arc>`
geometries. Both the auto map (Osm2Odr/SUMO) and the manual map (RoadRunner) store
their curves as `<paramPoly3>`, so the extractor returned [] for the auto map and just
the handful of incidental arcs for the manual map — making the RQ1 curvature gap a
measurement artifact rather than a real comparison. Curvature must be sampled from
paramPoly3 (and spiral) geometry too.
"""
import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor


def _road(inner_xml: str, length: str = "1.0") -> ET.Element:
    return ET.fromstring(
        f'<road><planView>'
        f'<geometry s="0" x="0" y="0" hdg="0" length="{length}">{inner_xml}</geometry>'
        f'</planView></road>'
    )


def test_collect_curvatures_from_parampoly3_is_nonempty():
    # The core bug: paramPoly3 curvature was never collected -> empty samples.
    road = _road(
        '<paramPoly3 aU="0" bU="1" cU="0" dU="0" aV="0" bV="0" cV="0.005" dV="0" pRange="arcLength"/>'
    )
    curvs = XODRMapStatsExtractor._collect_curvatures(road)
    assert len(curvs) > 0
    assert all(math.isfinite(k) for k in curvs)


def test_collect_curvatures_parampoly3_known_value():
    # u(p)=p, v(p)=0.005*p^2 (arcLength) -> curvature ~= 2*cV = 0.01 at interior points.
    road = _road(
        '<paramPoly3 aU="0" bU="1" cU="0" dU="0" aV="0" bV="0" cV="0.005" dV="0" pRange="arcLength"/>'
    )
    curvs = XODRMapStatsExtractor._collect_curvatures(road)
    assert len(curvs) >= 1
    for k in curvs:
        assert abs(k - 0.01) < 1e-3


def test_collect_curvatures_supports_normalized_prange():
    # The auto map uses pRange="normalized" — must be handled, not skipped.
    road = _road(
        '<paramPoly3 aU="0" bU="1" cU="0" dU="0" aV="0" bV="0" cV="0.005" dV="0" pRange="normalized"/>',
        length="1.0",
    )
    curvs = XODRMapStatsExtractor._collect_curvatures(road)
    assert len(curvs) > 0
    assert all(math.isfinite(k) for k in curvs)


def test_collect_curvatures_arc_still_works():
    # Backward compat: existing arc handling is preserved.
    road = _road('<arc curvature="0.02"/>')
    curvs = XODRMapStatsExtractor._collect_curvatures(road)
    assert curvs == [0.02]


def test_collect_curvatures_degenerate_parampoly3_does_not_crash():
    # Zero-length / degenerate segment must be skipped, never raise.
    road = _road(
        '<paramPoly3 aU="0" bU="0" cU="0" dU="0" aV="0" bV="0" cV="0" dV="0" pRange="arcLength"/>',
        length="0.0",
    )
    curvs = XODRMapStatsExtractor._collect_curvatures(road)
    assert isinstance(curvs, list)


def test_collect_curvatures_line_only_is_empty():
    # A pure straight line carries no sampled curvature (semantics: curved geometry only).
    road = _road('<line/>')
    curvs = XODRMapStatsExtractor._collect_curvatures(road)
    assert curvs == []


def test_collect_curvatures_excludes_nonphysical_degenerate_segment():
    # Near-cusp paramPoly3: u(p)=p-2p^2 so u'(p=0.25)=0; with tiny v' the tangent nearly
    # vanishes and the analytic curvature blows up (radius << 1 m). Such ill-conditioned
    # values are not real road curvature and must NOT be emitted.
    road = _road(
        '<paramPoly3 aU="0" bU="1" cU="-2" dU="0" aV="0" bV="0" cV="0.001" dV="0" pRange="normalized"/>',
        length="1.0",
    )
    curvs = XODRMapStatsExtractor._collect_curvatures(road)
    leaked = [k for k in curvs if abs(k) > 1.0]
    assert not leaked, f"leaked non-physical curvature (radius < 1 m): {leaked}"
