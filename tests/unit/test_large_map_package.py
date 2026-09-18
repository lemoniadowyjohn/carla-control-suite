"""Unit tests for ultimate_pipeline.tiling.large_map_package.

Covers the gap identified in DESIGN.md §5 extension 3-4: turning a whole-map
XODR + per-tile FBX files into the ``Import/<PackageName>/`` layout CARLA's
``make import`` / ``Import.py`` filename-matching expects, plus the offline
pre-cook validation gate that catches staging/descriptor drift before any
UE4 host is involved.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.tiling.large_map_package import (
    PackageDescriptor,
    build_package_json,
    parse_tile_fbx_filename,
    stage_large_map_package,
    validate_staged_package,
)


# ---------------------------------------------------------------------------
# Filename parsing (CARLA "<MapName>_Tile_<x>_<y>.fbx" convention)
# ---------------------------------------------------------------------------
class TestParseTileFbxFilename:
    def test_parses_simple_name(self):
        assert parse_tile_fbx_filename("Ingolstadt_Tile_0_0.fbx") == ("Ingolstadt", 0, 0)

    def test_parses_multi_digit_and_map_name_with_underscore(self):
        assert parse_tile_fbx_filename("My_Map_Tile_12_8.fbx") == ("My_Map", 12, 8)

    def test_parses_negative_tile_indices(self):
        # The grid origin can produce negative indices (tile_fbx_generator
        # TileGridSpec docstring: a point near (-9.3, -8.3) lands in (-1, -1)).
        assert parse_tile_fbx_filename("Ingolstadt_Tile_-1_-1.fbx") == ("Ingolstadt", -1, -1)

    def test_rejects_non_matching_names(self):
        assert parse_tile_fbx_filename("Ingolstadt.fbx") is None
        assert parse_tile_fbx_filename("Ingolstadt_Tile_0_0.obj") is None
        assert parse_tile_fbx_filename("random_file.fbx") is None
        assert parse_tile_fbx_filename("Ingolstadt_Tile_a_b.fbx") is None


# ---------------------------------------------------------------------------
# PackageDescriptor validation
# ---------------------------------------------------------------------------
class TestPackageDescriptor:
    def test_valid_descriptor_constructs(self):
        d = PackageDescriptor(
            name="Ingolstadt",
            xodr_filename="Ingolstadt.xodr",
            tile_size_m=1000.0,
            tile_fbx_filenames=["Ingolstadt_Tile_0_0.fbx", "Ingolstadt_Tile_0_1.fbx"],
        )
        assert d.use_carla_materials is True

    def test_rejects_empty_name(self):
        with pytest.raises(ValueError):
            PackageDescriptor(name="", xodr_filename="M.xodr", tile_size_m=1000.0, tile_fbx_filenames=[])

    def test_rejects_non_xodr_extension(self):
        with pytest.raises(ValueError):
            PackageDescriptor(name="M", xodr_filename="M.txt", tile_size_m=1000.0, tile_fbx_filenames=[])

    def test_rejects_nonpositive_tile_size(self):
        with pytest.raises(ValueError):
            PackageDescriptor(name="M", xodr_filename="M.xodr", tile_size_m=0.0, tile_fbx_filenames=[])

    def test_rejects_non_fbx_tile_filename(self):
        with pytest.raises(ValueError):
            PackageDescriptor(
                name="M", xodr_filename="M.xodr", tile_size_m=1000.0,
                tile_fbx_filenames=["M_Tile_0_0.obj"],
            )

    def test_rejects_duplicate_tile_filenames(self):
        with pytest.raises(ValueError):
            PackageDescriptor(
                name="M", xodr_filename="M.xodr", tile_size_m=1000.0,
                tile_fbx_filenames=["M_Tile_0_0.fbx", "M_Tile_0_0.fbx"],
            )


# ---------------------------------------------------------------------------
# package.json construction (pure function, matches CARLA's documented schema)
# ---------------------------------------------------------------------------
class TestBuildPackageJson:
    def test_matches_documented_schema_shape(self):
        d = PackageDescriptor(
            name="Map01",
            xodr_filename="Map01.xodr",
            tile_size_m=2000.0,
            tile_fbx_filenames=[
                "Map01_Tile_0_0.fbx",
                "Map01_Tile_0_1.fbx",
                "Map01_Tile_1_0.fbx",
                "Map01_Tile_1_1.fbx",
            ],
        )
        doc = build_package_json(d)
        assert doc == {
            "maps": [
                {
                    "name": "Map01",
                    "xodr": "./Map01.xodr",
                    "use_carla_materials": True,
                    "tile_size": 2000.0,
                    "tiles": [
                        "./Map01_Tile_0_0.fbx",
                        "./Map01_Tile_0_1.fbx",
                        "./Map01_Tile_1_0.fbx",
                        "./Map01_Tile_1_1.fbx",
                    ],
                }
            ],
            "props": [],
        }

    def test_use_carla_materials_false_is_preserved(self):
        d = PackageDescriptor(
            name="M", xodr_filename="M.xodr", tile_size_m=1000.0,
            tile_fbx_filenames=[], use_carla_materials=False,
        )
        doc = build_package_json(d)
        assert doc["maps"][0]["use_carla_materials"] is False

    def test_empty_tiles_list_is_valid(self):
        d = PackageDescriptor(name="M", xodr_filename="M.xodr", tile_size_m=1000.0, tile_fbx_filenames=[])
        doc = build_package_json(d)
        assert doc["maps"][0]["tiles"] == []


# ---------------------------------------------------------------------------
# Staging: Import/<PackageName>/ layout
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_map_sources(tmp_path: Path):
    """A fake whole-map xodr + 3 tile fbx files, mimicking tile_fbx_generator output."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    xodr = src_dir / "Ingolstadt.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    tiles = []
    for tx, ty in [(0, 0), (0, 1), (1, 0)]:
        t = src_dir / f"Ingolstadt_Tile_{tx}_{ty}.fbx"
        t.write_bytes(b"FAKEFBX" + f"{tx}{ty}".encode())
        tiles.append(str(t))
    return {"xodr": str(xodr), "tiles": tiles, "src_dir": src_dir}


class TestStageLargeMapPackage:
    def test_stages_xodr_and_tiles_and_writes_descriptor(self, tmp_path: Path, fake_map_sources):
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=fake_map_sources["tiles"],
            import_root=str(import_root),
            tile_size_m=1000.0,
        )
        assert result.status == "ok"
        pkg_dir = import_root / "Ingolstadt"
        assert pkg_dir.is_dir()
        assert (pkg_dir / "Ingolstadt.xodr").is_file()
        assert (pkg_dir / "Ingolstadt_Tile_0_0.fbx").is_file()
        assert (pkg_dir / "Ingolstadt_Tile_0_1.fbx").is_file()
        assert (pkg_dir / "Ingolstadt_Tile_1_0.fbx").is_file()
        assert (pkg_dir / "package.json").is_file()
        assert (pkg_dir / "Ingolstadt.json").is_file()
        assert len(result.tiles_staged) == 3
        assert not result.tiles_skipped_missing

    def test_package_json_and_named_json_are_byte_identical(self, tmp_path: Path, fake_map_sources):
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=fake_map_sources["tiles"],
            import_root=str(import_root),
        )
        pkg_dir = Path(result.package_dir)
        a = (pkg_dir / "package.json").read_bytes()
        b = (pkg_dir / "Ingolstadt.json").read_bytes()
        assert a == b

    def test_tiles_are_sorted_deterministically_by_index(self, tmp_path: Path, fake_map_sources):
        import_root = tmp_path / "Import"
        # Pass tiles in a shuffled order; staged descriptor should still be sorted.
        shuffled = list(reversed(fake_map_sources["tiles"]))
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=shuffled,
            import_root=str(import_root),
        )
        doc = json.loads((Path(result.package_dir) / "package.json").read_text(encoding="utf-8"))
        tiles = doc["maps"][0]["tiles"]
        assert tiles == [
            "./Ingolstadt_Tile_0_0.fbx",
            "./Ingolstadt_Tile_0_1.fbx",
            "./Ingolstadt_Tile_1_0.fbx",
        ]

    def test_missing_tile_source_is_skipped_not_fatal(self, tmp_path: Path, fake_map_sources):
        import_root = tmp_path / "Import"
        missing = str(Path(fake_map_sources["src_dir"]) / "Ingolstadt_Tile_9_9.fbx")
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=fake_map_sources["tiles"] + [missing],
            import_root=str(import_root),
        )
        assert result.status == "ok"
        assert missing in result.tiles_skipped_missing
        assert len(result.tiles_staged) == 3

    def test_missing_xodr_fails_closed(self, tmp_path: Path, fake_map_sources):
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(tmp_path / "does_not_exist.xodr"),
            tile_fbx_paths=fake_map_sources["tiles"],
            import_root=str(import_root),
        )
        assert result.status == "failed"
        assert "not found" in result.reason

    def test_xodr_sha256_mismatch_fails_closed(self, tmp_path: Path, fake_map_sources):
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=fake_map_sources["tiles"],
            import_root=str(import_root),
            expected_xodr_sha256="0" * 64,
        )
        assert result.status == "failed"
        assert "sha256 mismatch" in result.reason
        # Must not have staged into Import/ on a hash mismatch.
        assert not (import_root / "Ingolstadt" / "Ingolstadt.xodr").exists()

    def test_manifest_sidecar_written_with_claim_boundary(self, tmp_path: Path, fake_map_sources):
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=fake_map_sources["tiles"],
            import_root=str(import_root),
        )
        manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
        assert manifest["artifact_type"] == "carla_large_map_import_package"
        assert manifest["tiles_staged_count"] == 3
        assert "UNCONFIRMED" in manifest["claim_boundary"]

    def test_custom_package_name_differs_from_map_name(self, tmp_path: Path, fake_map_sources):
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=fake_map_sources["tiles"],
            import_root=str(import_root),
            package_name="Ingolstadt_LargeMap_v1",
        )
        assert result.status == "ok"
        pkg_dir = import_root / "Ingolstadt_LargeMap_v1"
        assert pkg_dir.is_dir()
        assert (pkg_dir / "Ingolstadt_LargeMap_v1.json").is_file()
        doc = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
        # The descriptor's map "name" stays the map name (CARLA identifies the
        # map by this field); only the staging directory/filename uses the
        # package name.
        assert doc["maps"][0]["name"] == "Ingolstadt"


# ---------------------------------------------------------------------------
# Transactional staging integrity (comprehensive gap audit 20260915, packet
# P0-C): _copy_file() hardlinks when possible. A hardlink is not an
# independent copy -- if the source is later mutated in place (e.g. a re-run
# pipeline stage rewrites the same path), the "staged"/"promoted" artifact
# silently changes too, defeating the entire point of staging an immutable
# artifact before it is handed to `make import` / a UE4 cook.
# ---------------------------------------------------------------------------
class TestStagedArtifactIsIndependentOfSourceMutation:
    def test_xodr_source_mutation_after_staging_does_not_propagate(
        self, tmp_path: Path, fake_map_sources
    ):
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=fake_map_sources["tiles"],
            import_root=str(import_root),
        )
        assert result.status == "ok"
        staged_xodr = Path(result.xodr_staged_path)
        original_staged_bytes = staged_xodr.read_bytes()
        assert original_staged_bytes == Path(fake_map_sources["xodr"]).read_bytes()

        # Simulate a re-run pipeline stage rewriting the SOURCE file in place
        # (same path, opened for write -- not a rename/replace). This is
        # exactly the scenario the audit flagged: a hardlinked "staged" copy
        # is the same inode as the source and would change right along with
        # it.
        src_xodr = Path(fake_map_sources["xodr"])
        src_xodr.write_text("<OpenDRIVE>MUTATED-AFTER-STAGING</OpenDRIVE>", encoding="utf-8")

        staged_bytes_after_mutation = staged_xodr.read_bytes()
        assert staged_bytes_after_mutation == original_staged_bytes, (
            "the staged/promoted xodr changed after the SOURCE file was "
            "mutated post-staging -- stage_large_map_package() must produce "
            "an independent copy (not a hardlink aliasing the source inode), "
            "otherwise a staged/promoted artifact is not actually immutable"
        )

    def test_tile_fbx_source_mutation_after_staging_does_not_propagate(
        self, tmp_path: Path, fake_map_sources
    ):
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=fake_map_sources["tiles"],
            import_root=str(import_root),
        )
        assert result.status == "ok"
        pkg_dir = Path(result.package_dir)
        staged_tile = pkg_dir / "Ingolstadt_Tile_0_0.fbx"
        original_staged_bytes = staged_tile.read_bytes()

        src_tile = Path(fake_map_sources["src_dir"]) / "Ingolstadt_Tile_0_0.fbx"
        src_tile.write_bytes(b"MUTATED-TILE-BYTES-AFTER-STAGING")

        staged_bytes_after_mutation = staged_tile.read_bytes()
        assert staged_bytes_after_mutation == original_staged_bytes, (
            "the staged/promoted tile FBX changed after its SOURCE file was "
            "mutated post-staging -- stage_large_map_package() must produce "
            "an independent copy, not a hardlink"
        )


# ---------------------------------------------------------------------------
# Offline pre-cook validation gate
# ---------------------------------------------------------------------------
class TestValidateStagedPackage:
    def _stage(self, tmp_path: Path, fake_map_sources, **kwargs):
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=fake_map_sources["tiles"],
            import_root=str(import_root),
            **kwargs,
        )
        assert result.status == "ok"
        return Path(result.package_dir)

    def test_valid_package_passes(self, tmp_path: Path, fake_map_sources):
        pkg_dir = self._stage(tmp_path, fake_map_sources)
        v = validate_staged_package(str(pkg_dir))
        assert v.status == "PASS"
        assert v.failures == []
        assert v.tile_count == 3

    def test_expected_sha256_check(self, tmp_path: Path, fake_map_sources):
        pkg_dir = self._stage(tmp_path, fake_map_sources)
        import hashlib
        real_sha = hashlib.sha256((pkg_dir / "Ingolstadt.xodr").read_bytes()).hexdigest()
        v_ok = validate_staged_package(str(pkg_dir), expected_xodr_sha256=real_sha)
        assert v_ok.status == "PASS"
        v_bad = validate_staged_package(str(pkg_dir), expected_xodr_sha256="f" * 64)
        assert v_bad.status == "FAIL"
        assert any("sha256 mismatch" in f for f in v_bad.failures)

    def test_missing_directory_fails(self, tmp_path: Path):
        v = validate_staged_package(str(tmp_path / "does_not_exist"))
        assert v.status == "FAIL"
        assert any("does not exist" in f for f in v.failures)

    def test_missing_package_json_fails(self, tmp_path: Path):
        pkg_dir = tmp_path / "Empty"
        pkg_dir.mkdir()
        v = validate_staged_package(str(pkg_dir))
        assert v.status == "FAIL"
        assert any("missing package.json" in f for f in v.failures)

    def test_declared_tile_missing_from_disk_fails(self, tmp_path: Path, fake_map_sources):
        pkg_dir = self._stage(tmp_path, fake_map_sources)
        # Delete a staged tile file but leave it declared in package.json.
        (pkg_dir / "Ingolstadt_Tile_0_0.fbx").unlink()
        v = validate_staged_package(str(pkg_dir))
        assert v.status == "FAIL"
        assert any("declared tile not found" in f for f in v.failures)

    def test_stray_undeclared_tile_on_disk_fails(self, tmp_path: Path, fake_map_sources):
        pkg_dir = self._stage(tmp_path, fake_map_sources)
        # Drop an extra tile file directly into the package dir without going
        # through stage_large_map_package -- simulates a hand-copied or
        # partially-regenerated package where package.json drifted from disk.
        (pkg_dir / "Ingolstadt_Tile_5_5.fbx").write_bytes(b"STRAY")
        v = validate_staged_package(str(pkg_dir))
        assert v.status == "FAIL"
        assert any("stray tile FBX" in f for f in v.failures)

    def test_malformed_package_json_fails(self, tmp_path: Path, fake_map_sources):
        pkg_dir = self._stage(tmp_path, fake_map_sources)
        (pkg_dir / "package.json").write_text("{not valid json", encoding="utf-8")
        v = validate_staged_package(str(pkg_dir))
        assert v.status == "FAIL"
        assert any("not valid JSON" in f for f in v.failures)

    def test_package_json_missing_required_field_fails(self, tmp_path: Path, fake_map_sources):
        pkg_dir = self._stage(tmp_path, fake_map_sources)
        doc = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
        del doc["maps"][0]["tile_size"]
        (pkg_dir / "package.json").write_text(json.dumps(doc), encoding="utf-8")
        v = validate_staged_package(str(pkg_dir))
        assert v.status == "FAIL"
        assert any("tile_size" in f for f in v.failures)

    def test_empty_tiles_package_still_passes_structurally(self, tmp_path: Path, fake_map_sources):
        # A package staged before any tiles were generated (xodr only) should
        # still structurally validate -- an empty tile list is not itself an
        # error at the offline-gate layer (coverage-vs-grid is a separate,
        # higher-level check left to the caller / a future extension).
        import_root = tmp_path / "Import"
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=fake_map_sources["xodr"],
            tile_fbx_paths=[],
            import_root=str(import_root),
        )
        assert result.status == "ok"
        v = validate_staged_package(result.package_dir)
        assert v.status == "PASS"
        assert v.tile_count == 0
