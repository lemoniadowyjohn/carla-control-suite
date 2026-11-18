from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_submission_validator_imports_from_submission_root_only(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    submission_root = repo_root / "submission" / "infrastructure"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(submission_root)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import ultimate_pipeline.sensors.applied_sensor_rig as rig; "
            "import ultimate_pipeline.tools.validate_thesis_run as validator; "
            "assert rig.SCHEMA == 'APPLIED_SENSOR_RIG/v2'; "
            "print(validator.__file__)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert str(submission_root) in completed.stdout
