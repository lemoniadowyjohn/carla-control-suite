from pathlib import Path

import ultimate_pipeline.tools.run_perception_safe as m


def test_default_calib_exists() -> None:
    p = Path(m._DEFAULT_CALIB_PATH)
    assert p.exists(), f"Default calib not found: {p}"
