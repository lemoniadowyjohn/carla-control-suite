import filecmp
import os
import pytest

CRITICAL_MIRRORED_FILES = [
    "core/carla_opendrive_loader.py",
    "core/xodr_hash_gate.py",
    "carla_tools/map_identity_guard.py",
    "quality/check_carla_opendrive_compat.py",
    "tools/load_final_into_carla.py",
]

def test_duplicate_module_drift():
    """Ensure submission/infrastructure/ultimate_pipeline mirrors ultimate_pipeline exactly for critical files."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    root_up = os.path.join(base_dir, "ultimate_pipeline")
    sub_up = os.path.join(base_dir, "submission", "infrastructure", "ultimate_pipeline")

    drifts = []
    for rel_path in CRITICAL_MIRRORED_FILES:
        f1 = os.path.join(root_up, rel_path)
        f2 = os.path.join(sub_up, rel_path)

        assert os.path.exists(f1), f"Canonical file missing: {f1}"
        assert os.path.exists(f2), f"Mirror file missing: {f2}"

        if not filecmp.cmp(f1, f2, shallow=False):
            drifts.append(rel_path)

    assert not drifts, f"Module drift detected between ultimate_pipeline and submission mirror in files: {drifts}"
