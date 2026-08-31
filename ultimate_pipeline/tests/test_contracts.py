"""
Tests for contracts module.

These tests verify:
- ExperimentConfigModel parsing and validation
- AgentSyncContract loading and validation
- RunArtifacts directory management
- run_id generation
"""

import json
import tempfile
from pathlib import Path

import pytest


class TestExperimentConfigModel:
    """Tests for ExperimentConfigModel."""

    def test_minimal_config(self):
        """Test creation with minimal required fields."""
        from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel

        config = ExperimentConfigModel(experiment_id="test_exp")

        assert config.experiment_id == "test_exp"
        # seed defaults to 0 (for reproducibility), not None
        assert config.seed == 0
        assert config.carla.host == "127.0.0.1"
        assert config.carla.port == 2000

    def test_config_hash_deterministic(self):
        """Test that config_hash is deterministic."""
        from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel

        config1 = ExperimentConfigModel(experiment_id="test", seed=42)
        config2 = ExperimentConfigModel(experiment_id="test", seed=42)

        assert config1.config_hash() == config2.config_hash()

    def test_config_hash_differs_on_change(self):
        """Test that config_hash changes with config changes."""
        from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel

        config1 = ExperimentConfigModel(experiment_id="test", seed=42)
        config2 = ExperimentConfigModel(experiment_id="test", seed=43)

        assert config1.config_hash() != config2.config_hash()

    def test_apply_overrides(self):
        """Test applying CLI overrides."""
        from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel

        config = ExperimentConfigModel(experiment_id="test")
        updated = config.apply_overrides({"seed": 123, "carla.port": 2001})

        assert updated.seed == 123
        assert updated.carla.port == 2001
        # Original unchanged
        assert config.seed == 0  # Default seed is 0

    def test_to_yaml(self):
        """Test YAML serialization."""
        from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel

        config = ExperimentConfigModel(experiment_id="test", seed=42)
        yaml_str = config.to_yaml()

        assert "experiment_id: test" in yaml_str
        assert "seed: 42" in yaml_str

    def test_load_from_yaml(self):
        """Test loading config from YAML file."""
        from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("experiment_id: loaded_test\nseed: 99\n")
            f.flush()

            config = ExperimentConfigModel.load(f.name)

        assert config.experiment_id == "loaded_test"
        assert config.seed == 99

        Path(f.name).unlink()


class TestAgentSyncContract:
    """Tests for AgentSyncContract."""

    def test_default_bbox(self):
        """Test default bbox values match thesis spec."""
        from ultimate_pipeline.contracts.agent_sync import AgentSyncContract

        contract = AgentSyncContract()

        # Verify exact Ingolstadt bbox values
        assert contract.bbox.lat_min == pytest.approx(48.74935649548228)
        assert contract.bbox.lat_max == pytest.approx(48.77444431571603)
        assert contract.bbox.lon_min == pytest.approx(11.422268084715878)
        assert contract.bbox.lon_max == pytest.approx(11.47882091528412)

    def test_sensor_rig_defaults(self):
        """Test sensor rig contract defaults."""
        from ultimate_pipeline.contracts.agent_sync import AgentSyncContract

        contract = AgentSyncContract()

        assert contract.sensor_rig.use_K_undistortion is True
        assert contract.sensor_rig.ignore_K is True
        assert contract.sensor_rig.ignore_D is True
        assert contract.sensor_rig.ctv_inverted is False
        assert contract.sensor_rig.vtl_inverted is True

    def test_determinism_defaults(self):
        """Test determinism contract defaults."""
        from ultimate_pipeline.contracts.agent_sync import AgentSyncContract

        contract = AgentSyncContract()

        assert contract.determinism.min_runs == 5
        assert contract.determinism.preferred_runs == 10
        assert "xodr_sha256" in contract.determinism.required_signature_fields

    def test_save_and_load(self):
        """Test round-trip save/load."""
        from ultimate_pipeline.contracts.agent_sync import AgentSyncContract, load_agent_sync

        contract = AgentSyncContract()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "agent_sync.yaml"
            contract.save(path)

            loaded = load_agent_sync(path)

        assert loaded.version == contract.version
        assert loaded.bbox.lat_min == contract.bbox.lat_min

    def test_validate_agent_sync_missing_file(self):
        """Test validation with missing file."""
        from ultimate_pipeline.contracts.agent_sync import validate_agent_sync

        result = validate_agent_sync(path="/nonexistent/path.yaml")

        assert result["valid"] is False
        # Error message contains the path or "No such file"
        assert len(result["errors"]) > 0
        error_text = " ".join(result["errors"]).lower()
        assert "nonexistent" in error_text or "no such file" in error_text or "no agent_sync" in error_text


class TestRunArtifacts:
    """Tests for RunArtifacts."""

    def test_create_run_id_format(self):
        """Test run_id format."""
        from ultimate_pipeline.contracts.artifacts import create_run_id

        run_id = create_run_id(
            config_hash="abcdef123456",
            experiment_id="test_exp",
        )

        # Format: {timestamp}_{git_sha}_{config_hash}_{experiment_id}
        parts = run_id.split("_")
        assert len(parts) >= 4
        # First part is date YYYYMMDD
        assert len(parts[0]) == 8
        assert parts[0].isdigit()

    def test_run_artifacts_directories(self):
        """Test directory creation."""
        from ultimate_pipeline.contracts.artifacts import RunArtifacts

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = RunArtifacts(
                run_id="test_run_123",
                artifact_root=tmpdir,
            )
            artifacts.ensure_directories()

            assert artifacts.run_dir.exists()
            assert artifacts.logs_dir.exists()
            assert artifacts.repro_dir.exists()

    def test_write_config(self):
        """Test config writing."""
        from ultimate_pipeline.contracts.artifacts import RunArtifacts
        from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = RunArtifacts(
                run_id="test_run",
                artifact_root=tmpdir,
            )

            config = ExperimentConfigModel(experiment_id="test")
            path = artifacts.write_config(config)

            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "experiment_id" in content

    def test_write_metrics(self):
        """Test metrics writing."""
        from ultimate_pipeline.contracts.artifacts import RunArtifacts

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = RunArtifacts(
                run_id="test_run",
                artifact_root=tmpdir,
            )

            metrics = {"accuracy": 0.95, "loss": 0.05}
            path = artifacts.write_metrics(metrics)

            assert path.exists()
            loaded = json.loads(path.read_text(encoding="utf-8"))
            assert loaded["accuracy"] == 0.95

    def test_finalize(self):
        """Test run finalization."""
        from ultimate_pipeline.contracts.artifacts import RunArtifacts

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = RunArtifacts(
                run_id="test_run",
                artifact_root=tmpdir,
            )
            artifacts.ensure_directories()

            result = artifacts.finalize(
                success=True,
                experiment_id="test_exp",
                metrics={"score": 100},
                duration_s=10.5,
            )

            assert result["success"] is True
            assert artifacts.summary_json_path.exists()
            assert artifacts.summary_md_path.exists()


class TestReleaseProfilePolicy:
    """Tests for release profile resolution and unsafe-feature gating.

    Verifies that unsafe operations require BOTH explicit opt-in AND
    profile permission — never profile permission alone.
    """

    # ------------------------------------------------------------------
    # unsafe_lanelink_regen_enabled
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("profile", "settings_enabled", "env_value", "expected"),
        [
            ("structural_release", False, None, False),
            ("structural_release", True, None, False),
            ("structural_release", False, "true", False),
            ("debug", False, None, False),
            ("debug", True, None, True),
            ("debug", False, "true", True),
            ("debug", True, "false", False),
            ("visual_build", True, None, False),
            ("scenario_augmentation", True, None, False),
            ("", True, None, False),
            ("unknown-profile", True, None, False),
        ],
    )
    def test_lanelink_regeneration_policy(
        self,
        monkeypatch,
        profile,
        settings_enabled,
        env_value,
        expected,
    ):
        from ultimate_pipeline.contracts.release_profile import unsafe_lanelink_regen_enabled

        class Settings:
            RELEASE_PROFILE = profile
            ENABLE_LANELINK_REGEN = settings_enabled

        if env_value is None:
            monkeypatch.delenv("UP_ENABLE_LANELINK_REGEN", raising=False)
        else:
            monkeypatch.setenv("UP_ENABLE_LANELINK_REGEN", env_value)

        assert unsafe_lanelink_regen_enabled(Settings()) is expected

    def test_invalid_lanelink_env_fails_closed(self, monkeypatch):
        from ultimate_pipeline.contracts.release_profile import unsafe_lanelink_regen_enabled

        class Settings:
            RELEASE_PROFILE = "debug"
            ENABLE_LANELINK_REGEN = False

        monkeypatch.setenv("UP_ENABLE_LANELINK_REGEN", "probably")
        with pytest.raises(ValueError):
            unsafe_lanelink_regen_enabled(Settings())

    # ------------------------------------------------------------------
    # unsafe_planview_mutations_enabled
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("profile", "settings_enabled", "env_value", "expected"),
        [
            ("structural_release", False, None, False),
            ("structural_release", True, None, False),
            ("structural_release", False, "true", False),
            ("debug", False, None, False),
            ("debug", True, None, True),
            ("debug", False, "true", True),
            ("debug", True, "false", False),
            ("visual_build", True, None, False),
            ("scenario_augmentation", True, None, False),
            ("", True, None, False),
            ("unknown-profile", True, None, False),
        ],
    )
    def test_planview_mutations_policy(
        self,
        monkeypatch,
        profile,
        settings_enabled,
        env_value,
        expected,
    ):
        from ultimate_pipeline.contracts.release_profile import unsafe_planview_mutations_enabled

        class Settings:
            RELEASE_PROFILE = profile
            ENABLE_UNSAFE_PLANVIEW_MUTATIONS = settings_enabled

        if env_value is None:
            monkeypatch.delenv("UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS", raising=False)
        else:
            monkeypatch.setenv("UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS", env_value)

        assert unsafe_planview_mutations_enabled(Settings()) is expected

    def test_invalid_planview_env_fails_closed(self, monkeypatch):
        from ultimate_pipeline.contracts.release_profile import unsafe_planview_mutations_enabled

        class Settings:
            RELEASE_PROFILE = "debug"
            ENABLE_UNSAFE_PLANVIEW_MUTATIONS = False

        monkeypatch.setenv("UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS", "nope")
        with pytest.raises(ValueError):
            unsafe_planview_mutations_enabled(Settings())

    # ------------------------------------------------------------------
    # stage_06_links.py / stage_05_geometry.py unsafe-mutation gates
    # (unsafe_short_segment_merge_enabled, unsafe_heading_only_smoothing_enabled,
    # unsafe_small_geometry_merge_enabled, unsafe_curvature_only_clamp_enabled,
    # straight_chord_connector_fallback_enabled) -- all route through the same
    # _unsafe_feature_enabled(settings_obj, attr, env) helper as the two policies
    # above, so they share the identical opt-in-AND-profile-permission matrix.
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("func_name", "attr", "env"),
        [
            (
                "unsafe_short_segment_merge_enabled",
                "ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
                "UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
            ),
            (
                "unsafe_heading_only_smoothing_enabled",
                "ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
                "UP_ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
            ),
            (
                "unsafe_small_geometry_merge_enabled",
                "ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE",
                "UP_ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE",
            ),
            (
                "unsafe_curvature_only_clamp_enabled",
                "ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP",
                "UP_ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP",
            ),
            (
                "straight_chord_connector_fallback_enabled",
                "ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
                "UP_ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
            ),
        ],
    )
    @pytest.mark.parametrize(
        ("profile", "settings_enabled", "env_value", "expected"),
        [
            ("structural_release", False, None, False),
            ("structural_release", True, None, False),
            ("structural_release", False, "true", False),
            ("debug", False, None, False),
            ("debug", True, None, True),
            ("debug", False, "true", True),
            ("debug", True, "false", False),
            ("visual_build", True, None, False),
            ("scenario_augmentation", True, None, False),
            ("experimental_unsafe", True, None, True),
            ("", True, None, False),
            ("unknown-profile", True, None, False),
        ],
    )
    def test_unsafe_geometry_mutation_gate_policy(
        self,
        monkeypatch,
        func_name,
        attr,
        env,
        profile,
        settings_enabled,
        env_value,
        expected,
    ):
        import ultimate_pipeline.contracts.release_profile as release_profile

        func = getattr(release_profile, func_name)

        class Settings:
            pass

        setattr(Settings, "RELEASE_PROFILE", profile)
        setattr(Settings, attr, settings_enabled)

        if env_value is None:
            monkeypatch.delenv(env, raising=False)
        else:
            monkeypatch.setenv(env, env_value)

        assert func(Settings()) is expected

    def test_unsafe_short_segment_merge_invalid_env_fails_closed(self, monkeypatch):
        from ultimate_pipeline.contracts.release_profile import (
            unsafe_short_segment_merge_enabled,
        )

        class Settings:
            RELEASE_PROFILE = "debug"
            ENABLE_UNSAFE_SHORT_SEGMENT_MERGE = False

        monkeypatch.setenv("UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE", "maybe")
        with pytest.raises(ValueError):
            unsafe_short_segment_merge_enabled(Settings())

    # ------------------------------------------------------------------
    # unsafe_geometry_start_recompute_enabled (legacy-flag compat shim)
    # ------------------------------------------------------------------

    def test_geometry_start_recompute_modern_flag_only(self, monkeypatch):
        from ultimate_pipeline.contracts.release_profile import (
            unsafe_geometry_start_recompute_enabled,
        )

        class Settings:
            RELEASE_PROFILE = "debug"
            ENABLE_GEOMETRY_START_RECOMPUTE = False
            ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE = True

        monkeypatch.delenv("UP_ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE", raising=False)
        assert unsafe_geometry_start_recompute_enabled(Settings()) is True

    def test_geometry_start_recompute_legacy_flag_maps_to_modern(self, monkeypatch):
        """Legacy ENABLE_GEOMETRY_START_RECOMPUTE=True (and modern flag unset)
        must still require profile permission -- opt-in alone is not enough."""
        from ultimate_pipeline.contracts.release_profile import (
            unsafe_geometry_start_recompute_enabled,
        )

        class SettingsUnsafeProfile:
            RELEASE_PROFILE = "debug"
            ENABLE_GEOMETRY_START_RECOMPUTE = True
            ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE = False

        class SettingsReleaseProfile:
            RELEASE_PROFILE = "structural_release"
            ENABLE_GEOMETRY_START_RECOMPUTE = True
            ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE = False

        monkeypatch.delenv("UP_ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE", raising=False)
        assert unsafe_geometry_start_recompute_enabled(SettingsUnsafeProfile()) is True
        assert unsafe_geometry_start_recompute_enabled(SettingsReleaseProfile()) is False

    def test_geometry_start_recompute_neither_flag_set(self, monkeypatch):
        from ultimate_pipeline.contracts.release_profile import (
            unsafe_geometry_start_recompute_enabled,
        )

        class Settings:
            RELEASE_PROFILE = "debug"
            ENABLE_GEOMETRY_START_RECOMPUTE = False
            ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE = False

        monkeypatch.delenv("UP_ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE", raising=False)
        assert unsafe_geometry_start_recompute_enabled(Settings()) is False

    def test_geometry_start_recompute_env_override_applies_under_legacy_shim(
        self, monkeypatch
    ):
        """Even when the legacy-shim branch fires, a live env override for the
        modern env var name must still be honored (it reads real os.environ,
        not the synthetic _Compat settings object)."""
        from ultimate_pipeline.contracts.release_profile import (
            unsafe_geometry_start_recompute_enabled,
        )

        class Settings:
            RELEASE_PROFILE = "debug"
            ENABLE_GEOMETRY_START_RECOMPUTE = True
            ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE = False

        monkeypatch.setenv("UP_ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE", "false")
        assert unsafe_geometry_start_recompute_enabled(Settings()) is False

    # ------------------------------------------------------------------
    # resolve_strict_quality_gates
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("profile", "env_value", "expected"),
        [
            ("structural_release", None, True),
            ("visual_build", None, True),
            ("scenario_augmentation", None, False),
            ("debug", None, False),
            ("", None, False),
            ("structural_release", "0", False),
            ("debug", "1", True),
            ("unknown-profile", None, False),
        ],
    )
    def test_strict_quality_gates(
        self,
        monkeypatch,
        profile,
        env_value,
        expected,
    ):
        from ultimate_pipeline.contracts.release_profile import resolve_strict_quality_gates

        if env_value is None:
            monkeypatch.delenv("UP_STRICT_QUALITY_GATES", raising=False)
        else:
            monkeypatch.setenv("UP_STRICT_QUALITY_GATES", env_value)

        assert resolve_strict_quality_gates(profile, env_override=env_value) is expected

    # ------------------------------------------------------------------
    # resolve_experimental_unsafe
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("profile", "expected"),
        [
            ("structural_release", False),
            ("visual_build", False),
            ("scenario_augmentation", False),
            ("debug", True),
            ("", False),
            ("unknown-profile", False),
        ],
    )
    def test_experimental_unsafe(self, profile, expected):
        from ultimate_pipeline.contracts.release_profile import resolve_experimental_unsafe

        assert resolve_experimental_unsafe(profile) is expected

    # ------------------------------------------------------------------
    # parse_optional_bool_env
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1", True),
            ("true", True),
            ("TRUE", True),
            ("yes", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("FALSE", False),
            ("no", False),
            ("off", False),
            ("", False),
        ],
    )
    def test_parse_optional_bool_env_valid(self, monkeypatch, raw, expected):
        from ultimate_pipeline.contracts.release_profile import parse_optional_bool_env

        monkeypatch.setenv("_TEST_VAR", raw)
        assert parse_optional_bool_env("_TEST_VAR") is expected

    def test_parse_optional_bool_env_missing(self, monkeypatch):
        from ultimate_pipeline.contracts.release_profile import parse_optional_bool_env

        monkeypatch.delenv("_TEST_VAR_MISSING", raising=False)
        assert parse_optional_bool_env("_TEST_VAR_MISSING") is None

    def test_parse_optional_bool_env_invalid(self, monkeypatch):
        from ultimate_pipeline.contracts.release_profile import parse_optional_bool_env

        monkeypatch.setenv("_TEST_VAR_INVALID", "bogus")
        with pytest.raises(ValueError):
            parse_optional_bool_env("_TEST_VAR_INVALID")


class TestExperimentRegistry:
    """Tests for experiment registry."""

    def test_get_smoke_test(self):
        """Test that smoke_test experiment is registered."""
        from ultimate_pipeline.experiments.registry import get_experiment

        exp = get_experiment("smoke_test")

        assert exp is not None
        assert exp.id == "smoke_test"
        assert exp.requires_carla is False

    def test_list_experiments(self):
        """Test listing experiments."""
        from ultimate_pipeline.experiments.registry import list_experiments

        experiments = list_experiments()

        assert len(experiments) > 0
        ids = [e.id for e in experiments]
        assert "smoke_test" in ids

    def test_list_experiments_filter_carla(self):
        """Test filtering by CARLA requirement."""
        from ultimate_pipeline.experiments.registry import list_experiments

        offline = list_experiments(filter_carla=False)
        carla_only = list_experiments(filter_carla=True)

        assert all(not e.requires_carla for e in offline)
        assert all(e.requires_carla for e in carla_only)

    def test_experiment_result_dataclass(self):
        """Test ExperimentResult dataclass."""
        from ultimate_pipeline.experiments.registry import ExperimentResult

        result = ExperimentResult(
            success=True,
            metrics={"test": 1},
            artifacts=["file.txt"],
        )

        assert result.success is True
        assert result.warnings == []  # Default empty list
