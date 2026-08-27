"""ultimate_pipeline/carla_tools/map_registry.py::verify_pinned_map -- the fail-closed
content-drift guard for the pinned-map registry: raises rather than silently proceeding when a
pinned map file is missing, has drifted (sha256 mismatch), or is an un-smudged git-LFS pointer
stub masquerading as real content. Explicitly supports base_dir/registry override params "for
tests" per its own docstring -- was designed to be tested but had zero coverage. Supplemental to
test_map_registry_name_normalization.py (which already covers the name-resolution helpers).
Found via the orphaned-.pyc sweep (test_map_registry.py, the original exact-name test file, no
longer exists on this branch). copy_latest_carla_log (env/filesystem log-scanning, low value)
is out of scope.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ultimate_pipeline.carla_tools.map_registry import (
    MapRegistryDriftError,
    verify_pinned_map,
)


def _registry_for(path: Path, content: bytes, *, aliases=("test_map",)):
    return {
        "test_key": {
            "path": str(path),
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "role": "auto",
            "aliases": list(aliases),
        }
    }


def test_verify_pinned_map_happy_path_returns_entry(tmp_path: Path):
    p = tmp_path / "map.xodr"
    content = b"<OpenDRIVE/>"
    p.write_bytes(content)
    registry = _registry_for(p, content)

    entry = verify_pinned_map("test_map", registry=registry)

    assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    assert entry["bytes"] == len(content)


def test_verify_pinned_map_resolves_by_alias_case_insensitively(tmp_path: Path):
    p = tmp_path / "map.xodr"
    content = b"<OpenDRIVE/>"
    p.write_bytes(content)
    registry = _registry_for(p, content, aliases=("MyAlias",))

    entry = verify_pinned_map("myalias", registry=registry)
    assert entry is not None


def test_verify_pinned_map_resolves_by_canonical_key_when_no_aliases_declared(tmp_path: Path):
    # entry.get("aliases", [key]) only falls back to the dict key when "aliases" is entirely
    # absent -- a registry entry that DOES declare aliases must include the key itself to
    # remain resolvable by it (matches the real registry's convention of always listing its
    # own key among its aliases).
    p = tmp_path / "map.xodr"
    content = b"<OpenDRIVE/>"
    p.write_bytes(content)
    registry = {
        "test_key": {
            "path": str(p),
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            # no "aliases" key at all
        }
    }

    entry = verify_pinned_map("test_key", registry=registry)
    assert entry is not None


def test_verify_pinned_map_unregistered_name_raises_lookup_error(tmp_path: Path):
    registry = _registry_for(tmp_path / "map.xodr", b"x")
    with pytest.raises(LookupError, match="not a registered pinned map"):
        verify_pinned_map("totally_unknown_name", registry=registry)


def test_verify_pinned_map_missing_file_raises_drift_error(tmp_path: Path):
    missing = tmp_path / "does_not_exist.xodr"
    registry = {
        "test_key": {
            "path": str(missing), "sha256": "a" * 64, "bytes": 100,
            "aliases": ["test_map"],
        }
    }
    with pytest.raises(MapRegistryDriftError, match="file not found"):
        verify_pinned_map("test_map", registry=registry)


def test_verify_pinned_map_sha256_drift_raises_drift_error(tmp_path: Path):
    p = tmp_path / "map.xodr"
    p.write_bytes(b"content that was pinned originally")
    registry = {
        "test_key": {
            "path": str(p),
            "sha256": hashlib.sha256(b"different content entirely").hexdigest(),
            "bytes": 100,
            "aliases": ["test_map"],
        }
    }
    with pytest.raises(MapRegistryDriftError, match="content drift"):
        verify_pinned_map("test_map", registry=registry)


def test_verify_pinned_map_lfs_pointer_stub_raises_actionable_drift_error(tmp_path: Path):
    p = tmp_path / "map.xodr"
    # A real git-lfs pointer stub is a small text file starting with this exact header.
    p.write_bytes(
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:abcdef1234567890\nsize 144385542\n"
    )
    registry = {
        "test_key": {
            "path": str(p), "sha256": "a" * 64, "bytes": 100,
            "aliases": ["test_map"],
        }
    }
    with pytest.raises(MapRegistryDriftError, match="un-smudged git-LFS pointer"):
        verify_pinned_map("test_map", registry=registry)


def test_verify_pinned_map_relative_path_resolved_against_base_dir(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    p = tmp_path / "sub" / "map.xodr"
    content = b"<OpenDRIVE/>"
    p.write_bytes(content)
    registry = {
        "test_key": {
            "path": "sub/map.xodr",
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "aliases": ["test_map"],
        }
    }

    entry = verify_pinned_map("test_map", base_dir=tmp_path, registry=registry)
    assert entry is not None


def test_verify_pinned_map_absolute_path_ignores_base_dir(tmp_path: Path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    p = real_dir / "map.xodr"
    content = b"<OpenDRIVE/>"
    p.write_bytes(content)
    registry = _registry_for(p, content)  # absolute path already

    wrong_base = tmp_path / "wrong"
    wrong_base.mkdir()
    entry = verify_pinned_map("test_map", base_dir=wrong_base, registry=registry)
    assert entry is not None


def test_verify_pinned_map_returns_a_copy_not_the_live_registry_dict(tmp_path: Path):
    p = tmp_path / "map.xodr"
    content = b"<OpenDRIVE/>"
    p.write_bytes(content)
    registry = _registry_for(p, content)

    entry = verify_pinned_map("test_map", registry=registry)
    entry["sha256"] = "mutated"
    assert registry["test_key"]["sha256"] != "mutated"  # mutation must not leak back
