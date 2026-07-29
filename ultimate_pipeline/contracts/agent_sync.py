"""
Agent Sync Contract Model

Pydantic models for validating agent_sync.yaml contracts.
Replaces markdown-based validation with structured schema validation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class BboxContract(BaseModel):
    """Fixed OSM bounding box contract - DO NOT CHANGE."""

    lat_min: float = 48.74935649548228
    lat_max: float = 48.77444431571603
    lon_min: float = 11.422268084715878
    lon_max: float = 11.47882091528412

    @model_validator(mode="after")
    def validate_bounds(self) -> "BboxContract":
        if self.lat_min >= self.lat_max:
            raise ValueError("lat_min must be less than lat_max")
        if self.lon_min >= self.lon_max:
            raise ValueError("lon_min must be less than lon_max")
        return self

    def to_string(self) -> str:
        """Return canonical bbox string for tools."""
        return f"{self.lat_min},{self.lon_min},{self.lat_max},{self.lon_max}"


class SensorRigContract(BaseModel):
    """Sensor rig calibration contract."""

    # Camera configuration
    use_K_undistortion: bool = True
    ignore_K: bool = True
    ignore_D: bool = True
    ctv_inverted: bool = False  # cTv used directly, NOT inverted

    # LiDAR configuration
    vtl_inverted: bool = True  # vTl MUST be inverted for CARLA attachment

    # Required evidence
    rig_verification_required: bool = True
    screenshot_required: bool = True


class DeterminismContract(BaseModel):
    """Determinism/reproducibility contract."""

    min_runs: int = 5
    preferred_runs: int = 10

    # Map signature fields
    required_signature_fields: List[str] = Field(default_factory=lambda: [
        "xodr_sha256",
        "tile_metadata_sha256",
        "tile_count",
        "road_count",
        "junction_count",
    ])

    # Verdict classifications
    verdicts: List[str] = Field(default_factory=lambda: [
        "DETERMINISTIC",
        "NATURAL_RANDOMIZATION",
        "NONDETERMINISTIC",
    ])


class TilePairingContract(BaseModel):
    """Tile pairing algorithm contract."""

    algorithm: str = "hungarian"
    fallback: str = "greedy"
    require_one_to_one: bool = True


class ArtifactContract(BaseModel):
    """Required artifacts contract."""

    domain_gap: List[str] = Field(default_factory=lambda: [
        "full_report.json",
        "summary.csv",
        "reproducibility_hash.json",
        "tile_pairing_report.json",
        "domain_gap_status.json",
    ])

    determinism: List[str] = Field(default_factory=lambda: [
        "determinism_report.json",
        "determinism_hashes.csv",
        "determinism_thesis_table.csv",
        "determinism_delta.csv",
    ])

    perception: List[str] = Field(default_factory=lambda: [
        "perception_status.json",
        "rig_verification.json",
        "ego_spawn.png",
        "camera_front.png",
        "lidar_bev.png",
    ])

    perception_optional: List[str] = Field(default_factory=lambda: [
        "lidar_on_rgb_overlay.png",
        "objects_placed.json",
        "objects_placed.png",
    ])


class EnvironmentContract(BaseModel):
    """Environment variables contract."""

    required: List[str] = Field(default_factory=list)
    optional: List[str] = Field(default_factory=lambda: [
        "UP_MANUAL_XODR_GRID0828",
        "UP_MANUAL_TILES_DIR",
        "UP_AUTO_RUN_DIR",
        "UP_DISABLE_CARLA",
        "UP_TILE_CORRESPONDENCE_CSV",
        "UP_ALLOW_IDENTITY_ALIGNMENT",
        "UP_ALLOW_EMPTY_CORRESPONDENCE",
        "UP_ENABLE_CARLA_TESTS",
    ])


class AgentSyncContract(BaseModel):
    """
    Complete agent sync contract.

    This is the structured replacement for AGENT_SYNC.md.
    All contract validation is done via Pydantic instead of markdown parsing.
    """

    version: int = 1
    description: str = "Ultimate Pipeline Agent Sync Contract"

    bbox: BboxContract = Field(default_factory=BboxContract)
    sensor_rig: SensorRigContract = Field(default_factory=SensorRigContract)
    determinism: DeterminismContract = Field(default_factory=DeterminismContract)
    tile_pairing: TilePairingContract = Field(default_factory=TilePairingContract)
    artifacts: ArtifactContract = Field(default_factory=ArtifactContract)
    environment: EnvironmentContract = Field(default_factory=EnvironmentContract)

    # Flags for strict validation
    strict_mode: bool = False
    fail_on_missing_artifacts: bool = True

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Version must be at least 1")
        return v

    def to_yaml(self) -> str:
        """Export contract to YAML string."""
        try:
            import yaml
            return yaml.dump(self.model_dump(), default_flow_style=False, sort_keys=False)
        except ImportError:
            import json
            return json.dumps(self.model_dump(), indent=2)

    def save(self, path: Union[str, Path]) -> None:
        """Save contract to YAML file."""
        path = Path(path)
        content = self.to_yaml()
        path.write_text(content, encoding="utf-8")


def load_agent_sync(path: Optional[Union[str, Path]] = None) -> AgentSyncContract:
    """
    Load agent_sync contract from YAML file.

    Args:
        path: Path to agent_sync.yaml. If None, searches in standard locations.

    Returns:
        Validated AgentSyncContract instance.

    Raises:
        FileNotFoundError: If no contract file found.
        ValidationError: If contract validation fails.
    """
    if path is None:
        # Search in standard locations
        search_paths = [
            Path("agent_sync.yaml"),
            Path("configs/agent_sync.yaml"),
            Path.cwd() / "agent_sync.yaml",
        ]

        # Also check relative to this module
        module_dir = Path(__file__).parent.parent.parent
        search_paths.append(module_dir / "agent_sync.yaml")
        search_paths.append(module_dir / "configs" / "agent_sync.yaml")

        for p in search_paths:
            if p.exists():
                path = p
                break

        if path is None:
            raise FileNotFoundError(
                "No agent_sync.yaml found. Searched: " +
                ", ".join(str(p) for p in search_paths)
            )

    path = Path(path)
    content = path.read_text(encoding="utf-8")

    try:
        import yaml
        data = yaml.safe_load(content)
    except ImportError:
        import json
        # Try JSON fallback
        data = json.loads(content)

    if data is None:
        data = {}

    return AgentSyncContract.model_validate(data)


def validate_agent_sync(
    path: Optional[Union[str, Path]] = None,
    required_version: int = 1,
    strict: bool = False,
) -> Dict[str, Any]:
    """
    Validate agent_sync contract and return status report.

    Args:
        path: Path to agent_sync.yaml
        required_version: Minimum required version
        strict: Enable strict validation mode

    Returns:
        Dict with validation results:
        - valid: bool
        - version: int
        - errors: List[str]
        - warnings: List[str]
        - contract: AgentSyncContract (if valid)
    """
    result: Dict[str, Any] = {
        "valid": False,
        "version": 0,
        "errors": [],
        "warnings": [],
        "contract": None,
        "path": None,
    }

    try:
        contract = load_agent_sync(path)
        result["contract"] = contract
        result["version"] = contract.version
        result["path"] = str(path) if path else "auto-detected"

        # Version check
        if contract.version < required_version:
            result["errors"].append(
                f"Contract version {contract.version} < required {required_version}"
            )

        # Sensor rig validation
        if not contract.sensor_rig.use_K_undistortion:
            result["errors"].append("Sensor rig must use K_undistortion")
        if not contract.sensor_rig.vtl_inverted:
            result["errors"].append("vTl must be inverted for CARLA attachment")
        if contract.sensor_rig.ctv_inverted:
            result["errors"].append("cTv should NOT be inverted")

        # Determinism validation
        if contract.determinism.min_runs < 2:
            result["warnings"].append("min_runs < 2 may not detect variation")

        # Strict mode checks
        if strict:
            if not contract.fail_on_missing_artifacts:
                result["errors"].append("Strict mode requires fail_on_missing_artifacts=true")

        # Set valid if no errors
        result["valid"] = len(result["errors"]) == 0

    except FileNotFoundError as e:
        result["errors"].append(str(e))
        result["warnings"].append(
            "Create agent_sync.yaml with: python -m ultimate_pipeline.cli doctor --init-agent-sync"
        )

    except Exception as e:
        result["errors"].append(f"Validation error: {e}")

    return result


def migrate_from_markdown(md_path: Union[str, Path], yaml_path: Union[str, Path]) -> bool:
    """
    Create agent_sync.yaml from AGENT_SYNC.md (template-based).

    This doesn't parse the markdown; it creates a fresh YAML with canonical values.

    Args:
        md_path: Path to existing AGENT_SYNC.md (for reference)
        yaml_path: Path to create agent_sync.yaml

    Returns:
        True if migration successful
    """
    md_path = Path(md_path)
    yaml_path = Path(yaml_path)

    if not md_path.exists():
        print(f"[WARN] AGENT_SYNC.md not found at {md_path}")

    # Create canonical contract
    contract = AgentSyncContract()
    contract.save(yaml_path)

    print(f"[OK] Created {yaml_path} with canonical contract values")
    print(f"[INFO] AGENT_SYNC.md is now deprecated. Use agent_sync.yaml.")

    return True
