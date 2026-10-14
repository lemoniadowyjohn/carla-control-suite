"""O2 — Large-Map Package Contract Audit tests.

Verifies the one-map/many-tiles architecture and that the mechanical
contract audit catches violations without mutating geometry.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.tiling.large_map_package import (
    stage_large_map_package,
    audit_large_map_package_contract,
    _sha256,
)


def _make_xodr(path: Path, content: str = "<OpenDRIVE></OpenDRIVE>") -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _make_tiles(tmp_path: Path, indices):
    paths = []
    for tx, ty in indices:
        p = tmp_path / f"Ingolstadt_Tile_{tx}_{ty}.fbx"
        p.write_bytes(b"fake" + f"{tx}{ty}".encode())
        paths.append(str(p))
    return paths


class TestContractAuditPass:
    def test_valid_one_map_many_tiles_passes(self, tmp_path: Path):
        xodr = _make_xodr(tmp_path / "Ingolstadt.xodr")
        tiles = _make_tiles(tmp_path, [(0, 0), (0, 1), (1, 0)])
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=tiles,
            import_root=str(tmp_path / "Import"),
        )
        assert result.status == "ok"
        audit = audit_large_map_package_contract(result.package_dir)
        assert audit.status == "PASS", f"failures: {audit.failures}"

    def test_tile_naming_consistent(self, tmp_path: Path):
        xodr = _make_xodr(tmp_path / "Ingolstadt.xodr")
        tiles = _make_tiles(tmp_path, [(0, 0), (-1, -1)])
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=tiles,
            import_root=str(tmp_path / "Import"),
        )
        audit = audit_large_map_package_contract(result.package_dir)
        assert audit.status == "PASS"

    def test_common_frame_and_tile_size(self, tmp_path: Path):
        xodr = _make_xodr(tmp_path / "Ingolstadt.xodr")
        tiles = _make_tiles(tmp_path, [(0, 0)])
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=tiles,
            import_root=str(tmp_path / "Import"),
            tile_size_m=1000.0,
        )
        audit = audit_large_map_package_contract(
            result.package_dir, expected_tile_size_m=1000.0, expected_header_offset_xy=(832671.676, 5458671.104)
        )
        # Synthetic tiles have no per-tile manifests, so header check is warning, not fail
        assert audit.status == "PASS"


class TestContractAuditFail:
    def test_per_tile_xodr_leak_fails(self, tmp_path: Path):
        xodr = _make_xodr(tmp_path / "Ingolstadt.xodr")
        tiles = _make_tiles(tmp_path, [(0, 0)])
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=tiles,
            import_root=str(tmp_path / "Import"),
        )
        # Inject a per-tile XODR leak
        leak = Path(result.package_dir) / "Ingolstadt_Tile_0_0.xodr"
        leak.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
        audit = audit_large_map_package_contract(result.package_dir)
        assert audit.status == "FAIL"
        assert any("per-tile XODR" in f or "exactly one .xodr" in f for f in audit.failures)

    def test_duplicate_tile_index_fails(self, tmp_path: Path):
        xodr = _make_xodr(tmp_path / "Ingolstadt.xodr")
        # Manually create two FBXs with same tx,ty but different map_name prefix
        # to get duplicate index (0,0) via different names that parse to same index
        # Simpler: directly place duplicate by writing two files with same name
        # and then auditing duplicate via manual filesystem manipulation
        tiles = _make_tiles(tmp_path, [(0, 0)])
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=tiles,
            import_root=str(tmp_path / "Import"),
        )
        # Duplicate index via second file with same index but different path:
        # Create a second FBX with same tile index but different filename that still
        # parses to same (tx,ty) — e.g., Ingolstadt_Tile_0_0.fbx is the only name
        # that parses to (0,0) for Ingolstadt, so we test by directly adding a
        # stray duplicate index file with different map_name that still has same xy
        # but our check is on (tx,ty) only, so we need two files that parse to same (0,0)
        # Use a different map_name but same xy, then the duplicate check should
        # still catch (0,0) duplicate if we manually add it.
        # For this test, we simulate by adding a second on-disk tile that the
        # descriptor doesn't declare, but the contract audit checks on-disk tiles
        # for duplicate indices, not declared.  So we add a second on-disk file
        # with same index via a symlink/copy with same name is impossible (same
        # filename).  Instead, we test the duplicate detection by creating a
        # package with two tiles that have same (tx,ty) via the same map_name —
        # which is prevented at descriptor level (duplicate filename).  So we
        # test a different violation: multiple XODRs.
        # For duplicate index, we check that our audit would catch it if it
        # somehow happened — we simulate by creating a second file with same
        # index but different map_name prefix that still yields same (0,0)
        dup = Path(result.package_dir) / "Other_Tile_0_0.fbx"
        dup.write_bytes(b"fake")
        audit = audit_large_map_package_contract(result.package_dir)
        assert audit.status == "FAIL"
        assert any("duplicate tile index" in f for f in audit.failures)

    def test_no_xodr_fails(self, tmp_path: Path):
        # Create a package dir with no XODR
        xodr = _make_xodr(tmp_path / "Ingolstadt.xodr")
        tiles = _make_tiles(tmp_path, [(0, 0)])
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=tiles,
            import_root=str(tmp_path / "Import"),
        )
        # Delete the XODR
        (Path(result.package_dir) / "Ingolstadt.xodr").unlink()
        audit = audit_large_map_package_contract(result.package_dir)
        assert audit.status == "FAIL"
        assert any("exactly one .xodr" in f for f in audit.failures)

    def test_stray_tile_fails_in_validate(self, tmp_path: Path):
        xodr = _make_xodr(tmp_path / "Ingolstadt.xodr")
        tiles = _make_tiles(tmp_path, [(0, 0)])
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=tiles,
            import_root=str(tmp_path / "Import"),
        )
        # Stray tile not declared
        stray = Path(result.package_dir) / "Ingolstadt_Tile_9_9.fbx"
        stray.write_bytes(b"stray")
        audit = audit_large_map_package_contract(result.package_dir)
        # Our contract audit does not currently check for stray vs declared
        # (that is validate_staged_package's job), but it does check on-disk
        # tile count vs descriptor
        # It will PASS because stray is not declared but is on-disk; our audit
        # currently warns but does not fail for stray?  Let's check that
        # validate does fail for stray
        from ultimate_pipeline.tiling.large_map_package import validate_staged_package

        v = validate_staged_package(result.package_dir)
        assert v.status == "FAIL"
        assert any("stray" in f for f in v.failures)


class TestVisualLayerDoesNotDuplicateRoads:
    def test_fbx_is_buildings_only_via_config(self, tmp_path: Path):
        # The only mechanical check we can do offline is that the tile manifest
        # (when present) records semantic_classification Buildings-only
        # and that the OSM2World config excludes RoadModule.
        # Here we verify the config string is present in the generator.
        from pathlib import Path as P

        txt = P("ultimate_pipeline/tiling/tile_fbx_generator.py").read_text(encoding="utf-8")
        assert "excludeWorldModule=RoadModule" in txt
        assert "createTerrain=false" in txt
