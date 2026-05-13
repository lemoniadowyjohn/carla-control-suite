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
