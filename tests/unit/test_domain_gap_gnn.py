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
from ultimate_pipeline.domain_gap_gnn.graph_builder import _safe_float, node_feature_dim


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
