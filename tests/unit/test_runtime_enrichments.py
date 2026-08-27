"""ultimate_pipeline/carla_tools/runtime_enrichments.py -- shared type-normalization and
deterministic-sampling logic for runtime scene enrichments (buildings/trees/poles/etc.),
used by run_perception_pair.py and run_perception_safe.py. This pass covers only the pure,
CARLA-free functions (type alias normalization, required-type gap detection, filter+sample);
spawn_runtime_enrichments/destroy_runtime_enrichments/capture_qa_bundle are CARLA-dependent
and out of scope, matching this sweep's established pattern. Found untested via the
orphaned-.pyc sweep.
"""
from __future__ import annotations

import json
from pathlib import Path

from ultimate_pipeline.carla_tools.runtime_enrichments import (
    CANONICAL_REQUIRED_TYPES,
    compute_missing_required_types,
    load_and_sample_enrichments,
    normalize_enrichment_object,
    normalize_enrichment_type,
    parse_type_filter,
)


# ---------------------------------------------------------------------------
# normalize_enrichment_type
# ---------------------------------------------------------------------------

def test_normalize_empty_defaults_to_building():
    assert normalize_enrichment_type("") == "building"
    assert normalize_enrichment_type(None) == "building"


def test_normalize_known_alias_maps_to_canonical():
    assert normalize_enrichment_type("street_light") == "pole"
    assert normalize_enrichment_type("trashcan") == "bin"
    assert normalize_enrichment_type("fence") == "barrier"


def test_normalize_is_case_and_separator_insensitive():
    assert normalize_enrichment_type("Street-Light") == "pole"
    assert normalize_enrichment_type("STREET LIGHT") == "pole"


def test_normalize_strips_leading_trailing_underscores():
    assert normalize_enrichment_type("__pole__") == "pole"


def test_normalize_unknown_type_passed_through_unchanged():
    assert normalize_enrichment_type("some_novel_type") == "some_novel_type"


def test_normalize_dashes_become_underscores_before_alias_lookup():
    assert normalize_enrichment_type("light-pole") == "pole"


# ---------------------------------------------------------------------------
# parse_type_filter
# ---------------------------------------------------------------------------

def test_parse_type_filter_none_or_empty_returns_none():
    assert parse_type_filter("") is None
    assert parse_type_filter(None) is None


def test_parse_type_filter_splits_and_normalizes_comma_list():
    result = parse_type_filter("tree, Street-Light, unknown_thing")
    assert result == {"tree", "pole", "unknown_thing"}


def test_parse_type_filter_ignores_blank_tokens():
    result = parse_type_filter("tree,,  ,pole")
    assert result == {"tree", "pole"}


# ---------------------------------------------------------------------------
# normalize_enrichment_object
# ---------------------------------------------------------------------------

def test_normalize_object_uses_type_key_when_normalized_type_absent():
    obj = normalize_enrichment_object({"type": "street_tree"})
    assert obj["normalized_type"] == "tree"
    assert obj["type"] == "tree"
    assert obj["object_type"] == "tree"


def test_normalize_object_prefers_normalized_type_over_type():
    obj = normalize_enrichment_object({"normalized_type": "pole", "type": "building"})
    assert obj["normalized_type"] == "pole"
    assert obj["type"] == "pole"


def test_normalize_object_falls_back_to_object_type_key():
    obj = normalize_enrichment_object({"object_type": "bench"})
    assert obj["normalized_type"] == "bench"


def test_normalize_object_defaults_to_building_when_no_type_keys_present():
    obj = normalize_enrichment_object({"id": 1})
    assert obj["normalized_type"] == "building"


def test_normalize_object_preserves_other_fields():
    obj = normalize_enrichment_object({"type": "tree", "x": 1.0, "y": 2.0})
    assert obj["x"] == 1.0
    assert obj["y"] == 2.0


# ---------------------------------------------------------------------------
# compute_missing_required_types
# ---------------------------------------------------------------------------

def test_missing_required_types_none_required_returns_empty():
    assert compute_missing_required_types([{"type": "tree"}], None) == []


def test_missing_required_types_all_present_returns_empty():
    enrichments = [{"normalized_type": "building"}, {"normalized_type": "tree"}]
    assert compute_missing_required_types(enrichments, {"building", "tree"}) == []


def test_missing_required_types_reports_absent_ones_sorted():
    enrichments = [{"normalized_type": "building"}]
    missing = compute_missing_required_types(enrichments, {"building", "tree", "pole"})
    assert missing == ["pole", "tree"]


def test_missing_required_types_normalizes_aliases_before_comparing():
    # enrichment uses the raw alias "street_light"; required set uses the canonical "pole"
    enrichments = [{"type": "street_light"}]
    assert compute_missing_required_types(enrichments, {"pole"}) == []


def test_missing_required_types_against_full_canonical_set(tmp_path: Path):
    enrichments = [{"normalized_type": t} for t in CANONICAL_REQUIRED_TYPES]
    assert compute_missing_required_types(enrichments, CANONICAL_REQUIRED_TYPES) == []


# ---------------------------------------------------------------------------
# load_and_sample_enrichments
# ---------------------------------------------------------------------------

def _write_enrichments(path: Path, items) -> None:
    path.write_text(json.dumps(items), encoding="utf-8")


def test_load_and_sample_no_filter_no_limit_returns_all(tmp_path: Path, monkeypatch):
    path = tmp_path / "enrich.json"
    items = [{"type": "tree"}, {"type": "building"}]
    _write_enrichments(path, items)
    import ultimate_pipeline.carla_tools.runtime_enrichments as mod
    monkeypatch.setattr(mod.enrich_mod, "load_enrichments", lambda p: json.loads(Path(p).read_text()))

    enrichments, summary = load_and_sample_enrichments(str(path), limit=0)

    assert summary["total_loaded"] == 2
    assert summary["filtered_count"] == 2
    assert len(enrichments) == 2


def test_load_and_sample_filters_by_type(tmp_path: Path, monkeypatch):
    path = tmp_path / "enrich.json"
    items = [{"type": "tree"}, {"type": "building"}, {"type": "pole"}]
    _write_enrichments(path, items)
    import ultimate_pipeline.carla_tools.runtime_enrichments as mod
    monkeypatch.setattr(mod.enrich_mod, "load_enrichments", lambda p: json.loads(Path(p).read_text()))

    enrichments, summary = load_and_sample_enrichments(str(path), limit=0, type_filter={"tree", "pole"})

    assert summary["filtered_count"] == 2
    assert {e["normalized_type"] for e in enrichments} == {"tree", "pole"}


def test_load_and_sample_deterministic_across_repeated_calls(tmp_path: Path, monkeypatch):
    path = tmp_path / "enrich.json"
    items = [{"type": "tree", "id": i} for i in range(20)]
    _write_enrichments(path, items)
    import ultimate_pipeline.carla_tools.runtime_enrichments as mod
    monkeypatch.setattr(mod.enrich_mod, "load_enrichments", lambda p: json.loads(Path(p).read_text()))

    enrichments_a, _ = load_and_sample_enrichments(str(path), limit=5, seed=42)
    enrichments_b, _ = load_and_sample_enrichments(str(path), limit=5, seed=42)

    assert [e["id"] for e in enrichments_a] == [e["id"] for e in enrichments_b]
    assert len(enrichments_a) == 5


def test_load_and_sample_different_seeds_can_differ(tmp_path: Path, monkeypatch):
    path = tmp_path / "enrich.json"
    items = [{"type": "tree", "id": i} for i in range(50)]
    _write_enrichments(path, items)
    import ultimate_pipeline.carla_tools.runtime_enrichments as mod
    monkeypatch.setattr(mod.enrich_mod, "load_enrichments", lambda p: json.loads(Path(p).read_text()))

    enrichments_a, _ = load_and_sample_enrichments(str(path), limit=5, seed=1)
    enrichments_b, _ = load_and_sample_enrichments(str(path), limit=5, seed=2)

    assert [e["id"] for e in enrichments_a] != [e["id"] for e in enrichments_b]


def test_load_and_sample_limit_larger_than_available_returns_all(tmp_path: Path, monkeypatch):
    path = tmp_path / "enrich.json"
    items = [{"type": "tree"}, {"type": "building"}]
    _write_enrichments(path, items)
    import ultimate_pipeline.carla_tools.runtime_enrichments as mod
    monkeypatch.setattr(mod.enrich_mod, "load_enrichments", lambda p: json.loads(Path(p).read_text()))

    enrichments, summary = load_and_sample_enrichments(str(path), limit=1000)

    assert len(enrichments) == 2
    assert summary["sampled_count"] == 2


def test_load_and_sample_per_type_counts(tmp_path: Path, monkeypatch):
    path = tmp_path / "enrich.json"
    items = [{"type": "tree"}, {"type": "tree"}, {"type": "building"}]
    _write_enrichments(path, items)
    import ultimate_pipeline.carla_tools.runtime_enrichments as mod
    monkeypatch.setattr(mod.enrich_mod, "load_enrichments", lambda p: json.loads(Path(p).read_text()))

    _, summary = load_and_sample_enrichments(str(path), limit=0)

    assert summary["per_type_counts"] == {"tree": 2, "building": 1}
