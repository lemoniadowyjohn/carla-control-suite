"""O4 — Import Package Preflight CLI tests.

Verifies the deterministic preflight correctly classifies packages without
launching Unreal, and never claims READY_FOR_RUNTIME.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tools.preflight_import_package import preflight_package
from ultimate_pipeline.tiling.large_map_package import _sha256


def _make_xodr(path: Path, content: str = "<OpenDRIVE><header><offset x=\"832671.676\" y=\"5458671.104\" z=\"0\" hdg=\"0\"/></header></OpenDRIVE>") -> str:
    path.write_text(content, encoding="utf-8")
    return _sha256(path)


def _make_tile_with_manifest(fbx_path: Path, source_sha: str) -> Path:
    fbx_path.parent.mkdir(parents=True, exist_ok=True)
    fbx_path.write_bytes(b"FAKEFBX" + fbx_path.name.encode())
    fbx_sha = _sha256(fbx_path)
    manifest = fbx_path.parent / (fbx_path.stem + ".tile_fbx.json")
    manifest.write_text(
        json.dumps(
            {
                "source_provenance": {"map_of_record_sha256": source_sha},
                "fbx": {"sha256": fbx_sha, "bytes": fbx_path.stat().st_size},
                "status": "ok",
            }
        ),
        encoding="utf-8",
    )
    return fbx_path


def _stage_valid_package(tmp_path: Path, xodr_sha: str = None):
    from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

    xodr = tmp_path / "Ingolstadt.xodr"
    header_content = "<OpenDRIVE><header><offset x=\"832671.676\" y=\"5458671.104\" z=\"0\" hdg=\"0\"/></header></OpenDRIVE>"
    if xodr_sha is None:
        xodr_sha = _make_xodr(xodr, header_content)
    else:
        # Write with header and compute sha (must match xodr_sha if provided)
        xodr.write_text(header_content, encoding="utf-8")
    # Create tiles with correct provenance
    tiles = []
    for tx, ty in [(0, 0), (0, 1)]:
        p = _make_tile_with_manifest(tmp_path / f"src_{tx}_{ty}" / f"Ingolstadt_Tile_{tx}_{ty}.fbx", source_sha=_make_xodr(tmp_path / "tmp.xodr", header_content) if False else xodr_sha)
        # Actually reuse xodr_sha
        # Recreate with correct sha
        p.unlink(missing_ok=True)
        (p.parent / (p.stem + ".tile_fbx.json")).unlink(missing_ok=True)
        p2 = _make_tile_with_manifest(p, source_sha=xodr_sha)
        tiles.append(str(p2))
    result = stage_large_map_package(
        map_name="Ingolstadt",
        xodr_path=str(xodr),
        tile_fbx_paths=tiles,
        import_root=str(tmp_path / "Import"),
        expected_xodr_sha256=xodr_sha,
    )
    return result, xodr_sha


class TestPreflightReady:
    def test_ready_for_import_when_valid(self, tmp_path: Path):
        # Use authoritative XODR for this test?  Instead, stage a synthetic
        # package and preflight it with expected SHA overridden to be synthetic,
        # so the authoritative check is bypassed via expected_xodr_sha param.
        # For this unit test we call preflight_package directly with expected
        # SHA set to synthetic, so authoritative check is not the staged XODR
        # but the synthetic XODR.
        xodr = tmp_path / "Ingolstadt.xodr"
        header = "<OpenDRIVE><header><offset x=\"832671.676\" y=\"5458671.104\" z=\"0\" hdg=\"0\"/></header></OpenDRIVE>"
        sha = _make_xodr(xodr, header)
        t1 = _make_tile_with_manifest(tmp_path / "a" / "Ingolstadt_Tile_0_0.fbx", source_sha=sha)
        t2 = _make_tile_with_manifest(tmp_path / "b" / "Ingolstadt_Tile_0_1.fbx", source_sha=sha)
        from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=[str(t1), str(t2)],
            import_root=str(tmp_path / "Import"),
            expected_xodr_sha256=sha,
        )
        assert result.status == "ok"
        pre = preflight_package(result.package_dir, expected_xodr_sha=sha, min_free_gib=0.001)
        assert pre["status"] == "READY", f"failures: {[c for c in pre['checks'] if c['status']!='PASS']}"
        assert pre["claim"] == "READY_FOR_IMPORT"
        assert "READY_FOR_RUNTIME" not in json.dumps(pre)

    def test_never_claims_runtime(self, tmp_path: Path):
        xodr = tmp_path / "Ingolstadt.xodr"
        sha = _make_xodr(xodr)
        t = _make_tile_with_manifest(tmp_path / "a" / "Ingolstadt_Tile_0_0.fbx", source_sha=sha)
        from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=[str(t)],
            import_root=str(tmp_path / "Import"),
            expected_xodr_sha256=sha,
        )
        pre = preflight_package(result.package_dir, expected_xodr_sha=sha, min_free_gib=0.001)
        assert "READY_FOR_RUNTIME" not in pre["claim"]
        assert pre["claim"] in ("READY_FOR_IMPORT", "BLOCKED_FOR_IMPORT", "INCOMPLETE_FOR_IMPORT")


class TestPreflightBlockedCases:
    def test_missing_tile_blocked(self, tmp_path: Path):
        xodr = tmp_path / "Ingolstadt.xodr"
        sha = _make_xodr(xodr)
        t1 = _make_tile_with_manifest(tmp_path / "a" / "Ingolstadt_Tile_0_0.fbx", source_sha=sha)
        from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=[str(t1)],
            import_root=str(tmp_path / "Import"),
            expected_xodr_sha256=sha,
        )
        # Tamper descriptor to declare a tile that doesn't exist
        pkg_json = Path(result.package_dir) / "package.json"
        doc = json.loads(pkg_json.read_text(encoding="utf-8"))
        doc["maps"][0]["tiles"].append("./Ingolstadt_Tile_9_9.fbx")
        pkg_json.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        pre = preflight_package(result.package_dir, expected_xodr_sha=sha, min_free_gib=0.001)
        assert pre["status"] == "BLOCKED"
        assert any("tile_exists" in c.get("check", "") or "declared tile not found" in str(c) for c in pre["checks"])

    def test_stale_tile_blocked(self, tmp_path: Path):
        xodr = tmp_path / "Ingolstadt.xodr"
        sha_current = _make_xodr(xodr, "<OpenDRIVE>current</OpenDRIVE><header><offset x=\"832671.676\" y=\"5458671.104\"/></header>")
        sha_stale = "a" * 64
        t_stale = _make_tile_with_manifest(tmp_path / "stale" / "Ingolstadt_Tile_0_0.fbx", source_sha=sha_stale)
        from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

        # Stage will reject stale tile, so we need to bypass staging and
        # manually create a package that contains a stale tile to test preflight
        # detection of stale after staging (via sidecar or per-tile manifest).
        # Instead, stage with current tile, then replace the staged FBX's
        # provenance sidecar to be stale.
        t_current = _make_tile_with_manifest(tmp_path / "cur" / "Ingolstadt_Tile_0_0.fbx", source_sha=sha_current)
        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=[str(t_current)],
            import_root=str(tmp_path / "Import"),
            expected_xodr_sha256=sha_current,
        )
        # Now manually make the staged tile stale by creating a per-tile
        # manifest alongside the staged FBX with stale SHA
        staged_fbx = Path(result.package_dir) / "Ingolstadt_Tile_0_0.fbx"
        stale_manifest = staged_fbx.parent / "Ingolstadt_Tile_0_0.tile_fbx.json"
        stale_manifest.write_text(
            json.dumps(
                {
                    "source_provenance": {"map_of_record_sha256": sha_stale},
                    "fbx": {"sha256": _sha256(staged_fbx), "bytes": staged_fbx.stat().st_size},
                }
            ),
            encoding="utf-8",
        )
        pre = preflight_package(result.package_dir, expected_xodr_sha=sha_current, min_free_gib=0.001)
        assert pre["status"] == "BLOCKED"

    def test_mismatched_xodr_blocked(self, tmp_path: Path):
        xodr = tmp_path / "Ingolstadt.xodr"
        sha = _make_xodr(xodr)
        t = _make_tile_with_manifest(tmp_path / "a" / "Ingolstadt_Tile_0_0.fbx", source_sha=sha)
        from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=[str(t)],
            import_root=str(tmp_path / "Import"),
            expected_xodr_sha256=sha,
        )
        # Tamper staged XODR to be different
        (Path(result.package_dir) / "Ingolstadt.xodr").write_text("<OpenDRIVE>tampered</OpenDRIVE>", encoding="utf-8")
        pre = preflight_package(result.package_dir, expected_xodr_sha=sha, min_free_gib=0.001)
        assert pre["status"] == "BLOCKED"

    def test_malformed_package_blocked(self, tmp_path: Path):
        xodr = tmp_path / "Ingolstadt.xodr"
        sha = _make_xodr(xodr)
        t = _make_tile_with_manifest(tmp_path / "a" / "Ingolstadt_Tile_0_0.fbx", source_sha=sha)
        from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=[str(t)],
            import_root=str(tmp_path / "Import"),
            expected_xodr_sha256=sha,
        )
        (Path(result.package_dir) / "package.json").write_text("{not json", encoding="utf-8")
        pre = preflight_package(result.package_dir, expected_xodr_sha=sha, min_free_gib=0.001)
        assert pre["status"] == "BLOCKED"

    def test_wrong_tile_naming_blocked(self, tmp_path: Path):
        xodr = tmp_path / "Ingolstadt.xodr"
        sha = _make_xodr(xodr)
        # Create a tile with wrong naming
        bad_tile = tmp_path / "BadName.fbx"
        bad_tile.write_bytes(b"fake")
        from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=[str(bad_tile)],
            import_root=str(tmp_path / "Import"),
            expected_xodr_sha256=sha,
        )
        # The bad tile is skipped (not staged) because it doesn't match naming,
        # so the staged package has 0 tiles but still has XODR.  The descriptor
        # will have 0 tiles, which is not a naming violation.  To test wrong
        # naming, we declare a wrong name in the descriptor.
        pkg_json = Path(result.package_dir) / "package.json"
        doc = json.loads(pkg_json.read_text(encoding="utf-8"))
        doc["maps"][0]["tiles"] = ["./BadName.fbx"]
        # Also create the bad file on disk
        (Path(result.package_dir) / "BadName.fbx").write_bytes(b"fake")
        pkg_json.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        pre = preflight_package(result.package_dir, expected_xodr_sha=sha, min_free_gib=0.001)
        assert pre["status"] == "BLOCKED"

    def test_missing_frame_metadata_incomplete_or_blocked(self, tmp_path: Path):
        xodr = tmp_path / "Ingolstadt.xodr"
        # XODR without header offset
        xodr.write_text("<OpenDRIVE><header></header></OpenDRIVE>", encoding="utf-8")
        sha = _sha256(xodr)
        t = _make_tile_with_manifest(tmp_path / "a" / "Ingolstadt_Tile_0_0.fbx", source_sha=sha)
        from ultimate_pipeline.tiling.large_map_package import stage_large_map_package

        result = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(xodr),
            tile_fbx_paths=[str(t)],
            import_root=str(tmp_path / "Import"),
            expected_xodr_sha256=sha,
        )
        pre = preflight_package(result.package_dir, expected_xodr_sha=sha, min_free_gib=0.001)
        # Missing offset should be INCOMPLETE or BLOCKED (frame metadata missing)
        assert pre["status"] in ("BLOCKED", "INCOMPLETE")
        assert any("world_frame" in c.get("check", "") for c in pre["checks"])
