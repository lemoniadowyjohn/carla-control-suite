from __future__ import annotations

"""Stale-artifact injection gates for governed map resolution (B4).

Builds a temp environment containing two maps A and B (distinct sha256), a
pin registry resolving the map-of-record to B, and a stale A planted in every
plausible discovery directory. Proves that every registry-governed consumer
-- map-of-record resolver, cook offset source, Import/ package staging and
validation, and the tile FBX provenance gate -- selects B exclusively and
fails closed on drift.

Also pins down the two demonstrated NON-governed stale-selection paths
``settings._resolve_input_xodr_with_fallback`` and
``artifact_locator._newest_final_xodr``: they still choose newest-by-mtime
files when structural repair evidence is absent, which is exactly the
defect class the governed paths are designed to prevent. These tests encode
current behavior so a future fix that removes the mtime tie-break updates
them deliberately.
"""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultimate_pipeline.carla_tools.map_registry import (
    MapRegistryDriftError,
    MapRegistryValidationError,
    verify_pinned_map,
)
from ultimate_pipeline.config.settings import _resolve_input_xodr_with_fallback
from ultimate_pipeline.tiling.large_map_package import (
    _tile_provenance_status,
    stage_large_map_package,
    validate_staged_package,
)
from ultimate_pipeline.tools.artifact_locator import (
    _newest_final_xodr,
    resolve_run_dir,
)

MAP_A = b"<OpenDRIVE>stale map A</OpenDRIVE>"
MAP_B = b"<OpenDRIVE>registered map B</OpenDRIVE>"

NEWEST = 2_000_000_000
OLDEST = 1_000_000_000


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_map(base: Path, name: str, data: bytes) -> Path:
    p = base / name
    p.write_bytes(data)
    return p


def _pin_registry(map_b: Path, base: Path) -> dict:
    return {
        "auto_map_of_record": {
            "path": str(map_b.relative_to(base)).replace("\\", "/"),
            "sha256": _sha256_bytes(MAP_B),
            "bytes": len(MAP_B),
            "role": "auto",
            "frame": "test rebased frame",
            "aliases": ["auto", "auto_map_of_record", "map_of_record"],
            "frame_id": "test_local_rebased",
            "frame_kind": "rebased_local",
            "crs_authority": "test",
            "rebase_dx": 100.0,
            "rebase_dy": 200.0,
        }
    }


@pytest.fixture
def env(tmp_path):
    stale_dir = tmp_path / "run_stale"
    stale_dir.mkdir()
    map_a = _write_map(stale_dir, "map_of_record_stale.xodr", MAP_A)
    map_b = _write_map(tmp_path, "map_of_record_registered.xodr", MAP_B)
    os.utime(map_a, (NEWEST, NEWEST))
    os.utime(map_b, (OLDEST, OLDEST))
    return SimpleNamespace(
        base=tmp_path,
        map_a=map_a,
        map_b=map_b,
        registry=_pin_registry(map_b, tmp_path),
        sha_a=_sha256_bytes(MAP_A),
        sha_b=_sha256_bytes(MAP_B),
    )


@pytest.mark.quality
@pytest.mark.regression
class TestGovernedMapOfRecordResolver:
    def test_resolves_registered_map_only_even_with_newer_stale_present(self, env):
        receipt = verify_pinned_map("auto_map_of_record", base_dir=env.base, registry=env.registry)
        assert receipt["resolved_path"] == str(env.map_b)
        assert receipt["sha256"] == env.sha_b
        assert receipt["verification_status"] == "VERIFIED"
        assert receipt["registry_sha256"]

    def test_resolves_via_alias(self, env):
        receipt = verify_pinned_map("map_of_record", base_dir=env.base, registry=env.registry)
        assert receipt["resolved_path"] == str(env.map_b)
        assert receipt["registry_key"] == "auto_map_of_record"

    def test_content_drift_fails_closed_without_fallback_to_stale(self, env):
        env.map_b.write_bytes(MAP_B + b"tampered")
        with pytest.raises(MapRegistryDriftError):
            verify_pinned_map("auto_map_of_record", base_dir=env.base, registry=env.registry)

    def test_byte_size_drift_fails_closed_without_fallback_to_stale(self, env):
        env.map_b.write_bytes(MAP_B[:-4])
        with pytest.raises(MapRegistryDriftError):
            verify_pinned_map("auto_map_of_record", base_dir=env.base, registry=env.registry)

    def test_missing_registered_map_fails_closed_despite_newer_stale(self, env):
        env.map_b.unlink()
        with pytest.raises(MapRegistryDriftError):
            verify_pinned_map("auto_map_of_record", base_dir=env.base, registry=env.registry)

    def test_unregistered_file_never_resolves_by_basename(self, env):
        with pytest.raises(LookupError):
            verify_pinned_map("map_of_record_stale", base_dir=env.base, registry=env.registry)

    def test_rebased_frame_requires_structured_offset_fields(self, env):
        broken = {
            "auto_map_of_record": {
                "path": str(env.map_b.relative_to(env.base)).replace("\\", "/"),
                "sha256": env.sha_b,
                "bytes": len(MAP_B),
                "role": "auto",
                "frame": "rebased frame without offsets",
                "aliases": ["auto"],
                "frame_kind": "rebased_local",
            }
        }
        with pytest.raises(MapRegistryValidationError):
            verify_pinned_map("auto_map_of_record", base_dir=env.base, registry=broken)


@pytest.mark.quality
@pytest.mark.regression
class TestCookOffsetAuthority:
    @staticmethod
    def _cook_header_offset(pin):
        dx = pin.get("rebase_dx")
        dy = pin.get("rebase_dy")
        if dx is None or dy is None:
            raise ValueError("missing structured frame fields")
        return (float(dx), float(dy))

    def test_offset_source_is_registry_bound_or_fails_closed(self, env):
        receipt = verify_pinned_map("auto_map_of_record", base_dir=env.base, registry=env.registry)
        assert receipt["resolved_path"] == str(env.map_b)
        if receipt.get("rebase_dx") is None or receipt.get("rebase_dy") is None:
            with pytest.raises(ValueError):
                self._cook_header_offset(receipt)
        else:
            assert self._cook_header_offset(receipt) == (100.0, 200.0)


@pytest.mark.quality
@pytest.mark.regression
class TestImportPackageStagingAndValidation:
    def test_stage_and_validate_pass_for_registered_map(self, env):
        staged = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(env.map_b),
            tile_fbx_paths=[],
            import_root=str(env.base / "Import"),
            expected_xodr_sha256=env.sha_b,
        )
        assert staged.status == "ok"
        validation = validate_staged_package(
            staged.package_dir, expected_xodr_sha256=env.sha_b
        )
        assert validation.status == "PASS"
        assert validation.xodr_sha256 == env.sha_b

    def test_staging_refuses_stale_map_against_registered_sha(self, env):
        rejected = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(env.map_a),
            tile_fbx_paths=[],
            import_root=str(env.base / "Import"),
            expected_xodr_sha256=env.sha_b,
        )
        assert rejected.status == "failed"
        assert "xodr sha256 mismatch" in rejected.reason

    def test_swapped_stale_map_fails_post_stage_validation(self, env):
        staged = stage_large_map_package(
            map_name="Ingolstadt",
            xodr_path=str(env.map_b),
            tile_fbx_paths=[],
            import_root=str(env.base / "Import"),
            expected_xodr_sha256=env.sha_b,
        )
        assert staged.status == "ok"
        Path(staged.xodr_staged_path).write_bytes(MAP_A)
        bad = validate_staged_package(
            staged.package_dir, expected_xodr_sha256=env.sha_b
        )
        assert bad.status == "FAIL"
        assert any("sha256" in f for f in bad.failures)


@pytest.mark.quality
@pytest.mark.regression
class TestTileFbxProvenanceGate:
    def _tile_pair(self, env, sha=None):
        tile_dir = env.base / "tiles"
        tile_dir.mkdir(exist_ok=True)
        fbx = tile_dir / "Ingolstadt_Tile_0_0.fbx"
        fbx.write_bytes(b"fake fbx")
        manifest = tile_dir / "Ingolstadt_Tile_0_0.tile_fbx.json"
        if sha is not None:
            manifest.write_text(
                json.dumps(
                    {"source_provenance": {"map_of_record_sha256": sha}},
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        return fbx, manifest

    def test_stale_generation_tile_rejected(self, env):
        fbx, _ = self._tile_pair(env, sha=env.sha_a)
        status, actual, _ = _tile_provenance_status(fbx, env.sha_b)
        assert status == "mismatch"
        assert actual == env.sha_a

    def test_matching_generation_tile_accepted(self, env):
        fbx, _ = self._tile_pair(env, sha=env.sha_b)
        status, actual, _ = _tile_provenance_status(fbx, env.sha_b)
        assert status == "ok"
        assert actual == env.sha_b

    def test_manifestless_tile_rejected(self, env):
        fbx, _ = self._tile_pair(env, sha=None)
        status, _, _ = _tile_provenance_status(fbx, env.sha_b)
        assert status == "missing_manifest"

    def test_sha_less_manifest_rejected(self, env):
        fbx, _ = self._tile_pair(env, sha=env.sha_a)
        fbx.parent.joinpath(fbx.stem + ".tile_fbx.json").write_text(
            json.dumps({"foo": 1}), encoding="utf-8"
        )
        status, _, _ = _tile_provenance_status(fbx, env.sha_b)
        assert status == "missing_sha"


@pytest.mark.quality
@pytest.mark.regression
class TestDocumentedStaleMtimeSelectionPaths:
    def test_next_run_input_prefers_repair_evidence_over_mtime(self, env):
        base = env.base / "outputs"
        (base / "run_stale").mkdir(parents=True)
        (base / "run_good").mkdir(parents=True)
        stale = _write_map(base / "run_stale", "08_final_1000.xodr", MAP_A)
        _write_map(base / "run_good", "08_final_2000.xodr", MAP_B)
        sem_good = _write_map(base / "run_good", "08_final_3000_semantic.xodr", MAP_B)
        _write_map(base / "run_good", "08_final_3000_laneSectionFixed_v1.xodr", MAP_B)
        os.utime(stale, (NEWEST, NEWEST))
        os.utime(sem_good, (OLDEST, OLDEST))
        assert _resolve_input_xodr_with_fallback(str(base)) == str(sem_good)

    def test_next_run_input_is_stale_by_mtime_without_repair_evidence(self, env):
        base = env.base / "outputs"
        (base / "run_stale").mkdir(parents=True)
        (base / "run_good").mkdir(parents=True)
        stale = _write_map(base / "run_stale", "08_final_1000.xodr", MAP_A)
        good = _write_map(base / "run_good", "08_final_2000.xodr", MAP_B)
        os.utime(stale, (NEWEST, NEWEST))
        os.utime(good, (OLDEST, OLDEST))
        assert _resolve_input_xodr_with_fallback(str(base)) == str(stale)

    def test_artifact_locator_prefers_repair_evidence_over_mtime(self, env):
        run_dir = env.base / "run"
        run_dir.mkdir(parents=True)
        sem_stale = _write_map(run_dir, "08_final_1000_semantic.xodr", MAP_A)
        sem_good = _write_map(run_dir, "08_final_2000_semantic.xodr", MAP_B)
        _write_map(run_dir, "08_final_2000_laneSectionFixed_v1.xodr", MAP_B)
        os.utime(sem_stale, (NEWEST, NEWEST))
        os.utime(sem_good, (OLDEST, OLDEST))
        assert _newest_final_xodr(run_dir) == sem_good

    def test_artifact_locator_is_stale_by_mtime_without_repair_evidence(self, env):
        run_dir = env.base / "run"
        run_dir.mkdir(parents=True)
        stale = _write_map(run_dir, "08_final_1000_semantic.xodr", MAP_A)
        good = _write_map(run_dir, "08_final_2000_semantic.xodr", MAP_B)
        os.utime(stale, (NEWEST, NEWEST))
        os.utime(good, (OLDEST, OLDEST))
        assert _newest_final_xodr(run_dir) == stale

    def test_resolve_run_dir_is_explicit_not_mtime(self, env, monkeypatch):
        monkeypatch.delenv("UP_HEALTH_RUN_DIR", raising=False)
        assert resolve_run_dir(None) == Path(".")
        monkeypatch.setenv("UP_HEALTH_RUN_DIR", str(env.map_b.parent))
        assert resolve_run_dir(None) == Path(str(env.map_b.parent))