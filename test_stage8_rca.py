#!/usr/bin/env python3
"""
Isolated Stage-8 RCA Test
Runs Stage 8 (_step8_markings_and_integrity) on a given Stage 7 artifact
and captures all output, errors, and artifacts.
"""

import os
import sys
import json
import traceback
import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

# Add project root to path
PROJECT_ROOT = Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main")
sys.path.insert(0, str(PROJECT_ROOT))

# Set up environment
os.environ["UP_DISABLE_CARLA"] = "1"
os.environ["UP_STRICT_QUALITY_GATES"] = "0"
os.environ["UP_ENABLE_LANELINK_REGEN"] = "0"
os.environ["UP_AUTOFIX_LANE_SUCCESSORS"] = "1"  # Enable autofix
os.environ["UP_AUTOFIX_MISSING_LANE_SUCCESSORS"] = "0"
os.environ["UP_RUN_PREFLIGHT"] = "0"
os.environ["UP_ENABLE_CARLA_ELEVATION_VALIDATION"] = "0"
os.environ["UP_ENABLE_SPAWN_VALIDATION_STEP8"] = "0"
os.environ["UP_ENABLE_NATIVE_SIGNAL_ENRICHMENT"] = "0"
os.environ["UP_ENABLE_MAP_HYGIENE"] = "false"
os.environ["UP_ENABLE_DRIVABLE_SURFACE_HOLE_SCAN"] = "0"
os.environ["UP_ENABLE_GEOMETRIC_CONTINUITY"] = "0"
os.environ["UP_ENABLE_LANE_WIDTH_CONTINUITY"] = "0"
os.environ["UP_ENABLE_LANE_GEOMETRY_CONTINUITY"] = "0"
os.environ["UP_ENABLE_ROAD_LINK_TARGET_REPAIR"] = "0"
os.environ["UP_THESIS_STRICT"] = "0"
os.environ["UP_STRICT_LANE_SUCCESSORS"] = "0"

# Now import after env is set
from ultimate_pipeline.pipeline_stages.stage_08_integrity import _step8_markings_and_integrity
from ultimate_pipeline.core.odr_io import load_xodr, save_xodr
from ultimate_pipeline.config.settings import Settings

# Global storage for injected main_pipeline globals
import ultimate_pipeline.main_pipeline as main_pipeline_module

# Capture stdout/stderr
import io
from contextlib import redirect_stdout, redirect_stderr

def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def compute_file_bytes(path: Path) -> int:
    return path.stat().st_size

class MockPipeline:
    """Mock pipeline object with minimal required attributes."""
    
    def __init__(self, out_dir: Path, settings: Settings):
        self.out_dir = str(out_dir)
        self.settings = settings
        self.vreport = MagicMock()
        self.vreport.add_dict = MagicMock()
        self.vreport.add = MagicMock()
        self.qgate = MagicMock()
        self.qgate.gate_geometric_continuity = MagicMock(return_value={"ok": True})
        self.client = None
        self._carla_isolation_enabled = lambda: False
        
    def _assert_geometry_frozen(self, root, stage_name: str):
        """Mock geometry frozen assertion - always passes."""
        pass
    
    def _stage_gate(self, stage: str, gate_name: str, gate_func):
        """Mock stage gate - always passes."""
        result = gate_func()
        if hasattr(result, 'get') and not result.get('ok', True):
            raise RuntimeError(f"Gate {gate_name} failed")
        return result
    
    def _run_geometric_continuity_gate(self, xodr_path: str, label: str):
        """Mock geometric continuity gate."""
        pass
    
    def _step8_marking_summary(self, final_out: str):
        """Mock marking summary."""
        pass
    
    def _step8c_spawn_validation(self, final_out: str):
        """Mock spawn validation - disabled via env."""
        pass
    
    def _authority_mark_structure_mutated(self, stage: str, reason: str):
        """Mock authority marking."""
        pass
    
    def _authority_mark_hygiene_complete(self, final_out: str):
        """Mock hygiene complete."""
        pass
    
    def _maybe_override_final_georef(self, final_out: str):
        """Mock georef override."""
        pass
    
    def _carla_smoke_load_subprocess(self, **kwargs):
        """Mock CARLA smoke load."""
        return {"payload": {"load_ok": True}}

def run_stage8_rca(stage7_path: Path, output_dir: Path) -> Dict[str, Any]:
    """Run Stage 8 on the given Stage 7 artifact and return results."""
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    final_out = output_dir / "08_final.xodr"
    
    # Create settings
    settings = Settings()
    settings.OUTPUT_DIR_OVERRIDE = str(output_dir)
    settings.DETERMINISTIC_MODE = True
    settings.DETERMINISTIC_SEED = 42
    settings.ENABLE_CARLA = False
    settings.ENABLE_LANELINK_REGEN = False
    settings.ENABLE_MAP_HYGIENE = False
    settings.ENABLE_DRIVABLE_SURFACE_HOLE_SCAN = False
    settings.ENABLE_SPAWN_VALIDATION_STEP8 = False
    settings.ENABLE_NATIVE_SIGNAL_ENRICHMENT = False
    settings.FORCE_LIGHT_LOAD_IN_STEP_8 = True
    settings.STRICT_MODE = False
    settings.THESIS_STRICT = False
    settings.RELEASE_PROFILE = "debug"
    settings.USE_SHAPELY = False
    settings.AUTOFIX_MISSING_LANE_SUCCESSORS = False
    # Read autofix from env
    import os
    settings._autofix_lane_successors_env = os.getenv("UP_AUTOFIX_LANE_SUCCESSORS", "0").strip().lower() in ("1", "true", "yes", "on")
    settings._autofix_missing_lane_successors_env = os.getenv("UP_AUTOFIX_MISSING_LANE_SUCCESSORS", "0").strip().lower() in ("1", "true", "yes", "on")
    
    # Create mock pipeline
    mock_pipeline = MockPipeline(output_dir, settings)
    
    # Capture stdout/stderr
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    
    # Disk space before
    disk_free_before = shutil.disk_usage(output_dir).free
    
    # Track artifacts created
    artifacts_before = set(output_dir.glob("*"))
    
    exit_code = 0
    failure_class = "UNKNOWN"
    root_cause = ""
    traceback_str = ""
    last_successful_op = ""
    last_created_artifact = ""
    
    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            print(f"[RCA] Starting Stage 8 on {stage7_path}")
            print(f"[RCA] Output will be written to {final_out}")
            print(f"[RCA] Stage 7 SHA256: {compute_sha256(stage7_path)}")
            print(f"[RCA] Stage 7 size: {compute_file_bytes(stage7_path)} bytes")
            
            last_successful_op = "Loading Stage 7 XODR"
            tree, root = load_xodr(str(stage7_path))
            
            last_successful_op = "Running _step8_markings_and_integrity"
            result = _step8_markings_and_integrity(mock_pipeline, str(stage7_path), str(final_out))
            
            last_successful_op = "Stage 8 completed successfully"
            print(f"[RCA] Stage 8 completed, output: {result}")
            
    except Exception as e:
        exit_code = 1
        traceback_str = traceback.format_exc()
        print(f"[RCA] Stage 8 FAILED: {e}")
        print(f"[RCA] Traceback:\n{traceback_str}")
        
        # Classify failure
        error_msg = str(e)
        if isinstance(e, RuntimeError):
            if "geometry" in error_msg.lower():
                failure_class = "INVALID_GEOMETRY"
            elif "schema" in error_msg.lower() or "xsd" in error_msg.lower():
                failure_class = "SCHEMA_CONTRACT_FAILURE"
            elif "validation" in error_msg.lower() or "gate" in error_msg.lower():
                failure_class = "VALIDATION_GATE_FAILURE"
            elif "CARLA" in error_msg:
                failure_class = "PYTHON_EXCEPTION"  # CARLA-related but in isolation mode
            else:
                failure_class = "PYTHON_EXCEPTION"
        elif isinstance(e, MemoryError):
            failure_class = "MEMORY_FAILURE"
        elif isinstance(e, OSError) or isinstance(e, IOError):
            failure_class = "FILESYSTEM_WRITE_FAILURE"
        elif isinstance(e, FileNotFoundError):
            failure_class = "MISSING_INPUT"
        else:
            failure_class = "PYTHON_EXCEPTION"
        
        root_cause = f"{type(e).__name__}: {error_msg}"
    
    # Disk space after
    disk_free_after = shutil.disk_usage(output_dir).free
    
    # Find new artifacts
    artifacts_after = set(output_dir.glob("*"))
    new_artifacts = artifacts_after - artifacts_before
    if new_artifacts:
        last_created_artifact = str(max(new_artifacts, key=lambda p: p.stat().st_mtime))
    
    # Compute Stage 8 output hash if exists
    stage8_sha = ""
    stage8_bytes = 0
    if final_out.exists():
        stage8_sha = compute_sha256(final_out)
        stage8_bytes = compute_file_bytes(final_out)
    
    # Collect captured output
    stdout_str = stdout_capture.getvalue()
    stderr_str = stderr_capture.getvalue()
    
    return {
        "stage7_path": str(stage7_path),
        "stage7_sha256": compute_sha256(stage7_path),
        "stage7_bytes": compute_file_bytes(stage7_path),
        "stage8_path": str(final_out),
        "stage8_sha256": stage8_sha,
        "stage8_bytes": stage8_bytes,
        "exit_code": exit_code,
        "failure_class": failure_class,
        "root_cause": root_cause,
        "traceback": traceback_str,
        "stdout": stdout_str,
        "stderr": stderr_str,
        "last_successful_operation": last_successful_op,
        "last_created_artifact": last_created_artifact,
        "disk_free_before_gb": disk_free_before / (1024**3),
        "disk_free_after_gb": disk_free_after / (1024**3),
        "new_artifacts": [str(p) for p in new_artifacts],
    }

if __name__ == "__main__":
    # Use the Stage 7 artifact from gap048
    stage7_candidates = [
        PROJECT_ROOT / "reports" / "gap048" / "07_lanes_GAP048_AFTER.xodr",
        PROJECT_ROOT / "reports" / "gap048" / "07_lanes_GAP048_STAGE8_SIM.xodr",
        PROJECT_ROOT / "reports" / "rq1_trial_runs" / "run_01" / "20261007_214826_524342" / "07_lanes_20261007_214826_524342.xodr",
        PROJECT_ROOT / "reports" / "rq1_trial_runs_x2_verify" / "run_01" / "20261008_024449_086823" / "07_lanes_20261008_024449_086823.xodr",
    ]
    
    stage7_path = None
    for p in stage7_candidates:
        if p.exists():
            stage7_path = p
            break
    
    if stage7_path is None:
        print("ERROR: No Stage 7 artifact found!")
        sys.exit(1)
    
    print(f"Using Stage 7 artifact: {stage7_path}")
    print(f"Stage 7 SHA256: {compute_sha256(stage7_path)}")
    print(f"Stage 7 size: {compute_file_bytes(stage7_path)} bytes")
    
    # Create isolated output directory
    output_dir = PROJECT_ROOT / "stage8_rca_output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    
    # Run Stage 8
    result = run_stage8_rca(stage7_path, output_dir)
    
    # Save results
    result_path = output_dir / "stage8_rca_result.json"
    with open(result_path, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    
    print("\n" + "="*60)
    print("STAGE 8 RCA RESULT")
    print("="*60)
    print(f"STAGE7_SHA={result['stage7_sha256']}")
    print(f"STAGE8_EXIT_CODE={result['exit_code']}")
    print(f"STAGE8_FAILURE_CLASS={result['failure_class']}")
    print(f"STAGE8_ROOT_CAUSE={result['root_cause']}")
    print(f"FRESH_STAGE8_SHA={result['stage8_sha256']}")
    print(f"STAGE8_BYTES={result['stage8_bytes']}")
    print(f"LAST_SUCCESSFUL_OP={result['last_successful_operation']}")
    print(f"LAST_CREATED_ARTIFACT={result['last_created_artifact']}")
    print(f"DISK_FREE_BEFORE_GB={result['disk_free_before_gb']:.2f}")
    print(f"DISK_FREE_AFTER_GB={result['disk_free_after_gb']:.2f}")
    print(f"NEW_ARTIFACTS={result['new_artifacts']}")
    print(f"\nResult saved to: {result_path}")
    
    if result['traceback']:
        print(f"\nTRACEBACK:\n{result['traceback']}")
    
    if result['stdout']:
        print(f"\nSTDOUT:\n{result['stdout'][-2000:]}")  # Last 2000 chars
    
    if result['stderr']:
        print(f"\nSTDERR:\n{result['stderr'][-2000:]}")
    
    sys.exit(result['exit_code'])