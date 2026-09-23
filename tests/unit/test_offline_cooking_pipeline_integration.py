"""End-to-end integration test for the offline "cook this map for CARLA" chain.

This locks in the answer to a real question raised during the 20260916
integration audit: do the three independently-built pieces of the offline
tile-cook pipeline actually connect?

    1. ``ultimate_pipeline.tiling.tile_fbx_generator`` (+ its
       ``classify_tile_buildings`` semantic-tag QA wiring) -- per-tile FBX
       generation from clipped OSM buildings.
    2. ``ultimate_pipeline.enrichment.carla_semantic_organizer`` -- the CARLA
       semantic-tag rule engine.
    3. ``ultimate_pipeline.tiling.large_map_package`` (the engine behind
       ``tools/stage_large_map_import_package.py``) -- staging a whole-map
       XODR + tile FBX files into CARLA's ``Import/<Package>/`` layout and
       validating it.

Audit findings this test encodes
---------------------------------
* ``carla_semantic_organizer.py`` was a genuinely orphaned module before this
  change: unit-tested in isolation but never imported or called from any real
  pipeline stage (``tile_fbx_generator.py``, ``cook_full_grid_tiles.py``,
  ``large_map_package.py``, ``main_pipeline.py`` -- none referenced it).
* The task's default assumption that it should be wired in via its
  ``CarlaSemanticOrganizer.plan_from_inventory`` / ``execute_plan`` file-
  placement API (which moves/copies one source file per classified object,
  per ``inventory[i]["filename"]``) does NOT match what
  ``tile_fbx_generator`` actually produces: one *merged* FBX per tile
  containing many building objects, not one file per object. Wiring the
  file-placement API in directly would have silently fabricated
  per-object placements for files that were never produced.
* The correct integration point (this test proves it): classify each
  building by its real OSM tags via ``classify_object`` -- the organizer's
  pure rule-engine function, genuinely exercised here, not mocked --
  immediately before/alongside tile FBX generation, and carry the result
  forward as an additive ``semantic_classification`` field on the tile's
  result/manifest. This is real QA value: this tile-cook path renders
  buildings only, so a non-"Buildings" classification is evidence of a
  source-data defect.
* ``tile_fbx_generator`` and ``large_map_package``/``stage_large_map_import_
  package.py`` already connect correctly by construction: the tile FBX
  naming convention (``tile_fbx_name`` / ``_TILE_FBX_RE``) is shared, and
  ``stage_large_map_package`` takes a flat list of file paths (any
  directory shape) and copies each by ``Path(...).name``, so it doesn't
  care that ``cook_full_grid_tiles.py`` nests tiles under
  ``artifacts/tile_<tx>_<ty>/``. This test proves that by actually running
  the chain, not by inspecting the code and assuming it works.

Test strategy: real interfaces, stubbed external binaries only
----------------------------------------------------------------
``generate_tile_fbx`` runs for real -- every line of orchestration in
``tile_fbx_generator.py`` executes (clip -> OSM XML -> classification ->
manifest -> hashing). The only things stubbed are ``OSM2WorldRunner`` and
``BlenderRunner``, which wrap genuinely external, unavailable-in-CI native
binaries (a Java OSM2World install and a Blender executable) that sit
*outside* the three pieces under test here and are already covered by their
own test suites. The stubs still write real files to the real paths
``generate_tile_fbx`` expects, so every downstream consumer (hashing,
``large_map_package.stage_large_map_package``, ``validate_staged_package``)
operates on real files on disk, not in-memory mocks of its input.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from ultimate_pipeline.tiling import tile_fbx_generator as tfg
from ultimate_pipeline.tiling.large_map_package import (
    stage_large_map_package,
    validate_staged_package,
)


# ---------------------------------------------------------------------------
# Stubs for the two genuinely-external-binary wrappers only.
# ---------------------------------------------------------------------------
class _FakeOSM2WorldResult:
    def __init__(self, status: str = "ok", reason: str = "") -> None:
        self.status = status
        self.reason = reason


class _FakeOSM2WorldRunner:
    """Stands in for a real OSM2World (Java) invocation.

    Writes a real, tiny .obj file to the exact path ``generate_tile_fbx``
    expects (``<output_dir>/<name_prefix>.obj``) so every downstream check in
    the real orchestration code (``obj_path.exists()``, hashing, etc.) sees
    a real file, not a mock return value.
    """

    def __init__(self, *, osm_path, output_dir, osm2world_home, timeout_sec,
                 config_path, name_prefix, **_kw) -> None:
        self._output_dir = Path(output_dir)
        self._name_prefix = name_prefix

    def run(self) -> _FakeOSM2WorldResult:
        obj_path = self._output_dir / f"{self._name_prefix}.obj"
        obj_path.write_text("# fake OBJ (stubbed OSM2World)\nv 0 0 0\n", encoding="utf-8")
        return _FakeOSM2WorldResult(status="ok")


class _FakeBlenderResult:
    def __init__(self, status: str = "ok", reason: str = "", manifest: Dict[str, Any] | None = None) -> None:
        self.status = status
        self.reason = reason
        self.manifest = manifest or {}


class _FakeBlenderRunner:
    """Stands in for a real Blender OBJ->FBX conversion.

    Writes a real .fbx file to the exact path ``generate_tile_fbx`` expects
    and returns a manifest shaped exactly like the real
    ``blender_runner.py`` inventory (``objects`` list with
    name/vertices/faces/materials), so ``_inventory_totals`` and
    ``classify_tile_buildings`` both operate on realistic data.
    """

    def __init__(self, *, obj_path, output_dir, blender_exe, timeout_sec,
                 name_prefix, **_kw) -> None:
        self._output_dir = Path(output_dir)
        self._name_prefix = name_prefix

    def run(self) -> _FakeBlenderResult:
        fbx_path = self._output_dir / f"{self._name_prefix}.fbx"
        fbx_path.write_bytes(b"FAKEFBX_STUBBED_BLENDER_" + self._name_prefix.encode("ascii"))
        manifest = {
            "objects": [
                {"name": "Building_a", "type": "MESH", "vertices": 8, "faces": 6,
                 "uv_layers": 1, "materials": ["Wall_Mat"], "bounds": []},
                {"name": "Building_b", "type": "MESH", "vertices": 8, "faces": 6,
                 "uv_layers": 1, "materials": ["Wall_Mat"], "bounds": []},
            ],
            "objects_total": 2,
        }
        return _FakeBlenderResult(status="ok", manifest=manifest)


@pytest.fixture(autouse=True)
def _stub_external_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tfg, "OSM2WorldRunner", _FakeOSM2WorldRunner)
    monkeypatch.setattr(tfg, "BlenderRunner", _FakeBlenderRunner)


# ---------------------------------------------------------------------------
# Fixtures: a tiny, representative tile of buildings (real coordinates, real
# OSM tags), all landing in the same grid cell by construction.
# ---------------------------------------------------------------------------
def _ring(lon0: float, lat0: float, d: float = 0.0004) -> List[Tuple[float, float]]:
    return [(lon0, lat0), (lon0 + d, lat0), (lon0 + d, lat0 + d), (lon0, lat0 + d), (lon0, lat0)]


def _make_tile_buildings() -> List[tfg.TileBuilding]:
    """Two real buildings plus one mistagged element, all in the same cell.

    The mistagged ``barrier=wall`` element proves ``classify_tile_buildings``
    is a real, functioning QA signal -- not a rubber stamp that always says
    "Buildings" -- while staying inside the same tile as the real buildings
    so the FBX-generation and staging steps still only ever see one tile.
    """
    return [
        tfg.TileBuilding(source_id="bA", source_type="way",
                          tags={"building": "yes", "height": "12"},
                          parts=[tfg.BuildingPolygon(outer=_ring(11.4300, 48.7500))]),
        tfg.TileBuilding(source_id="bB", source_type="way",
                          tags={"building": "residential"},
                          parts=[tfg.BuildingPolygon(outer=_ring(11.4305, 48.7505))]),
        tfg.TileBuilding(source_id="wC", source_type="way",
                          tags={"barrier": "wall"},
                          parts=[tfg.BuildingPolygon(outer=_ring(11.4310, 48.7510))]),
    ]


_GRID = tfg.TileGridSpec(tile_size_m=1000.0, header_offset_xy=(832671.676, 5458671.104))


# ---------------------------------------------------------------------------
# The end-to-end chain test.
# ---------------------------------------------------------------------------
class TestOfflineCookingPipelineChain:
    def test_tile_fbx_generation_feeds_real_package_staging_and_validation(
        self, tmp_path: Path
    ) -> None:
        buildings = _make_tile_buildings()

        # --- Step 0: the real partition step confirms all 3 land in one cell.
        assignment = tfg.assign_buildings_to_tiles(buildings, _GRID)
        assert len(assignment.tiles) == 1, (
            f"fixture buildings must land in exactly one cell for this test, "
            f"got {list(assignment.tiles.keys())}"
        )
        tile_index = next(iter(assignment.tiles))
        tile_buildings = assignment.tiles[tile_index]
        assert len(tile_buildings) == 3

        # --- Step 1: real tile FBX generation (piece 1), external binaries
        # stubbed, everything else genuine.
        artifacts_dir = tmp_path / "artifacts" / f"tile_{tile_index[0]}_{tile_index[1]}"
        result = tfg.generate_tile_fbx(
            buildings=tile_buildings,
            tile_index=tile_index,
            map_name="IntegTestMap",
            output_dir=str(artifacts_dir),
            osm2world_home="/fake/osm2world/home",
            blender_exe=None,
            run_roundtrip=False,
        )

        assert result.status == "ok", f"expected ok, got {result.status}: {result.reason}"
        assert result.fbx_name == f"IntegTestMap_Tile_{tile_index[0]}_{tile_index[1]}.fbx"

        # Real files exist on disk (not just claimed by a mock).
        osm_path = Path(result.osm_path)
        obj_path = Path(result.obj_path)
        fbx_path = Path(result.fbx_path)
        manifest_path = Path(result.manifest_path)
        assert osm_path.is_file()
        assert obj_path.is_file()
        assert fbx_path.is_file()
        assert manifest_path.is_file()
        assert result.fbx_sha256 == _sha256(fbx_path)  # hash matches the real bytes on disk

        # --- Step 1b: the semantic-organizer wiring (piece 2) is real, not
        # orphaned: 2 real buildings -> "Buildings", 1 mistagged wall element
        # -> "Walls", surfaced as a QA anomaly, not silently absorbed.
        sc = result.semantic_classification
        assert sc["engine"] == "ultimate_pipeline.enrichment.carla_semantic_organizer.classify_object"
        assert sc["buildings_classified"] == 3
        assert sc["counts_by_folder"] == {"Buildings": 2, "Walls": 1}
        assert sc["non_buildings_count"] == 1
        assert sc["non_buildings_anomalies"][0]["source_id"] == "wC"
        assert sc["non_buildings_anomalies"][0]["folder"] == "Walls"

        # The classification is also persisted in the on-disk manifest sidecar
        # (real file, not just the in-memory dataclass) -- this is the durable
        # evidence artifact a human/CI would actually inspect.
        manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest_doc["semantic_classification"] == sc

        # --- Step 2: real package staging + validation (piece 3), consuming
        # the *actual* FBX file generate_tile_fbx wrote -- no path is
        # fabricated or mocked here.
        xodr_path = tmp_path / "IntegTestMap.xodr"
        xodr_path.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")

        import_root = tmp_path / "Import"
        stage_result = stage_large_map_package(
            map_name="IntegTestMap",
            xodr_path=str(xodr_path),
            tile_fbx_paths=[str(fbx_path)],
            import_root=str(import_root),
            tile_size_m=1000.0,
        )

        assert stage_result.status == "ok", stage_result.reason
        assert stage_result.tiles_staged == [fbx_path.name]
        assert stage_result.tiles_skipped_missing == []

        package_dir = Path(stage_result.package_dir)
        assert (package_dir / fbx_path.name).is_file()
        assert (package_dir / "package.json").is_file()

        package_json = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        assert package_json["maps"][0]["tiles"] == [f"./{fbx_path.name}"]

        # --- Step 3: the offline pre-cook validation gate must PASS against
        # what was actually staged -- proving the whole chain is
        # self-consistent end to end, not just "each piece runs without
        # crashing".
        validation = validate_staged_package(stage_result.package_dir)
        assert validation.status == "PASS", validation.failures
        assert validation.failures == []
        assert validation.tile_count == 1

    def test_empty_tile_never_reaches_staging(self, tmp_path: Path) -> None:
        """A tile with no assigned buildings must short-circuit at generation
        and never produce a file that staging could pick up -- guards against
        a future regression silently staging a phantom/empty tile FBX.
        """
        artifacts_dir = tmp_path / "artifacts" / "tile_99_99"
        result = tfg.generate_tile_fbx(
            buildings=[],
            tile_index=(99, 99),
            map_name="IntegTestMap",
            output_dir=str(artifacts_dir),
            osm2world_home="/fake/osm2world/home",
            blender_exe=None,
            run_roundtrip=False,
        )
        assert result.status == "empty"
        assert result.fbx_path == ""
        assert not (artifacts_dir / "IntegTestMap_Tile_99_99.fbx").exists()
        # No files at all were produced for staging to (correctly) skip.
        stage_result = stage_large_map_package(
            map_name="IntegTestMap",
            xodr_path=str(_write_min_xodr(tmp_path)),
            tile_fbx_paths=[str(artifacts_dir / "IntegTestMap_Tile_99_99.fbx")],
            import_root=str(tmp_path / "Import"),
        )
        assert stage_result.status == "ok"
        assert stage_result.tiles_staged == []
        assert stage_result.tiles_skipped_missing == [
            str(artifacts_dir / "IntegTestMap_Tile_99_99.fbx")
        ]


def _write_min_xodr(tmp_path: Path) -> Path:
    p = tmp_path / "Min.xodr"
    p.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    return p


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
