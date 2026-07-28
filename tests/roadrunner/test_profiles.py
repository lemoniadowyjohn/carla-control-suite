from __future__ import annotations

from pathlib import Path

import pytest

import yaml


PROFILES_DIR = Path(__file__).resolve().parents[2] / "roadrunner_profiles"


@pytest.fixture
def profile_paths() -> list[Path]:
    return sorted(PROFILES_DIR.glob("*.yaml"))


class TestProfileStructure:
    def test_profiles_directory_exists(self) -> None:
        assert PROFILES_DIR.is_dir()

    def test_all_profiles_are_yaml(self, profile_paths: list[Path]) -> None:
        assert len(profile_paths) >= 5

    def test_each_profile_is_valid_yaml(self, profile_paths: list[Path]) -> None:
        for path in profile_paths:
            with open(str(path), "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{path.name} is not a YAML mapping"

    def test_each_profile_has_required_fields(self, profile_paths: list[Path]) -> None:
        required = {
            "required_tools",
            "minimum_capability_checks",
            "import_export_format",
            "expected_outputs",
            "required_gates",
            "optional_gates",
            "authority_class",
            "carla_compatibility_status",
            "release_prohibition_conditions",
        }
        for path in profile_paths:
            with open(str(path), "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            missing = required - set(data.keys())
            assert not missing, f"{path.name} missing fields: {missing}"

    def test_required_tools_is_list(self, profile_paths: list[Path]) -> None:
        for path in profile_paths:
            with open(str(path), "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert isinstance(data["required_tools"], list)

    def test_required_gates_is_list(self, profile_paths: list[Path]) -> None:
        for path in profile_paths:
            with open(str(path), "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert isinstance(data["required_gates"], list)

    def test_optional_gates_is_list(self, profile_paths: list[Path]) -> None:
        for path in profile_paths:
            with open(str(path), "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert isinstance(data["optional_gates"], list)


class TestSpecificProfiles:
    def test_reference_only_never_releases(self) -> None:
        path = PROFILES_DIR / "reference_only.yaml"
        with open(str(path), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "always" in data["release_prohibition_conditions"]

    def test_carla_0913_datasmith_is_experimental(self) -> None:
        path = PROFILES_DIR / "carla_0913_datasmith_experimental.yaml"
        with open(str(path), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "UnrealEngine" in data["required_tools"]
        assert "Datasmith" in data["required_tools"]
        assert data["carla_compatibility_status"] == "unknown"

    def test_carla_0916_fbx_xodr_is_compliant(self) -> None:
        path = PROFILES_DIR / "carla_0916_fbx_xodr.yaml"
        with open(str(path), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "CARLA_0916" in data["required_tools"]
        assert data["carla_compatibility_status"] == "compliant"

    def test_large_map_tiled_checks_alignment(self) -> None:
        path = PROFILES_DIR / "large_map_tiled.yaml"
        with open(str(path), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "tile_alignment" in data["minimum_capability_checks"]
        assert "tile_misalignment" in data["release_prohibition_conditions"]

    def test_xodr_roundtrip_requires_xodr_exporter(self) -> None:
        path = PROFILES_DIR / "xodr_roundtrip.yaml"
        with open(str(path), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "xodr_exporter" in data["minimum_capability_checks"]
        assert data["carla_compatibility_status"] == "high"
