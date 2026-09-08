import subprocess
import sys
from pathlib import Path


def test_codex_harness_is_valid():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "tools" / "validate_codex_harness.py")],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CODEX_HARNESS_OK" in result.stdout
