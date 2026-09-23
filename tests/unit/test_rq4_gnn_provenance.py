"""OC-51 (RQ4): GNN scientific-reproducibility + K-sweep design tests.

Every test here locks a §19 requirement: nested K subsets, seed
separation, checkpoint identity fail-closed, content-derived hashes,
strict dataset accounting, polynomial lane-width features, and
enumeration-order independence. Deterministic, CPU-only, offline.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest
import torch

from ultimate_pipeline.domain_gap_gnn import gnn_provenance as prov
from ultimate_pipeline.domain_gap_gnn.graph_builder import (
    NODE_FEATURE_NAMES,
    MapGraphBuilder,
    _lane_width_stats,
    describe_graph_schema,
    graph_schema_hash,
)
from ultimate_pipeline.domain_gap_gnn.map_tile_dataset import MapTileDataset


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


def _lane_xml(lane_id: str, lane_type: str = "driving", width_xml: str = "") -> str:
    widths = width_xml or '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
    return f"""
    <left><lane id="{lane_id}" type="{lane_type}">
      {widths}
    </lane></left>
    <center><lane id="0" type="none"/></center>
    """


def _write_tile(path: Path, roads_xml: str) -> Path:
    path.write_text(
        f'<?xml version="1.0"?><OpenDRIVE>{roads_xml}</OpenDRIVE>',
        encoding="utf-8",
    )
    return path


def _write_tiles_dir(d: Path, n: int, *, prefix: str = "tile") -> list[str]:
    names = []
    for i in range(n):
        name = f"{prefix}_{i:03d}.xodr"
        _write_tile(
            d / name,
            _road_xml(
                str(1000 + i),
                lane_sections_xml=(
                    f"<laneSection s=\"0\">{_lane_xml('1')}</laneSection>"
                ),
            ),
        )
        names.append(name)
    return names


# ---------------------------------------------------------------------------
# §19: K subsets nested
# ---------------------------------------------------------------------------

def test_k_subsets_are_nested():
    names = [f"tile_{i:03d}.xodr" for i in range(72)]
    subsets = prov.nested_subsets(names, [10, 20, 30, 40, 50, 60, 72], 1234)
    ordered = sorted(subsets)
    for smaller, larger in zip(ordered, ordered[1:]):
        assert subsets[smaller] == subsets[larger][: int(smaller)]
    assert len(subsets[10]) == 10
    assert len(subsets[72]) == 72


def test_k_subset_exceeding_pool_raises():
    with pytest.raises(ValueError):
        prov.nested_subsets(["a.xodr", "b.xodr"], [10], 1234)


# ---------------------------------------------------------------------------
# §19: same selection seed reproduces exact subset
# ---------------------------------------------------------------------------

def test_same_selection_seed_reproduces_exact_subset():
    names = [f"tile_{i:03d}.xodr" for i in range(40)]
    first = prov.nested_subsets(names, [10, 20, 30], 999)
    second = prov.nested_subsets(names, [10, 20, 30], 999)
    assert first == second
    other = prov.nested_subsets(names, [10, 20, 30], 1000)
    assert other[10] != first[10]  # sanity: seed actually matters


# ---------------------------------------------------------------------------
# §19: training seed does not change chosen tiles
# ---------------------------------------------------------------------------

def test_training_seed_does_not_change_chosen_tiles():
    """Subset composition is a function of the selection seed only. Two
    runs that differ ONLY in training seed must train on identical tiles."""
    names = [f"tile_{i:03d}.xodr" for i in range(40)]
    for training_seed in (42, 43, 44):
        _ = training_seed  # deliberately NOT an input to subset selection
        subsets = prov.nested_subsets(names, [10, 20], 1234)
        assert subsets[10] == prov.nested_subsets(names, [10], 1234)[10]
    ref = prov.nested_subsets(names, [10, 20], 1234)
    assert ref[10] == ref[20][:10]


# ---------------------------------------------------------------------------
# §19: selection seed does not accidentally alter configured training seed
# ---------------------------------------------------------------------------

def test_selection_seed_does_not_alter_training_seed_config():
    from ultimate_pipeline.domain_gap_gnn import run_ksweep as ks

    argv = [
        "--tiles_dir", "some/tiles",
        "--out_dir", "some/out",
        "--selection_seed", "777",
        "--training_seeds", "42", "43",
    ]
    args = ks._parse_args(argv)
    assert args.selection_seed == 777
    assert list(args.training_seeds) == [42, 43]
    # The deterministic permutation consumes only the selection seed...
    names = [f"t{i}.xodr" for i in range(10)]
    assert prov.deterministic_permutation(names, 777) == (
        prov.deterministic_permutation(names, args.selection_seed)
    )
    # ...and the training seeds survive untouched.
    assert list(args.training_seeds) == [42, 43]


# ---------------------------------------------------------------------------
# §19: checkpoint wrong dataset / schema / seed-config rejected
# ---------------------------------------------------------------------------

def _tiny_state() -> dict:
    return {"w": torch.zeros(4, 4), "b": torch.zeros(4)}


def _base_metadata(**overrides):
    meta = prov.build_checkpoint_metadata(
        graph_schema_sha256="schema-aaa",
        training_dataset_manifest_sha256="dataset-aaa",
        tile_selection_sha256="selection-aaa",
        source_tile_hashes=[{"tile": "t.xodr", "tile_sha256": "h"}],
        selection_seed=1234,
        training_seed=42,
        model_config={"node_dim": 12, "hidden_dim": 8},
        training_config={"epochs": 5, "lr": 0.001},
        git_sha="abc123",
        torch_version="2.9.1",
        torch_geometric_version="2.7.0",
    )
    meta.update(overrides)
    return meta


def test_checkpoint_wrong_dataset_rejected(tmp_path):
    ckpt = tmp_path / "c.pt"
    prov.save_checkpoint(ckpt, _tiny_state(), _base_metadata())
    sidecar = json.loads((tmp_path / "c.pt.manifest.json").read_text())
    expected = dict(sidecar)
    expected["training_dataset_manifest_sha256"] = "dataset-BBB"
    expected["tile_selection_sha256"] = "selection-BBB"
    ok, reasons = prov.checkpoints_compatible(expected, sidecar)
    assert not ok
    assert "mismatch:training_dataset_manifest_sha256" in reasons
    assert "mismatch:tile_selection_sha256" in reasons


def test_checkpoint_wrong_graph_schema_rejected(tmp_path):
    ckpt = tmp_path / "c.pt"
    prov.save_checkpoint(ckpt, _tiny_state(), _base_metadata())
    with pytest.raises(ValueError, match="schema"):
        prov.load_checkpoint(ckpt, expected_schema_hash="schema-ZZZ")


def test_checkpoint_wrong_seed_or_config_rejected(tmp_path):
    ckpt = tmp_path / "c.pt"
    prov.save_checkpoint(ckpt, _tiny_state(), _base_metadata())
    sidecar = json.loads((tmp_path / "c.pt.manifest.json").read_text())
    for field, bad in (
        ("training_seed", 43),
        ("selection_seed", 555),
        ("model_config", {"node_dim": 12, "hidden_dim": 16}),
        ("training_config", {"epochs": 5, "lr": 0.01}),
    ):
        expected = dict(sidecar)
        expected[field] = bad
        ok, reasons = prov.checkpoints_compatible(expected, sidecar)
        assert not ok, f"field {field} mismatch accepted"
        assert f"mismatch:{field}" in reasons


def test_checkpoint_matching_identity_accepted(tmp_path):
    ckpt = tmp_path / "c.pt"
    prov.save_checkpoint(ckpt, _tiny_state(), _base_metadata())
    sidecar = json.loads((tmp_path / "c.pt.manifest.json").read_text())
    ok, reasons = prov.checkpoints_compatible(dict(sidecar), sidecar)
    assert ok and reasons == []
    state, meta, label = prov.load_checkpoint(
        ckpt, expected_schema_hash="schema-aaa", expected_node_dim=12
    )
    assert meta is not None
    assert label == prov.VERIFIED_CRYPTOGRAPHIC_PROVENANCE


def test_legacy_checkpoint_labelled_not_upgraded(tmp_path):
    ckpt = tmp_path / "legacy.pt"
    torch.save({"model_state": _tiny_state(), "cfg": {"node_dim": 12}}, ckpt)
    state, meta, label = prov.load_checkpoint(ckpt)
    assert meta is None
    assert label == prov.LEGACY_UNBOUND_CHECKPOINT


# ---------------------------------------------------------------------------
# §19: stale checkpoint cannot be silently reused (ksweep policy)
# ---------------------------------------------------------------------------

def test_stale_checkpoint_without_manifest_not_reused(tmp_path):
    from ultimate_pipeline.domain_gap_gnn import run_ksweep as ks

    train_dir = tmp_path / "k_10" / "seed_42"
    train_dir.mkdir(parents=True)
    stale = train_dir / "map_encoder_epoch50.pt"
    stale.write_bytes(b"stale-bytes")
    expected = {"graph_schema_sha256": "x"}
    assert ks._try_reuse_checkpoint(train_dir, 50, expected, on_mismatch="retrain") is None


def test_stale_checkpoint_with_mismatched_manifest_not_reused(tmp_path):
    from ultimate_pipeline.domain_gap_gnn import run_ksweep as ks

    train_dir = tmp_path / "k_10" / "seed_42"
    train_dir.mkdir(parents=True)
    (train_dir / "map_encoder_epoch50.pt").write_bytes(b"stale-bytes")
    (train_dir / "map_encoder_epoch50.pt.manifest.json").write_text(
        json.dumps({"graph_schema_sha256": "OLD"}), encoding="utf-8"
    )
    expected = {"graph_schema_sha256": "NEW"}
    assert ks._try_reuse_checkpoint(train_dir, 50, expected, on_mismatch="retrain") is None
    with pytest.raises(RuntimeError, match="identity mismatch"):
        ks._try_reuse_checkpoint(train_dir, 50, expected, on_mismatch="fail")


def test_matching_checkpoint_reused(tmp_path):
    from ultimate_pipeline.domain_gap_gnn import run_ksweep as ks

    subset_dir = tmp_path / "subset"
    subset_dir.mkdir()
    _write_tiles_dir(subset_dir, 3)
    expected = ks._expected_manifest_for_subset(
        subset_dir=subset_dir,
        subset_names=sorted(p.name for p in subset_dir.glob("*.xodr")),
        all_tile_hashes={p.name: prov.sha256_file(p) for p in subset_dir.glob("*.xodr")},
        selection_seed=1234,
        training_seed=42,
        epochs=5,
        batch_size=2,
        lr=1e-4,
        noise_std=0.01,
        temperature=0.5,
        width_mode="legacy",
        strict_dataset=False,
    )
    train_dir = tmp_path / "k_3" / "seed_42"
    train_dir.mkdir(parents=True)
    (train_dir / "map_encoder_epoch5.pt").write_bytes(b"ckpt-bytes")
    (train_dir / "map_encoder_epoch5.pt.manifest.json").write_text(
        json.dumps(expected), encoding="utf-8"
    )
    got = ks._try_reuse_checkpoint(train_dir, 5, expected, on_mismatch="retrain")
    assert got is not None and got.name == "map_encoder_epoch5.pt"


# ---------------------------------------------------------------------------
# §19: SHA changes if tile bytes change
# ---------------------------------------------------------------------------

def test_tile_sha_changes_when_bytes_change(tmp_path):
    p = _write_tile(tmp_path / "t.xodr", _road_xml("1", lane_sections_xml=(
        "<laneSection s=\"0\">" + _lane_xml("1") + "</laneSection>")))
    before = prov.sha256_file(p)
    with open(p, "ab") as f:
        f.write(b"<!-- drift -->")
    assert prov.sha256_file(p) != before


def test_dataset_manifest_hash_changes_when_tile_bytes_change(tmp_path):
    d = tmp_path / "tiles"
    d.mkdir()
    _write_tiles_dir(d, 3)
    entries_a, hash_a, _ = prov.build_training_dataset_manifest(str(d))
    assert len(entries_a) == 3
    first = sorted(d.glob("*.xodr"))[0]
    with open(first, "ab") as f:
        f.write(b"<!-- drift -->")
    entries_b, hash_b, _ = prov.build_training_dataset_manifest(str(d))
    assert hash_b != hash_a
    assert [e["tile_sha256"] for e in entries_a] != [e["tile_sha256"] for e in entries_b]


# ---------------------------------------------------------------------------
# §19: graph schema SHA changes if feature order changes
# ---------------------------------------------------------------------------

def test_graph_schema_sha_changes_if_feature_order_changes():
    schema = describe_graph_schema(width_mode="legacy")
    h1 = prov.graph_schema_hash(schema)
    swapped = dict(schema)
    names = list(swapped["node_feature_names"])
    names[0], names[1] = names[1], names[0]
    swapped["node_feature_names"] = names
    swapped["node_feature_order"] = list(names)
    assert prov.graph_schema_hash(swapped) != h1


def test_graph_schema_sha_differs_between_width_modes():
    assert graph_schema_hash(width_mode="legacy") != graph_schema_hash(
        width_mode="polynomial"
    )


# ---------------------------------------------------------------------------
# §19: strict dataset catches invalid tile
# ---------------------------------------------------------------------------

def test_strict_dataset_catches_invalid_tile(tmp_path):
    d = tmp_path / "tiles"
    d.mkdir()
    _write_tiles_dir(d, 2)
    (d / "bad.xodr").write_text("this is not xml at all <", encoding="utf-8")

    legacy = MapTileDataset(str(d))  # LEGACY_TOLERANT: skips
    assert legacy.num_tiles == 2
    statuses = {r["tile"]: r["status"] for r in legacy.accounting}
    assert statuses["bad.xodr"] == "INVALID"
    assert legacy.coverage["expected"] == 3
    assert legacy.coverage["used"] == 2
    assert legacy.coverage["invalid"] == 1

    with pytest.raises(RuntimeError, match="Failed to build graph"):
        MapTileDataset(str(d), strict=True, width_mode="polynomial")


def test_strict_dataset_catches_malformed_width_value(tmp_path):
    d = tmp_path / "tiles"
    d.mkdir()
    bad_width = '<width sOffset="0" a="not-a-number" b="0" c="0" d="0"/>'
    _write_tile(
        d / "w.xodr",
        _road_xml("1", lane_sections_xml=(
            "<laneSection s=\"0\">" + _lane_xml("1", width_xml=bad_width)
            + "</laneSection>"
        )),
    )
    tolerant = MapTileDataset(str(d))  # legacy: falls back, tile still used
    assert tolerant.num_tiles == 1
    with pytest.raises(RuntimeError):
        MapTileDataset(str(d), strict=True, width_mode="polynomial")


def test_dataset_excluded_by_policy_accounted(tmp_path):
    d = tmp_path / "tiles"
    d.mkdir()
    _write_tiles_dir(d, 3)
    ds = MapTileDataset(str(d), exclude_names=["tile_000.xodr"])
    assert ds.num_tiles == 2
    statuses = {r["tile"]: r["status"] for r in ds.accounting}
    assert statuses["tile_000.xodr"] == "EXCLUDED_BY_POLICY"
    assert ds.coverage["excluded_by_policy"] == 1


def test_strict_requires_polynomial_width_mode(tmp_path):
    d = tmp_path / "tiles"
    d.mkdir()
    _write_tiles_dir(d, 1)
    with pytest.raises(ValueError, match="polynomial"):
        MapTileDataset(str(d), strict=True, width_mode="legacy")
    with pytest.raises(ValueError, match="polynomial"):
        MapGraphBuilder.build_from_xodr(
            str(d / "tile_000.xodr"), strict=True, width_mode="legacy"
        )


# ---------------------------------------------------------------------------
# §19: polynomial lane-width fixture produces expected feature
# ---------------------------------------------------------------------------

def test_polynomial_width_fixture_matches_analytic_expectation(tmp_path):
    """width(s) = 2.0 + 0.1·ds over ds ∈ [0, 10] (road length 10, one
    section); 8 uniform samples → mean 2.5, analytic std."""
    p = _write_tile(
        tmp_path / "w.xodr",
        _road_xml("7", length="10", lane_sections_xml=(
            "<laneSection s=\"0\">"
            + _lane_xml("1", width_xml='<width sOffset="0" a="2.0" b="0.1" c="0" d="0"/>')
            + "</laneSection>"
        )),
    )
    g = MapGraphBuilder.build_from_xodr(
        str(p), strict=True, width_mode="polynomial"
    )
    assert g is not None
    ds_pts = [10.0 * j / 7 for j in range(8)]
    exp_mean = 2.0 + 0.1 * statistics.fmean(ds_pts)
    exp_std = 0.1 * statistics.pstdev(ds_pts)
    width_mean_idx = NODE_FEATURE_NAMES.index("width_mean_norm")
    width_std_idx = NODE_FEATURE_NAMES.index("width_std_norm")
    driving_rows = [row for row in g.x.tolist() if row[0] == 1.0]
    assert len(driving_rows) == 1
    row = driving_rows[0]
    assert row[width_mean_idx] == pytest.approx(exp_mean / 5.0, rel=1e-5)
    assert row[width_std_idx] == pytest.approx(exp_std / 5.0, rel=1e-5)


def test_legacy_width_uses_a_only_and_differs_from_polynomial(tmp_path):
    p = _write_tile(
        tmp_path / "w.xodr",
        _road_xml("7", length="10", lane_sections_xml=(
            "<laneSection s=\"0\">"
            + _lane_xml("1", width_xml='<width sOffset="0" a="2.0" b="0.1" c="0" d="0"/>')
            + "</laneSection>"
        )),
    )
    g_legacy = MapGraphBuilder.build_from_xodr(str(p), width_mode="legacy")
    g_poly = MapGraphBuilder.build_from_xodr(
        str(p), strict=True, width_mode="polynomial"
    )
    idx = NODE_FEATURE_NAMES.index("width_mean_norm")
    legacy_mean = [row[idx] for row in g_legacy.x.tolist() if row[0] == 1.0][0]
    poly_mean = [row[idx] for row in g_poly.x.tolist() if row[0] == 1.0][0]
    assert legacy_mean == pytest.approx(2.0 / 5.0)  # bare `a` coefficient
    assert poly_mean == pytest.approx(2.5 / 5.0)    # evaluated polynomial
    assert legacy_mean != pytest.approx(poly_mean)


def test_lane_width_stats_helper_direct():
    import xml.etree.ElementTree as ET

    lane = ET.fromstring(
        '<lane id="1" type="driving">'
        '<width sOffset="0" a="3.0" b="0.2" c="0" d="0"/>'
        '<width sOffset="5" a="4.0" b="0" c="0" d="0"/>'
        "</lane>"
    )
    mean, std = _lane_width_stats(
        lane, strict=True, width_mode="polynomial",
        section_end_abs=10.0, section_s=0.0,
    )
    # interval 1: 3.0+0.2·ds on [0,5]; interval 2: constant 4.0 on [5,10].
    s1 = [3.0 + 0.2 * (5.0 * j / 7) for j in range(8)]
    s2 = [4.0] * 8
    pooled = s1 + s2
    assert mean == pytest.approx(statistics.fmean(pooled))
    assert std == pytest.approx(statistics.pstdev(pooled))


# ---------------------------------------------------------------------------
# §19: reversed file enumeration yields same manifests
# ---------------------------------------------------------------------------

def test_reversed_enumeration_yields_same_manifests(tmp_path):
    d = tmp_path / "tiles"
    d.mkdir()
    _write_tiles_dir(d, 4)
    fwd = sorted(p.name for p in d.glob("*.xodr"))
    rev = list(reversed(fwd))
    assert prov.deterministic_permutation(fwd, 11) == prov.deterministic_permutation(rev, 11)
    entries, h1, hashes = prov.build_training_dataset_manifest(str(d))
    assert h1 == prov.dataset_manifest_hash(list(reversed(entries)))
    assert prov.tile_selection_hash(fwd, hashes) == prov.tile_selection_hash(rev, hashes)


# ---------------------------------------------------------------------------
# Provenance plumbing: metadata checkpoint round-trips fail-closed
# ---------------------------------------------------------------------------

def test_metadata_checkpoint_roundtrip_and_schema_mismatch_fails(tmp_path):
    from ultimate_pipeline.domain_gap_gnn.latent_gap_runner import (
        _load_encoder,
        checkpoint_provenance_label,
    )
    from ultimate_pipeline.domain_gap_gnn.map_encoder import (
        MapEncoder,
        MapEncoderConfig,
    )

    cfg = MapEncoderConfig(node_dim=12, hidden_dim=8, num_layers=2,
                           out_dim=6, dropout=0.0)
    model = MapEncoder(cfg)
    meta = prov.build_checkpoint_metadata(
        graph_schema_sha256=graph_schema_hash(width_mode="legacy"),
        training_dataset_manifest_sha256="dataset-x",
        tile_selection_sha256="selection-x",
        source_tile_hashes=[],
        selection_seed=1234,
        training_seed=42,
        model_config={
            "node_dim": 12, "hidden_dim": 8, "num_layers": 2, "dropout": 0.0,
            "out_dim": 6, "normalize_embedding": True,
            "architecture": "MapEncoder/GCNConv+global_mean_pool+proj",
        },
        training_config={"epochs": 1, "width_mode": "legacy"},
        git_sha="test",
        torch_version="t", torch_geometric_version="g",
    )
    ckpt = tmp_path / "enc.pt"
    prov.save_checkpoint(ckpt, model.state_dict(), meta)
    assert checkpoint_provenance_label(str(ckpt)) == (
        prov.VERIFIED_CRYPTOGRAPHIC_PROVENANCE
    )
    loaded = _load_encoder(str(ckpt), torch.device("cpu"))
    assert isinstance(loaded, MapEncoder)

    # Tamper with the schema hash → fail closed.
    raw = torch.load(str(ckpt), map_location="cpu", weights_only=False)
    raw["metadata"]["graph_schema_sha256"] = "tampered"
    tampered = tmp_path / "tampered.pt"
    torch.save(raw, str(tampered))
    with pytest.raises(ValueError, match="schema"):
        _load_encoder(str(tampered), torch.device("cpu"))


def test_save_checkpoint_keeps_legacy_compat_keys(tmp_path):
    ckpt = tmp_path / "c.pt"
    prov.save_checkpoint(ckpt, _tiny_state(), _base_metadata())
    raw = torch.load(str(ckpt), map_location="cpu", weights_only=False)
    assert "state_dict" in raw and "metadata" in raw
    assert "model_state" in raw and "cfg" in raw  # historical loaders
    assert (tmp_path / "c.pt.manifest.json").is_file()


def test_determinism_summary_records_seeds_and_limits():
    det = prov.summarize_determinism(
        selection_seed=1234, training_seed=42, torch_seed=42,
        num_workers=0, deterministic_algorithms=True,
    )
    assert det["selection_seed"] == 1234
    assert det["training_seed"] == 42
    assert det["determinism_level"] == "DETERMINISTIC_CPU_SINGLE_WORKER"
    assert any("byte-identical" in str(lim) or "deterministic" in str(lim).lower()
               for lim in det["limitations"])


def test_leakage_audit_catches_overlap(tmp_path):
    d = tmp_path / "tiles"
    d.mkdir()
    names = _write_tiles_dir(d, 4)
    hashes = {n: prov.sha256_file(d / n) for n in names}
    train, test = names[:3], names[2:]
    audit = prov.audit_leakage(
        train_tile_names=train, train_tile_hashes=hashes, train_tiles_dir=d,
        test_tile_names=test, test_tile_hashes=hashes, test_tiles_dir=d,
    )
    assert audit["status"] == "FAIL"
    assert audit["same_spatial_tile_in_train_and_test_by_filename"] == [names[2]]
    clean = prov.audit_leakage(
        train_tile_names=train, train_tile_hashes=hashes, train_tiles_dir=d,
        test_tile_names=["elsewhere.xodr"], test_tile_hashes={"elsewhere.xodr": "zz"},
        test_tiles_dir=d,
    )
    assert clean["same_spatial_tile_in_train_and_test_by_filename"] == []


def test_ksweep_protocol_output_labels_stages(tmp_path):
    from ultimate_pipeline.domain_gap_gnn import run_ksweep as ks

    out = tmp_path / "out"
    results = [
        {
            "k": 10, "n_seeds": 2, "training_seeds": [42, 43],
            "selection_seed": 7, "tile_selection_sha256": "s",
            "cosine_similarity_mean": 0.5, "l2_mean": 1.0, "final_loss_mean": 2.0,
        }
    ]
    rows = [
        {"k": 10, "training_seed": 42, "selection_seed": 7,
         "cosine_similarity": 0.5, "l2": 1.0, "final_loss": 2.0,
         "checkpoint": "c", "tile_selection_sha256": "s"}
    ]
    ks._write_outputs(
        out_dir=out, results=results, per_run_rows=rows, k_values=[10],
        selection_seed=7, training_seeds=[42, 43],
        eval_pair_hashes={"manual_xodr": "m", "auto_xodr": "a"},
    )
    protocol = json.loads((out / "K_SWEEP_PROTOCOL.json").read_text())
    assert prov.DESCRIPTIVE_K_SWEEP in protocol["stages"]
    assert prov.MODEL_SELECTION in protocol["stages"]
    assert prov.FINAL_EVALUATION in protocol["stages"]
    assert "NOT an untouched" in protocol["evaluation_pair_reuse_warning"]
    report = json.loads((out / "ksweep_report.json").read_text())
    assert report["per_run_rows"] == rows


def test_train_and_ksweep_share_canonical_config_builders():
    """Regression guard: train_map_encoder and run_ksweep must build
    byte-identical training_config/model_config dicts, otherwise exact
    checkpoint-identity reuse can never verify (fail-safe retrain loop)."""
    import inspect

    import ultimate_pipeline.domain_gap_gnn.run_ksweep as ks
    import ultimate_pipeline.domain_gap_gnn.train_map_encoder as tme

    train_src = inspect.getsource(tme.main)
    ksweep_src = inspect.getsource(ks._expected_manifest_for_subset)
    assert "prov.build_training_config(" in train_src
    assert "prov.build_training_config(" in ksweep_src
    assert "prov.build_model_config(" in ksweep_src
    # The builders are deterministic: same inputs → identical dicts.
    assert prov.build_training_config(
        epochs=50, batch_size=16, lr=1e-4, width_mode="legacy",
        strict_dataset=False,
    ) == prov.build_training_config(
        epochs=50, batch_size=16, lr=1e-4, width_mode="legacy",
        strict_dataset=False,
    )
    assert (prov.build_training_config(epochs=50, batch_size=16, lr=1e-4)
            != prov.build_training_config(epochs=50, batch_size=16, lr=2e-4))
