"""C16 step 1-2 — semantic_tagging.py: mesh classification + fail-closed gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ultimate_pipeline.enrichment.semantic_tagging import (
    CITY_OBJECT_LABELS,
    STATIC_SCENERY_LABELS,
    classify_mesh,
    classify_mesh_or_material_name,
    tag_mesh_inventory,
    validate_semantic_tags,
)


def test_city_object_labels_match_real_carla_enum() -> None:
    """Ground-truth check: our hardcoded table must match the actual
    installed carla.CityObjectLabel enum exactly, not drift from it."""
    carla = pytest.importorskip("carla")
    real = {}
    for name in dir(carla.CityObjectLabel):
        if name.startswith("_"):
            continue
        try:
            real[name] = int(getattr(carla.CityObjectLabel, name))
        except Exception:
            continue
    assert real.get("NONE") == 0
    assert real.get("Any") == 255
    for name, value in CITY_OBJECT_LABELS.items():
        assert real.get(name) == value, f"{name}: expected {value}, real carla enum has {real.get(name)}"


@pytest.mark.parametrize("name,expected", [
    ("Road_asphalt_01", "Roads"),
    ("Building_wall_north", "Buildings"),  # "building" must win over generic "wall"
    ("Tree_broadleaf_large", "Vegetation"),
    ("Sidewalk_curb_02", "Sidewalks"),
    ("StreetLamp_pole", "Poles"),
    ("TrafficLight_head_red", "TrafficLight"),
    ("TrafficSign_speed_limit_30", "TrafficSigns"),
    ("GuardRail_segment_04", "GuardRail"),
    ("RailTrack_ballast", "RailTrack"),
    ("River_water_surface", "Water"),
    ("Bridge_deck_concrete", "Bridge"),
    ("Meadow_terrain_patch", "Terrain"),
    ("Gravel_ground_area", "Ground"),
])
def test_classify_positive_controls(name: str, expected: str) -> None:
    assert classify_mesh_or_material_name(name) == expected


def test_classify_negative_control_no_match_returns_none() -> None:
    assert classify_mesh_or_material_name("Xyzzy_Unknown_Prop_47") is None


def test_classify_order_sensitivity_guardrail_before_rail() -> None:
    assert classify_mesh_or_material_name("GuardRailBarrier") == "GuardRail"


def test_classify_order_sensitivity_roadline_before_road() -> None:
    assert classify_mesh_or_material_name("RoadLine_dashed_white") == "RoadLines"


def test_classify_mesh_falls_back_to_material_when_name_unmatched() -> None:
    mesh = {"name": "Object_017", "materials": ["Unknown_Mat", "OSM2World_Building_Wall"]}
    result = classify_mesh(mesh)
    assert result["label"] == "Buildings"
    assert result["matched_via"].startswith("material:")


def test_classify_mesh_prefers_name_over_material() -> None:
    mesh = {"name": "Road_segment_01", "materials": ["Building_facade"]}
    result = classify_mesh(mesh)
    assert result["label"] == "Roads"
    assert result["matched_via"] == "name"


def test_tag_mesh_inventory_matches_fbx_roundtrip_object_shape() -> None:
    # Same shape as fbx_roundtrip.py's ROUNDTRIP_SCRIPT_TEMPLATE inventory entries.
    objects = [
        {"name": "Road_main_01", "type": "MESH", "vertices": 4, "faces": 2,
         "uv_layers": 1, "materials": ["Asphalt"], "bounds": []},
        {"name": "Building_02", "type": "MESH", "vertices": 8, "faces": 6,
         "uv_layers": 1, "materials": ["Concrete_Wall"], "bounds": []},
    ]
    report = tag_mesh_inventory(objects)
    assert report["mesh_count"] == 2
    assert report["unmatched_count"] == 0


def test_validate_semantic_tags_positive_control_all_matched() -> None:
    report = tag_mesh_inventory([
        {"name": "Road_01", "materials": []},
        {"name": "Sidewalk_02", "materials": []},
    ])
    result = validate_semantic_tags(report)
    assert result["ok"] is True
    assert result["verdict"] == "SEMANTIC_TAGS_OK"


def test_validate_semantic_tags_negative_control_one_unmatched_fails() -> None:
    report = tag_mesh_inventory([
        {"name": "Road_01", "materials": []},
        {"name": "Mystery_Object_99", "materials": ["Unknown_Material"]},
    ])
    result = validate_semantic_tags(report)
    assert result["ok"] is False
    assert "Mystery_Object_99" in result["unmatched_meshes"]
    assert result["verdict"] == "SEMANTIC_TAGS_INCOMPLETE"


def test_validate_semantic_tags_negative_control_empty_inventory_fails() -> None:
    """Zero tagged meshes on a real cook is itself a defect, not a pass."""
    report = tag_mesh_inventory([])
    result = validate_semantic_tags(report)
    assert result["ok"] is False


def test_static_scenery_labels_excludes_dynamic_actors() -> None:
    assert "Car" not in STATIC_SCENERY_LABELS
    assert "Pedestrians" not in STATIC_SCENERY_LABELS
    assert "Roads" in STATIC_SCENERY_LABELS
    assert "Buildings" in STATIC_SCENERY_LABELS


def test_none_and_any_excluded_from_assignable_labels() -> None:
    assert 0 not in CITY_OBJECT_LABELS.values()
    assert 255 not in CITY_OBJECT_LABELS.values()
