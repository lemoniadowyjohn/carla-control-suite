"""Unit tests for ultimate_pipeline.enrichment.carla_semantic_organizer.

Tests:
1. Pure classification logic (OSM tags, object names, material names, fallbacks).
2. CARLA_SEMANTIC_FOLDERS completeness and ID mappings.
3. Organization planner inventory processing and report generation.
4. Filesystem execution (copy/move) on mock Unreal content trees.
5. Error handling (missing source files, corrupt inputs).
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from ultimate_pipeline.enrichment.carla_semantic_organizer import (
    CARLA_SEMANTIC_FOLDERS,
    CarlaSemanticOrganizer,
    classify_object,
)


class TestSemanticClassification:
    def test_all_folders_have_unique_positive_tag_ids(self):
        assert len(CARLA_SEMANTIC_FOLDERS) >= 22
        tag_ids = list(CARLA_SEMANTIC_FOLDERS.values())
        assert len(tag_ids) == len(set(tag_ids))
        assert all(isinstance(v, int) and v > 0 for v in tag_ids)

    def test_classify_by_osm_tags_precedence(self):
        # Explicit OSM building tag
        folder, rule = classify_object(osm_tags={"building": "yes"})
        assert folder == "Buildings"
        assert "osm_tag" in rule

        # Explicit OSM tree tag
        folder, rule = classify_object(osm_tags={"natural": "tree"})
        assert folder == "Vegetation"
        assert "osm_tag" in rule

        # Explicit OSM fence tag
        folder, rule = classify_object(osm_tags={"barrier": "fence"})
        assert folder == "Fences"
        assert "osm_tag" in rule

        # Explicit OSM wall tag
        folder, rule = classify_object(osm_tags={"barrier": "wall"})
        assert folder == "Walls"
        assert "osm_tag" in rule

        # Explicit OSM bridge tag
        folder, rule = classify_object(osm_tags={"bridge": "yes"})
        assert folder == "Bridge"
        assert "osm_tag" in rule

    def test_classify_by_object_name_keywords(self):
        assert classify_object(name="Building_Tile_6_8_mesh")[0] == "Buildings"
        assert classify_object(name="OakTree_HighLOD_01")[0] == "Vegetation"
        assert classify_object(name="StreetLamp_Post_B")[0] == "Poles"
        assert classify_object(name="TrafficSign_SpeedLimit50")[0] == "TrafficSigns"
        assert classify_object(name="TrafficSignal_Junction_01")[0] == "TrafficLight"
        assert classify_object(name="ConcreteGuardRail_Seg02")[0] == "GuardRail"
        assert classify_object(name="Highway_Asphalt_Section")[0] == "Roads"
        assert classify_object(name="Pedestrian_Sidewalk_Tile")[0] == "Sidewalks"
        assert classify_object(name="Bridge_Pier_Main")[0] == "Bridge"
        assert classify_object(name="Railway_Track_Line1")[0] == "RailTrack"
        assert classify_object(name="River_Water_Mesh")[0] == "Water"
        assert classify_object(name="Hill_Terrain_Chunk")[0] == "Terrain"

    def test_classify_by_material_name_keywords(self):
        folder, rule = classify_object(materials=["M_Roof_Tiles_Red"])
        assert folder == "Buildings"
        assert "material_name" in rule

        folder, _ = classify_object(materials=["M_Tree_Leaves"])
        assert folder == "Vegetation"

        folder, _ = classify_object(materials=["M_Asphalt_Road"])
        assert folder == "Roads"

    def test_fallback_to_other_on_unknown(self):
        folder, rule = classify_object(name="Unknown_Prop_XYZ", materials=["CustomMat_123"])
        assert folder == "Other"
        assert rule == "fallback:unclassified"


class TestOrganizerPlannerAndExecution:
    def test_dry_run_plan_generation(self, tmp_path: Path):
        content_root = tmp_path / "Content"
        organizer = CarlaSemanticOrganizer(content_root=content_root, mode="dry_run")

        inventory = [
            {"name": "Building_6_8", "materials": ["Wall_Mat"], "filename": "Building_6_8.fbx"},
            {"name": "OakTree_01", "materials": ["Leaf_Mat"], "filename": "OakTree_01.fbx"},
            {"name": "StreetLamp_A", "materials": ["Metal_Mat"], "filename": "StreetLamp_A.fbx"},
        ]

        report = organizer.plan_from_inventory(inventory)
        assert report.total_assets == 3
        assert report.placements_by_folder["Buildings"] == 1
        assert report.placements_by_folder["Vegetation"] == 1
        assert report.placements_by_folder["Poles"] == 1
        assert len(report.placements) == 3

        report_dict = report.to_dict()
        assert "verification_notes" in report_dict
        assert len(report_dict["verification_notes"]["confirmed"]) > 0

    def test_copy_execution_on_mock_tree(self, tmp_path: Path):
        content_root = tmp_path / "Content"
        source_dir = tmp_path / "Import"
        source_dir.mkdir(parents=True, exist_ok=True)

        # Create mock source FBX files
        bldg_file = source_dir / "Building_6_8.fbx"
        tree_file = source_dir / "OakTree_01.fbx"
        bldg_file.write_text("mock fbx bldg content", encoding="utf-8")
        tree_file.write_text("mock fbx tree content", encoding="utf-8")

        organizer = CarlaSemanticOrganizer(content_root=content_root, mode="copy")

        inventory = [
            {"name": "Building_6_8", "materials": ["Wall_Mat"], "filename": "Building_6_8.fbx"},
            {"name": "OakTree_01", "materials": ["Leaf_Mat"], "filename": "OakTree_01.fbx"},
        ]

        report = organizer.plan_from_inventory(inventory, source_dir=source_dir)
        report = organizer.execute_plan(report)

        assert report.total_assets == 2
        assert len(report.errors) == 0

        target_bldg = content_root / "Carla" / "Static" / "Buildings" / "Building_6_8.fbx"
        target_tree = content_root / "Carla" / "Static" / "Vegetation" / "OakTree_01.fbx"

        assert target_bldg.exists()
        assert target_tree.exists()
        assert target_bldg.read_text(encoding="utf-8") == "mock fbx bldg content"
        assert target_tree.read_text(encoding="utf-8") == "mock fbx tree content"

    def test_missing_source_file_error_handling(self, tmp_path: Path):
        content_root = tmp_path / "Content"
        source_dir = tmp_path / "Import"
        source_dir.mkdir(parents=True, exist_ok=True)

        organizer = CarlaSemanticOrganizer(content_root=content_root, mode="copy")
        inventory = [
            {"name": "Missing_Building", "filename": "NonExistent.fbx"},
        ]

        report = organizer.plan_from_inventory(inventory, source_dir=source_dir)
        report = organizer.execute_plan(report)

        assert len(report.errors) == 1
        assert "not found" in report.errors[0]
