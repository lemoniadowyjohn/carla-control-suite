"""Test module origin guard (Task 5).

Verifies that representative imported modules originate from the repository root,
not from another local/worktree path. This prevents PYTHONPATH contamination.
"""
import sys
sys.path.insert(0, '.')

from pathlib import Path
import ultimate_pipeline
from ultimate_pipeline import geometry, quality, tiling, topology


def _get_module_filepath(mod_obj) -> Path | None:
    """Get the filepath of a module, if available."""
    file_attr = getattr(mod_obj, '__file__', None)
    if file_attr is None:
        return None
    try:
        return Path(file_attr).resolve()
    except Exception:
        return None


"""Test module origin guard (Task 5).

Verifies that representative imported modules originate from the repository root,
not from another local/worktree path. This prevents PYTHONPATH contamination.
"""
import sys
sys.path.insert(0, '.')

from pathlib import Path
import ultimate_pipeline
from ultimate_pipeline import geometry, quality, tiling, topology


def _get_module_filepath(mod_obj) -> Path | None:
    """Get the filepath of a module, if available."""
    file_attr = getattr(mod_obj, '__file__', None)
    if file_attr is None:
        return None
    try:
        return Path(file_attr).resolve()
    except Exception:
        return None


def _verify_module_origin(mod_name: str, mod_obj) -> None:
    """Verify a module originates from the repository root.

    Raises AssertionError if the module file is not relative to the repo root.
    """
    repo_root = Path('.').resolve()
    module_path = _get_module_filepath(mod_obj)
    
    # If module has no __file__, skip the path check but log
    if module_path is None:
        print(f"WARNING: Module {mod_name!r} has no __file__, skipping path check")
        return
    
    # Check that the module is within the repo root
    try:
        module_path.relative_to(repo_root)
    except ValueError:
        raise AssertionError(
            f"Module {mod_name!r} originates from {module_path}, "
            f"not from repository root {repo_root}. "
            f"Possible PYTHONPATH contamination detected."
        )
    
    # The module should be under the repo root, not in a parent worktree
    assert module_path.is_relative_to(repo_root), (
        f"Module {mod_name!r} path {module_path} is not relative to repo root {repo_root}"
    )


def test_ultimate_pipeline_origin():
    """Test ultimate_pipeline module origin."""
    _verify_module_origin('ultimate_pipeline', sys.modules['ultimate_pipeline'])


def test_geometry_origin():
    """Test geometry module origin."""
    _verify_module_origin('geometry', geometry)


def test_quality_origin():
    """Test quality module origin."""
    _verify_module_origin('quality', quality)


def test_tiling_origin():
    """Test tiling module origin."""
    _verify_module_origin('tiling', tiling)


def test_topology_origin():
    """Test topology module origin."""
    _verify_module_origin('topology', topology)


if __name__ == '__main__':
    test_ultimate_pipeline_origin()
    test_geometry_origin()
    test_quality_origin()
    test_tiling_origin()
    test_topology_origin()
    print()
    print('All Task 5 tests PASSED!')