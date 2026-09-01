"""A2 characterization tests for the domain_gap_gnn engine (was 0 tests).

Deterministic, CPU-only, offline. Locks the behavior the thesis's perceptual
domain-gap numbers depend on. A failure here is a discovered defect, not a flaky
test; escalate rather than loosen the assertion.
"""
from __future__ import annotations

import pytest
import torch

from ultimate_pipeline.domain_gap_gnn.collapse_check import (
    _cross_mean_cosine,
    _pairwise_mean_cosine,
)
from ultimate_pipeline.domain_gap_gnn.latent_gap_utils import _as_2d, combine_latent_gaps
from ultimate_pipeline.domain_gap_gnn.map_encoder import MapEncoder, MapEncoderConfig
from ultimate_pipeline.domain_gap_gnn.graph_builder import (
    MapGraphBuilder,
    _safe_float,
    node_feature_dim,
)


# ---- collapse_check: cosine helpers ---------------------------------------
def test_pairwise_mean_cosine_identical_rows_is_one():
    e = torch.tensor([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    assert abs(_pairwise_mean_cosine(e) - 1.0) < 1e-6


def test_pairwise_mean_cosine_orthogonal_is_zero():
    e = torch.tensor([[1.0, 0.0], [0.0, 1.0]])
    assert abs(_pairwise_mean_cosine(e)) < 1e-6


def test_pairwise_mean_cosine_single_row_is_zero():
    assert _pairwise_mean_cosine(torch.tensor([[1.0, 0.0]])) == 0.0


def test_cross_mean_cosine_same_rows_is_one():
    a = torch.tensor([[1.0, 0.0], [1.0, 0.0]])
    assert abs(_cross_mean_cosine(a, a) - 1.0) < 1e-6


def test_cross_mean_cosine_orthogonal_is_zero():
    a = torch.tensor([[1.0, 0.0]])
    b = torch.tensor([[0.0, 1.0]])
    assert abs(_cross_mean_cosine(a, b)) < 1e-6


# ---- latent_gap_utils: combine_latent_gaps --------------------------------
def test_combine_latent_gaps_identical_is_zero_gap():
    z = torch.tensor([[1.0, 2.0, 3.0]])
    m = combine_latent_gaps(z, z)
    assert m["l1_mean"] < 1e-6 and m["l2"] < 1e-6 and m["mse"] < 1e-6
    assert m["cosine_distance"] < 1e-6
    assert abs(m["cosine_similarity"] - 1.0) < 1e-6


def test_combine_latent_gaps_orthogonal_positive_gap():
    a = torch.tensor([[1.0, 0.0, 0.0]])
    b = torch.tensor([[0.0, 1.0, 0.0]])
    m = combine_latent_gaps(a, b)
    assert m["l2"] > 0.0
    assert abs(m["cosine_similarity"]) < 1e-6  # orthogonal -> ~0
    assert abs(m["cosine_distance"] - 1.0) < 1e-6


def test_combine_latent_gaps_shape_mismatch_raises():
    with pytest.raises(ValueError):
        combine_latent_gaps(torch.zeros(1, 3), torch.zeros(1, 4))


def test_as_2d_promotes_1d_and_rejects_non_tensor():
    assert _as_2d(torch.zeros(5)).shape == (1, 5)
    with pytest.raises(TypeError):
        _as_2d([1, 2, 3])


# ---- graph_builder helpers ------------------------------------------------
def test_node_feature_dim_is_positive_int():
    d = node_feature_dim()
    assert isinstance(d, int) and d > 0


# ---- graph_builder: MapGraphBuilder.build_from_xodr edge construction ----
#
# 2026-09-01: the lane-link edge construction previously resolved a
# successor/predecessor target as (SOURCE road_id, SOURCE laneSection_s,
# to_lane) -- i.e. it never actually looked up where the link target lives,
# so almost every edge collapsed into a self-loop (a lane's successor id
# happening to equal its own id). Empirically confirmed on 15 real tiles from
# the C21_GNN_AUTHORITATIVE training set: 972/974 edges (99.8%) were
# self-loops before the fix, 0/1208 after. These tests lock the corrected
# resolution: intra-road (next/prev laneSection), inter-road (via road-level
# link + contactPoint), and the honest "no edge" outcome for junction-
# mediated connections (tile-scoped XODR carries no <junction> definitions
# to resolve those against).


def _road_xml(
    road_id: str,
    *,
    length: str = "10",
    link_xml: str = "",
    lane_sections_xml: str,
) -> str:
    return f"""
    <road id="{road_id}" length="{length}" junction="-1">
      {link_xml}
      <planView><geometry s="0" x="0" y="0" hdg="0" length="{length}"><line/></geometry></planView>
      <type s="0" type="town"><speed max="50"/></type>
      <lanes>{lane_sections_xml}</lanes>
    </road>
    """


def _lane_section_xml(s: str, lane_id: str, *, link_xml: str = "") -> str:
    return f"""
    <laneSection s="{s}">
      <left><lane id="{lane_id}" type="driving">
        <width sOffset="0" a="3.5" b="0" c="0" d="0"/>
        {link_xml}
      </lane></left>
      <center><lane id="0" type="none"/></center>
    </laneSection>
    """


def _write_odr(tmp_path, roads_xml: str, junctions_xml: str = ""):
    p = tmp_path / "m.xodr"
    p.write_text(
        f'<?xml version="1.0"?><OpenDRIVE>{roads_xml}{junctions_xml}</OpenDRIVE>',
        encoding="utf-8",
    )
    return p


def _self_loop_count(g) -> int:
    if g.edge_index.numel() == 0:
        return 0
    return int((g.edge_index[0] == g.edge_index[1]).sum())


def test_inter_road_successor_link_resolves_to_real_cross_road_edge(tmp_path):
    road1 = _road_xml(
        "1",
        link_xml='<link><successor elementType="road" elementId="2" contactPoint="start"/></link>',
        lane_sections_xml=_lane_section_xml("0", "1", link_xml='<link><successor id="1"/></link>'),
    )
    road2 = _road_xml(
        "2",
        link_xml='<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>',
        lane_sections_xml=_lane_section_xml("0", "1", link_xml='<link><predecessor id="1"/></link>'),
    )
    p = _write_odr(tmp_path, road1 + road2)

    g = MapGraphBuilder.build_from_xodr(str(p))

    assert g.edge_index.shape[1] == 2  # successor edge + predecessor edge
    assert _self_loop_count(g) == 0
    # the two edges must connect DIFFERENT nodes (road 1's lane <-> road 2's lane)
    src, dst = g.edge_index[0].tolist(), g.edge_index[1].tolist()
    assert all(s != d for s, d in zip(src, dst))


def test_inter_road_link_via_contactpoint_end_targets_last_laneSection(tmp_path):
    # road "2" has TWO laneSections; road "1"'s successor points at road "2"
    # with contactPoint="end", so it must resolve to road 2's LAST
    # laneSection (s=5), not its first (s=0).
    road1 = _road_xml(
        "1",
        link_xml='<link><successor elementType="road" elementId="2" contactPoint="end"/></link>',
        lane_sections_xml=_lane_section_xml("0", "1", link_xml='<link><successor id="1"/></link>'),
    )
    road2 = _road_xml(
        "2",
        length="10",
        lane_sections_xml=(
            _lane_section_xml("0", "1") + _lane_section_xml("5", "1")
        ),
    )
    p = _write_odr(tmp_path, road1 + road2)

    g = MapGraphBuilder.build_from_xodr(str(p))

    assert g.edge_index.shape[1] == 1
    assert _self_loop_count(g) == 0
    # destination node must be road 2's laneSection at s=5, not s=0
    dst_idx = int(g.edge_index[1, 0])
    # node ordering is deterministic: sorted by (road_id, sec_s, lane_id) as strings;
    # "1" < "2", and within road "2", 0.0 < 5.0 -- so s=5 section's driving lane
    # is NOT the first road-"2" node in sorted order.
    assert dst_idx != 1  # would be road "2" sec_s=0 lane "1" if resolved wrong


def test_intra_road_multi_lanesection_successor_resolves_to_next_section(tmp_path):
    lane_sections = (
        _lane_section_xml("0", "1", link_xml='<link><successor id="1"/></link>')
        + _lane_section_xml("5", "1")
    )
    road = _road_xml("1", length="10", lane_sections_xml=lane_sections)
    p = _write_odr(tmp_path, road)

    g = MapGraphBuilder.build_from_xodr(str(p))

    assert g.edge_index.shape[1] == 1
    assert _self_loop_count(g) == 0


def test_intra_road_multi_lanesection_predecessor_resolves_to_prev_section(tmp_path):
    lane_sections = (
        _lane_section_xml("0", "1")
        + _lane_section_xml("5", "1", link_xml='<link><predecessor id="1"/></link>')
    )
    road = _road_xml("1", length="10", lane_sections_xml=lane_sections)
    p = _write_odr(tmp_path, road)

    g = MapGraphBuilder.build_from_xodr(str(p))

    assert g.edge_index.shape[1] == 1
    assert _self_loop_count(g) == 0


def test_junction_mediated_link_produces_no_edge_not_a_self_loop(tmp_path):
    """Tile-scoped XODR carries no <junction> definitions, so a link that
    resolves through a junction cannot be resolved to a real target lane.
    The honest outcome is no edge at all -- not a self-loop, and not a
    crude all-lanes-of-A-to-all-lanes-of-B guess."""
    road1 = _road_xml(
        "1",
        link_xml='<link><successor elementType="junction" elementId="99"/></link>',
        lane_sections_xml=_lane_section_xml("0", "1", link_xml='<link><successor id="1"/></link>'),
    )
    road2 = _road_xml(
        "2",
        link_xml='<link><predecessor elementType="junction" elementId="99"/></link>',
        lane_sections_xml=_lane_section_xml("0", "1", link_xml='<link><predecessor id="1"/></link>'),
    )
    p = _write_odr(tmp_path, road1 + road2)

    g = MapGraphBuilder.build_from_xodr(str(p))

    assert g.edge_index.shape[1] == 0
    assert _self_loop_count(g) == 0


def test_successor_to_missing_road_produces_no_edge_and_does_not_crash(tmp_path):
    road1 = _road_xml(
        "1",
        link_xml='<link><successor elementType="road" elementId="999" contactPoint="start"/></link>',
        lane_sections_xml=_lane_section_xml("0", "1", link_xml='<link><successor id="1"/></link>'),
    )
    p = _write_odr(tmp_path, road1)

    g = MapGraphBuilder.build_from_xodr(str(p))  # must not raise

    assert g.edge_index.shape[1] == 0


def test_lane_with_no_link_element_produces_no_edge(tmp_path):
    road1 = _road_xml("1", lane_sections_xml=_lane_section_xml("0", "1"))
    p = _write_odr(tmp_path, road1)

    g = MapGraphBuilder.build_from_xodr(str(p))

    assert g.edge_index.shape[1] == 0


def test_regression_real_c21_training_tiles_have_zero_self_loops():
    """Integration-style regression guard against the exact defect class
    found in production: run the real graph builder against actual tiles
    from the C21_GNN_AUTHORITATIVE training set and confirm the self-loop
    fraction that was previously 99.8% is now 0%."""
    import glob

    files = sorted(
        glob.glob(
            "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/union_tiles/*.xodr"
        )
    )
    if not files:
        pytest.skip("no real C21_GNN_AUTHORITATIVE tiles available in this checkout")

    total_edges = 0
    total_self_loops = 0
    for f in files[:20]:
        g = MapGraphBuilder.build_from_xodr(f)
        if g is None or g.edge_index.numel() == 0:
            continue
        total_edges += g.edge_index.shape[1]
        total_self_loops += _self_loop_count(g)

    assert total_edges > 0  # sanity: the sample actually produced edges
    assert total_self_loops == 0


def test_safe_float_parses_and_falls_back():
    assert _safe_float("3.5") == 3.5
    assert _safe_float("not-a-number", default=1.0) == 1.0


# ---- map_encoder: forward shape + determinism -----------------------------
def _tiny_batch(node_dim: int):
    from torch_geometric.data import Batch, Data

    d = Data(
        x=torch.randn(5, node_dim),
        edge_index=torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]], dtype=torch.long),
    )
    return Batch.from_data_list([d])


def test_map_encoder_forward_shape_norm_and_determinism():
    cfg = MapEncoderConfig(node_dim=4, hidden_dim=8, num_layers=2, out_dim=6, dropout=0.0)
    batch = _tiny_batch(cfg.node_dim)
    model = MapEncoder(cfg).eval()
    with torch.no_grad():
        z1 = model(batch)
        z2 = model(batch)
    assert z1.shape == (1, cfg.out_dim)
    assert torch.allclose(z1, z2)  # eval + dropout=0 gives deterministic forward
    # normalize_embedding defaults True -> unit-norm embedding
    assert abs(float(z1.norm().item()) - 1.0) < 1e-5
