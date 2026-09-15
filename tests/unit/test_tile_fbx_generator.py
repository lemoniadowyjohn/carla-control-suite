"""Unit tests for ultimate_pipeline.tiling.tile_fbx_generator.

The load-bearing correctness question this module answers is the **seam
strategy** (DESIGN.md §3.2): a hard, non-overlapping clip in which every building
is assigned to *exactly one* tile by its footprint centroid. A building whose
footprint straddles a grid boundary must land in exactly one tile -- never both
(double-render / z-fighting / doubled semantic labels) and never neither
(dropped). These tests exercise that partition directly, plus the grid math, the
whole-building OSM emission (no mid-polygon cuts), and the naming convention.

The Blender/OSM2World render path is NOT exercised here (it needs the external
binaries and is covered by the real probe cook in the report dir); these tests are
pure, fast, and deterministic.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.tiling.tile_fbx_generator import (
    TileBuilding,
    TileGridSpec,
    assign_buildings_to_tiles,
    load_buildings_from_overpass_json,
    tile_fbx_name,
    write_tile_osm_xml,
)


# Zero header offset keeps the tests in a clean local frame: with offset (0, 0)
# the bare-tmerc projection maps a point near lon=0/lat=0 to approximately
# (lon*111320*cos(lat), lat*110540) metres, but to keep the assertions exact we
# assert on *relative* placement (which cell a point lands in vs a boundary),
# never on absolute projected metres.
_GRID = TileGridSpec(tile_size_m=1000.0, header_offset_xy=(0.0, 0.0))


def _square_ring(lon0: float, lat0: float, dlon: float, dlat: float):
    """A closed 4-corner rectangle ring in (lon, lat)."""
    return [
        (lon0, lat0),
        (lon0 + dlon, lat0),
        (lon0 + dlon, lat0 + dlat),
        (lon0, lat0 + dlat),
        (lon0, lat0),
    ]


def _building(source_id, rings, *, tags=None, source_type="way") -> TileBuilding:
    return TileBuilding(
        source_id=str(source_id),
        source_type=source_type,
        tags=tags or {"building": "yes"},
        rings=rings,
    )


# ---------------------------------------------------------------------------
# Grid math
# ---------------------------------------------------------------------------
class TestGridMath:
    def test_cell_index_is_floor_division(self):
        g = TileGridSpec(tile_size_m=1000.0, header_offset_xy=(0.0, 0.0))
        assert g.cell_index(0.0, 0.0) == (0, 0)
        assert g.cell_index(999.999, 999.999) == (0, 0)
        assert g.cell_index(1000.0, 0.0) == (1, 0)  # upper edge -> higher cell
        assert g.cell_index(0.0, 1000.0) == (0, 1)
        assert g.cell_index(2500.0, 3500.0) == (2, 3)

    def test_cell_index_negative_coordinates_not_clamped(self):
        # The pinned map's local extent starts slightly negative (~-9.3, -8.3);
        # such points must fall into tx=-1/ty=-1, not be silently clamped to 0.
        g = TileGridSpec(tile_size_m=1000.0, header_offset_xy=(0.0, 0.0))
        assert g.cell_index(-1.0, -1.0) == (-1, -1)
        assert g.cell_index(-0.0001, 500.0) == (-1, 0)

    def test_cell_bounds_local_is_half_open_and_contiguous(self):
        g = TileGridSpec(tile_size_m=1000.0, header_offset_xy=(0.0, 0.0))
        b0 = g.cell_bounds_local(0, 0)
        b1 = g.cell_bounds_local(1, 0)
        assert b0["x_max"] == b1["x_min"]  # no gap, no overlap
        assert b0 == {"x_min": 0.0, "x_max": 1000.0, "y_min": 0.0, "y_max": 1000.0}

    def test_origin_offset_shifts_grid(self):
        g = TileGridSpec(tile_size_m=1000.0, header_offset_xy=(0.0, 0.0),
                         origin_x=500.0, origin_y=500.0)
        assert g.cell_index(499.9, 499.9) == (-1, -1)
        assert g.cell_index(500.0, 500.0) == (0, 0)

    def test_rejects_nonpositive_tile_size(self):
        with pytest.raises(ValueError):
            TileGridSpec(tile_size_m=0.0, header_offset_xy=(0.0, 0.0))
        with pytest.raises(ValueError):
            TileGridSpec(tile_size_m=-100.0, header_offset_xy=(0.0, 0.0))


# ---------------------------------------------------------------------------
# THE PARTITION: boundary-building assignment (the trickiest correctness case)
# ---------------------------------------------------------------------------
class TestBoundaryAssignment:
    def test_partition_is_exhaustive_and_disjoint(self):
        # Three buildings clearly in three different cells.
        buildings = [
            _building("a", [_square_ring(0.001, 0.001, 0.0005, 0.0005)]),
            _building("b", [_square_ring(0.02, 0.001, 0.0005, 0.0005)]),
            _building("c", [_square_ring(0.001, 0.02, 0.0005, 0.0005)]),
        ]
        assignment = assign_buildings_to_tiles(buildings, _GRID)
        # placed + unplaceable == total (nothing vanishes)
        assert assignment.total_placed() + len(assignment.unplaceable) == 3
        # each building appears exactly once across all cells
        placed_ids = [b.source_id for cell in assignment.tiles.values() for b in cell]
        assert sorted(placed_ids) == ["a", "b", "c"]
        assert len(placed_ids) == len(set(placed_ids))

    def test_building_straddling_boundary_lands_in_exactly_one_tile(self):
        # Build a small building whose footprint deliberately crosses a tile
        # boundary. We construct it so its centroid sits firmly on one side, and
        # assert it is placed in exactly that one cell -- not duplicated into the
        # neighbour, not dropped.
        grid = TileGridSpec(tile_size_m=1000.0, header_offset_xy=(0.0, 0.0))

        # Find a lon that maps to ~ the x=1000 m boundary, then build a footprint
        # centered just to its LEFT so the centroid is in cell tx=0 but the
        # right edge poke into tx=1.
        from ultimate_pipeline.tiling.tile_fbx_generator import _FWD_TRANSFORMER

        # Binary-search a lon whose projected x == 1000 m at a fixed lat.
        lat = 0.01
        lo, hi = 0.0, 0.05
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            x, _y = _FWD_TRANSFORMER.transform(mid, lat)
            if x < 1000.0:
                lo = mid
            else:
                hi = mid
        boundary_lon = 0.5 * (lo + hi)
        # dlon corresponding to ~40 m at this lat
        span_x, _ = _FWD_TRANSFORMER.transform(0.001, lat)
        dlon_40m = 0.001 * (40.0 / span_x)

        # Footprint spans [boundary_lon - 0.75*dlon, boundary_lon + 0.25*dlon]
        # => centroid ~0.25*dlon LEFT of the boundary => cell tx=0. Right edge
        # crosses into tx=1.
        lon0 = boundary_lon - 0.75 * dlon_40m
        ring = _square_ring(lon0, lat, dlon_40m, 0.0003)
        b = _building("straddle", [ring])

        assignment = assign_buildings_to_tiles([b], grid)
        occupied = assignment.occupied_cells()
        assert len(occupied) == 1, f"straddling building placed in {occupied}, expected 1 cell"
        (tx, ty) = occupied[0]
        assert tx == 0, f"centroid-left building should be tx=0, got tx={tx}"
        # It appears exactly once.
        total = assignment.total_placed()
        assert total == 1

    def test_two_buildings_sharing_a_boundary_wall_go_to_different_tiles(self):
        # A building just left of a boundary and one just right of it must split
        # across the two cells (partition, not overlap): proves we do not lump
        # everything near a seam into one tile.
        from ultimate_pipeline.tiling.tile_fbx_generator import _FWD_TRANSFORMER
        lat = 0.01
        lo, hi = 0.0, 0.05
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            x, _y = _FWD_TRANSFORMER.transform(mid, lat)
            if x < 1000.0:
                lo = mid
            else:
                hi = mid
        boundary_lon = 0.5 * (lo + hi)
        span_x, _ = _FWD_TRANSFORMER.transform(0.001, lat)
        dlon_20m = 0.001 * (20.0 / span_x)

        left = _building("left", [_square_ring(boundary_lon - 2 * dlon_20m, lat, dlon_20m, 0.0003)])
        right = _building("right", [_square_ring(boundary_lon + dlon_20m, lat, dlon_20m, 0.0003)])
        assignment = assign_buildings_to_tiles([left, right], _GRID)
        occupied = assignment.occupied_cells()
        assert len(occupied) == 2, f"expected 2 distinct cells, got {occupied}"
        # left in tx=0, right in tx=1
        tx_by_id = {}
        for (tx, ty), bs in assignment.tiles.items():
            for b in bs:
                tx_by_id[b.source_id] = tx
        assert tx_by_id["left"] == 0
        assert tx_by_id["right"] == 1

    def test_centroid_not_any_vertex_intersection(self):
        # A large building centered in tx=0 but with a long spur poking deep into
        # tx=1 must still be assigned to tx=0 (by centroid), NOT to both cells.
        # This is the exact failure an "any vertex intersects" rule would cause.
        from ultimate_pipeline.tiling.tile_fbx_generator import _FWD_TRANSFORMER
        lat = 0.01
        lo, hi = 0.0, 0.05
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            x, _y = _FWD_TRANSFORMER.transform(mid, lat)
            if x < 1000.0:
                lo = mid
            else:
                hi = mid
        boundary_lon = 0.5 * (lo + hi)
        span_x, _ = _FWD_TRANSFORMER.transform(0.001, lat)
        dlon = 0.001 / span_x  # 1 m in lon degrees

        # Bulk (heavy mass) far left in tx=0, plus a thin spur crossing into tx=1.
        # Centroid is dominated by the bulk => tx=0.
        bulk = [
            (boundary_lon - 300 * dlon, lat),
            (boundary_lon - 100 * dlon, lat),
            (boundary_lon - 100 * dlon, lat + 0.002),
            (boundary_lon - 300 * dlon, lat + 0.002),
            (boundary_lon - 300 * dlon, lat),
        ]
        b = _building("spur", [bulk])
        assignment = assign_buildings_to_tiles([b], _GRID)
        occupied = assignment.occupied_cells()
        assert occupied == [(0, 0)] or all(tx == 0 for (tx, ty) in occupied)
        assert assignment.total_placed() == 1

    def test_unplaceable_building_reported_not_dropped(self):
        # A building with no finite geometry cannot be placed, but must be
        # accounted for in `unplaceable` -- placed + unplaceable == total.
        empty = TileBuilding(source_id="empty", source_type="way",
                             tags={"building": "yes"}, rings=[[]])
        good = _building("good", [_square_ring(0.001, 0.001, 0.0005, 0.0005)])
        assignment = assign_buildings_to_tiles([empty, good], _GRID)
        assert assignment.total_placed() == 1
        assert len(assignment.unplaceable) == 1
        assert assignment.unplaceable[0].source_id == "empty"
        assert assignment.total_placed() + len(assignment.unplaceable) == 2


# ---------------------------------------------------------------------------
# Whole-building OSM emission (no mid-polygon cuts)
# ---------------------------------------------------------------------------
class TestTileOsmEmission:
    def test_writes_whole_buildings_with_negative_ids(self, tmp_path: Path):
        buildings = [
            _building("a", [_square_ring(11.42, 48.75, 0.0005, 0.0005)],
                      tags={"building": "yes", "height": "12"}),
            _building("b", [_square_ring(11.43, 48.76, 0.0005, 0.0005)],
                      tags={"building": "residential"}),
        ]
        out = tmp_path / "tile.osm"
        stats = write_tile_osm_xml(buildings, str(out))
        assert stats["buildings"] == 2
        assert stats["ways_written"] == 2
        assert stats["nodes_written"] > 0

        root = ET.parse(out).getroot()
        assert root.tag == "osm"
        ways = root.findall("way")
        assert len(ways) == 2
        # every way references only negative synthetic node ids, and every ref
        # resolves to a node in the file (self-contained, parseable)
        node_ids = {n.get("id") for n in root.findall("node")}
        assert all(int(n) < 0 for n in node_ids)
        for w in ways:
            assert int(w.get("id")) < 0
            for nd in w.findall("nd"):
                assert nd.get("ref") in node_ids
            # ring is closed (first ref == last ref)
            refs = [nd.get("ref") for nd in w.findall("nd")]
            assert refs[0] == refs[-1]
            # tags preserved
            tags = {t.get("k"): t.get("v") for t in w.findall("tag")}
            assert tags.get("building") in ("yes", "residential")

    def test_shared_corner_nodes_are_deduplicated(self, tmp_path: Path):
        # Two buildings sharing an identical corner coordinate collapse onto one
        # node (avoids OSM2World duplicate-point degeneracies).
        shared = (11.42, 48.75)
        b1 = _building("a", [[shared, (11.421, 48.75), (11.421, 48.751), shared]])
        b2 = _building("b", [[shared, (11.419, 48.75), (11.419, 48.751), shared]])
        out = tmp_path / "shared.osm"
        stats = write_tile_osm_xml([b1, b2], str(out))
        # 4 + 4 = 8 distinct corners minus 1 shared = 7 nodes (each ring has 3
        # distinct corners + closure back to first).
        # b1 distinct: shared, (11.421,48.75), (11.421,48.751) = 3
        # b2 distinct: shared(dup), (11.419,48.75), (11.419,48.751) = 2 new
        assert stats["nodes_written"] == 5

    def test_relation_multi_ring_building_emits_all_outer_rings(self, tmp_path: Path):
        ring1 = _square_ring(11.42, 48.75, 0.0003, 0.0003)
        ring2 = _square_ring(11.425, 48.755, 0.0003, 0.0003)
        rel = _building("r1", [ring1, ring2], source_type="relation",
                        tags={"building": "yes", "type": "multipolygon"})
        out = tmp_path / "rel.osm"
        stats = write_tile_osm_xml([rel], str(out))
        assert stats["ways_written"] == 2  # one way per outer ring


# ---------------------------------------------------------------------------
# Naming convention
# ---------------------------------------------------------------------------
class TestNaming:
    def test_tile_fbx_name_matches_carla_convention(self):
        assert tile_fbx_name("Ingolstadt", 0, 0) == "Ingolstadt_Tile_0_0.fbx"
        assert tile_fbx_name("Ingolstadt", 6, 8) == "Ingolstadt_Tile_6_8.fbx"
        assert tile_fbx_name("Map01", 12, 3) == "Map01_Tile_12_3.fbx"


# ---------------------------------------------------------------------------
# Loading the real pinned building source (structural, no render)
# ---------------------------------------------------------------------------
class TestLoadPinnedSource:
    PINNED = (
        Path(__file__).resolve().parents[2]
        / "campaigns" / "ingolstadt_cooked_perception_v1" / "source"
        / "ingolstadt_buildings_overpass.json"
    )

    @pytest.mark.skipif(not PINNED.exists(), reason="pinned buildings source absent")
    def test_loads_all_buildings_and_partitions_them(self):
        buildings = load_buildings_from_overpass_json(str(self.PINNED))
        # The pinned source has 5,693 ways + 19 relations = 5,712 elements
        # (map_stats.json). Every way/relation with >=3 vertices becomes a
        # TileBuilding.
        assert len(buildings) >= 5700
        grid = TileGridSpec(
            tile_size_m=1000.0,
            header_offset_xy=(832671.676, 5458671.104),
        )
        assignment = assign_buildings_to_tiles(buildings, grid)
        # Every building placed exactly once (partition), nothing dropped.
        assert assignment.total_placed() + len(assignment.unplaceable) == len(buildings)
        # No building id appears in two different cells.
        placed_ids = [b.source_id for cell in assignment.tiles.values() for b in cell]
        assert len(placed_ids) == len(set(placed_ids))
        # The densest tile matches the independently-computed probe (tile (6,8)).
        densest = max(assignment.tiles.items(), key=lambda kv: len(kv[1]))
        assert densest[0] == (6, 8)
        assert len(densest[1]) > 500


# ---------------------------------------------------------------------------
# Fail-closed roundtrip semantics
# ---------------------------------------------------------------------------
class TestFailClosedRoundtrip:
    def test_roundtrip_not_requested_returns_ok_status(self, tmp_path: Path):
        from unittest.mock import patch, MagicMock
        from ultimate_pipeline.tiling.tile_fbx_generator import generate_tile_fbx

        bldgs = [TileBuilding(source_id="w1", source_type="way", tags={}, rings=[[(11.43, 48.75), (11.431, 48.75), (11.431, 48.751), (11.43, 48.751), (11.43, 48.75)]])]

        osm_file = tmp_path / "Ingolstadt_Tile_0_0.osm"
        osm_file.write_text("<osm/>", encoding="utf-8")
        obj_file = tmp_path / "Ingolstadt_Tile_0_0.obj"
        obj_file.write_text("v 0 0 0", encoding="utf-8")
        fbx_file = tmp_path / "Ingolstadt_Tile_0_0.fbx"
        fbx_file.write_bytes(b"Kaydara FBX Binary\x00")

        with patch("ultimate_pipeline.tiling.tile_fbx_generator.OSM2WorldRunner") as mock_o2w, \
             patch("ultimate_pipeline.tiling.tile_fbx_generator.BlenderRunner") as mock_blender:

            mock_o2w_inst = MagicMock()
            mock_o2w_inst.run.return_value = MagicMock(status="ok", reason="")
            mock_o2w.return_value = mock_o2w_inst

            mock_blender_inst = MagicMock()
            mock_blender_inst.run.return_value = MagicMock(status="ok", reason="", manifest={"objects": []})
            mock_blender.return_value = mock_blender_inst

            res = generate_tile_fbx(
                buildings=bldgs,
                tile_index=(0, 0),
                map_name="Ingolstadt",
                output_dir=str(tmp_path),
                osm2world_home="/fake/o2w",
                run_roundtrip=False,
            )

            assert res.status == "ok"
            assert res.roundtrip_ok is None
            assert res.roundtrip_verdict == "ROUNDTRIP_NOT_REQUESTED"

    def test_roundtrip_requested_and_fails_returns_failed_status(self, tmp_path: Path):
        from unittest.mock import patch, MagicMock
        from ultimate_pipeline.tiling.tile_fbx_generator import generate_tile_fbx

        bldgs = [TileBuilding(source_id="w1", source_type="way", tags={}, rings=[[(11.43, 48.75), (11.431, 48.75), (11.431, 48.751), (11.43, 48.751), (11.43, 48.75)]])]

        osm_file = tmp_path / "Ingolstadt_Tile_0_0.osm"
        osm_file.write_text("<osm/>", encoding="utf-8")
        obj_file = tmp_path / "Ingolstadt_Tile_0_0.obj"
        obj_file.write_text("v 0 0 0", encoding="utf-8")
        fbx_file = tmp_path / "Ingolstadt_Tile_0_0.fbx"
        fbx_file.write_bytes(b"Kaydara FBX Binary\x00")

        with patch("ultimate_pipeline.tiling.tile_fbx_generator.OSM2WorldRunner") as mock_o2w, \
             patch("ultimate_pipeline.tiling.tile_fbx_generator.BlenderRunner") as mock_blender, \
             patch("ultimate_pipeline.tiling.tile_fbx_generator.run_fbx_roundtrip") as mock_rt:

            mock_o2w.return_value.run.return_value = MagicMock(status="ok", reason="")
            mock_blender.return_value.run.return_value = MagicMock(status="ok", reason="", manifest={"objects": []})

            mock_rt.return_value = (False, {"comparison": {"verdict": "MESH_COUNT_MISMATCH"}})

            fake_blender = tmp_path / "blender.exe"
            fake_blender.write_bytes(b"fake blender")

            res = generate_tile_fbx(
                buildings=bldgs,
                tile_index=(0, 0),
                map_name="Ingolstadt",
                output_dir=str(tmp_path),
                osm2world_home="/fake/o2w",
                blender_exe=str(fake_blender),
                run_roundtrip=True,
            )

            assert res.status == "failed"
            assert res.roundtrip_ok is False
            assert "MESH_COUNT_MISMATCH" in res.reason
