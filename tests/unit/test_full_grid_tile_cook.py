"""Tests for multi-tile FBX cook orchestration.

These tests cover the **orchestration layer** -- the logic in
``scripts/cook_full_grid_tiles.py`` that loads, partitions, orders, and
aggregates results across all 20 occupied tiles -- NOT the per-tile generation
itself (already covered in ``test_tile_fbx_generator.py``).

Specifically:
- All occupied tiles are attempted (none silently skipped).
- Cooking order is densest-first.
- Checkpoints are written after every tile, not just at the end.
- A partially-failed grid still aggregates the completed tiles.
- Results aggregate correctly: ok/failed/empty counts match, total buildings
  equal placed + unplaceable.
- Anomalies (non-ok tiles) are surfaced, not suppressed.
- The final summary JSON is schema-valid (has all required keys).

The tests mock ``generate_tile_fbx`` so they run fast (no Blender/OSM2World
dependency) and are fully deterministic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import MagicMock, call, patch

import pytest

# Make sure repo root is importable when running directly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ultimate_pipeline.tiling.tile_fbx_generator import (
    TileBuilding,
    TileGridSpec,
    assign_buildings_to_tiles,
)


# ---------------------------------------------------------------------------
# Fixtures: a tiny synthetic grid of 3 occupied cells
# ---------------------------------------------------------------------------
def _make_ring(lon0: float, lat0: float) -> List[Tuple[float, float]]:
    """A tiny 4-corner ring."""
    d = 0.0003
    return [(lon0, lat0), (lon0 + d, lat0), (lon0 + d, lat0 + d), (lon0, lat0 + d),
            (lon0, lat0)]


def _make_building(bid: str, lon0: float, lat0: float) -> TileBuilding:
    return TileBuilding(
        source_id=bid,
        source_type="way",
        tags={"building": "yes"},
        rings=[_make_ring(lon0, lat0)],
    )


# Three buildings in three different 1000 m cells (well-separated lat/lon).
_BUILDINGS = [
    _make_building("b1", 11.43, 48.75),   # cell A
    _make_building("b2", 11.43, 48.755),  # cell A (same cell as b1)
    _make_building("b3", 11.44, 48.76),   # cell B
    _make_building("b4", 11.46, 48.77),   # cell C
]
_GRID = TileGridSpec(tile_size_m=1000.0, header_offset_xy=(832671.676, 5458671.104))


def _ok_result(tile_index: Tuple[int, int], n_buildings: int) -> Dict[str, Any]:
    tx, ty = tile_index
    return {
        "status": "ok",
        "tile_index": list(tile_index),
        "fbx_name": f"Map_Tile_{tx}_{ty}.fbx",
        "reason": "",
        "building_count": n_buildings,
        "osm_path": f"/tmp/Map_Tile_{tx}_{ty}.osm",
        "obj_path": f"/tmp/Map_Tile_{tx}_{ty}.obj",
        "fbx_path": f"/tmp/Map_Tile_{tx}_{ty}.fbx",
        "fbx_bytes": n_buildings * 2500,
        "fbx_sha256": "aabbcc" + str(tx) + str(ty),
        "objects_total": n_buildings + 2,
        "vertices_total": n_buildings * 16,
        "faces_total": n_buildings * 12,
        "roundtrip_ok": True,
        "roundtrip_verdict": "ROUNDTRIP_PASS",
        "osm2world_sec": 3.5,
        "blender_sec": 5.0,
        "roundtrip_sec": 3.0,
        "total_sec": 11.5,
        "manifest_path": f"/tmp/Map_Tile_{tx}_{ty}.tile_fbx.json",
    }


def _failed_result(tile_index: Tuple[int, int], reason: str) -> Dict[str, Any]:
    tx, ty = tile_index
    return {
        "status": "failed",
        "tile_index": list(tile_index),
        "fbx_name": f"Map_Tile_{tx}_{ty}.fbx",
        "reason": reason,
        "building_count": 0,
        "osm_path": "",
        "obj_path": "",
        "fbx_path": "",
        "fbx_bytes": 0,
        "fbx_sha256": "",
        "objects_total": 0,
        "vertices_total": 0,
        "faces_total": 0,
        "roundtrip_ok": None,
        "roundtrip_verdict": "",
        "osm2world_sec": 2.1,
        "blender_sec": 0.0,
        "roundtrip_sec": 0.0,
        "total_sec": 2.1,
        "manifest_path": "",
    }


# ---------------------------------------------------------------------------
# Import cook_all_tiles from the orchestrator
# ---------------------------------------------------------------------------
import importlib.util as _ilu
_COOK_SCRIPT = _REPO_ROOT / "scripts" / "cook_full_grid_tiles.py"


def _import_cook() -> Any:
    """Import cook_full_grid_tiles as a module."""
    spec = _ilu.spec_from_file_location("cook_full_grid_tiles", _COOK_SCRIPT)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cook_mod = _import_cook()


# ---------------------------------------------------------------------------
# Tests: ordering and completeness
# ---------------------------------------------------------------------------
class TestTileOrdering:
    def test_ordered_densest_first(self):
        """Cook order must be descending building count."""
        assignment = assign_buildings_to_tiles(_BUILDINGS, _GRID)
        # Build ordered list the same way the orchestrator does.
        ordered = sorted(
            ((cell, len(bs)) for cell, bs in assignment.tiles.items()),
            key=lambda kv: (-kv[1], kv[0]),
        )
        counts = [n for _, n in ordered]
        assert counts == sorted(counts, reverse=True), (
            f"Expected descending counts, got {counts}"
        )

    def test_all_occupied_cells_present_in_ordering(self):
        assignment = assign_buildings_to_tiles(_BUILDINGS, _GRID)
        ordered_cells = sorted(
            ((cell, len(bs)) for cell, bs in assignment.tiles.items()),
            key=lambda kv: (-kv[1], kv[0]),
        )
        tile_order = [cell for cell, _ in ordered_cells]
        assert set(tile_order) == set(assignment.tiles.keys()), (
            "Some occupied cells are missing from the cook order"
        )
        assert len(tile_order) == len(assignment.tiles), (
            "Cook order has duplicate or extra cells"
        )


# ---------------------------------------------------------------------------
# Tests: checkpointing
# ---------------------------------------------------------------------------
class TestCheckpointing:
    def test_checkpoint_written_after_every_tile(self, tmp_path: Path):
        """CHECKPOINT.json must be updated after EACH tile, not just at the end."""
        checkpoint_path = tmp_path / "CHECKPOINT.json"
        write_calls: List[int] = []  # track how many tiles completed at each write

        original_write = _cook_mod._write_checkpoint

        def _spy_write(path, run_id, completed, remaining, wall_elapsed_sec):
            write_calls.append(len(completed))
            original_write(
                path,
                run_id=run_id,
                completed=completed,
                remaining=remaining,
                wall_elapsed_sec=wall_elapsed_sec,
            )

        assignment = assign_buildings_to_tiles(_BUILDINGS, _GRID)
        n_tiles = len(assignment.tiles)

        with patch.object(_cook_mod, "_write_checkpoint", side_effect=_spy_write), \
             patch.object(_cook_mod, "load_buildings_from_overpass_json",
                          return_value=_BUILDINGS), \
             patch.object(_cook_mod, "assign_buildings_to_tiles",
                          return_value=assignment), \
             patch.object(_cook_mod, "PINNED_BUILDINGS", tmp_path / "b.json"), \
             patch.object(_cook_mod, "PINNED_XODR", tmp_path / "m.xodr"), \
             patch("ultimate_pipeline.tiling.tile_fbx_generator.generate_tile_fbx") as mock_gen:

            # Create dummy source files so sha256 doesn't fail.
            (tmp_path / "b.json").write_bytes(b"{}")
            (tmp_path / "m.xodr").write_bytes(b"<OpenDRIVE/>")

            # generate_tile_fbx returns a mock TileFbxResult that has .to_dict().
            def _fake_generate(**kwargs):
                tile_index = kwargs["tile_index"]
                r = MagicMock()
                r.status = "ok"
                r.roundtrip_verdict = "ROUNDTRIP_PASS"
                r.reason = ""
                r.fbx_bytes = 100
                r.to_dict.return_value = _ok_result(tile_index, 5)
                return r

            mock_gen.side_effect = _fake_generate

            # Patch generate_tile_fbx in the cook module's namespace.
            with patch.object(_cook_mod, "generate_tile_fbx", side_effect=_fake_generate):
                _cook_mod.cook_all_tiles(
                    osm2world_home="/fake/osm2world",
                    blender_exe=None,
                    report_dir=tmp_path / "report",
                    artifacts_dir=tmp_path / "artifacts",
                    run_roundtrip=False,
                    verbose=False,
                )

        # Should have been called once per tile.
        assert len(write_calls) == n_tiles, (
            f"Expected {n_tiles} checkpoint writes, got {len(write_calls)}"
        )
        # Each call should record one more completed tile than the previous.
        assert write_calls == list(range(1, n_tiles + 1)), (
            f"Checkpoint completed-counts should increment by 1 each call, got {write_calls}"
        )

    def test_checkpoint_json_structure(self, tmp_path: Path):
        """A written CHECKPOINT.json must have required keys and valid types."""
        checkpoint_path = tmp_path / "CHECKPOINT.json"
        completed = [_ok_result((6, 8), 626), _ok_result((7, 8), 573)]
        remaining = [(8, 8), (7, 9)]
        _cook_mod._write_checkpoint(
            checkpoint_path,
            run_id="20260915T200000Z",
            completed=completed,
            remaining=remaining,
            wall_elapsed_sec=30.5,
        )
        assert checkpoint_path.exists()
        doc = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert doc["schema_version"] == 1
        assert doc["tiles_completed"] == 2
        assert doc["tiles_remaining"] == 2
        assert doc["wall_elapsed_sec"] == pytest.approx(30.5, abs=0.01)
        assert isinstance(doc["results"], list)
        assert len(doc["results"]) == 2


# ---------------------------------------------------------------------------
# Tests: partial-failure handling
# ---------------------------------------------------------------------------
class TestPartialFailureHandling:
    def test_failed_tile_does_not_abort_remaining(self, tmp_path: Path):
        """When one tile fails, the cook must continue with the remaining tiles."""
        assignment = assign_buildings_to_tiles(_BUILDINGS, _GRID)
        ordered_cells = sorted(
            ((cell, len(bs)) for cell, bs in assignment.tiles.items()),
            key=lambda kv: (-kv[1], kv[0]),
        )
        tile_order = [cell for cell, _ in ordered_cells]
        n_tiles = len(tile_order)

        attempted: List[Tuple[int, int]] = []

        def _fake_generate(**kwargs):
            tile_index = kwargs["tile_index"]
            attempted.append(tile_index)
            r = MagicMock()
            if tile_index == tile_order[0]:
                # First tile (densest) fails.
                r.status = "failed"
                r.roundtrip_verdict = ""
                r.reason = "OSM2World timeout"
                r.fbx_bytes = 0
                r.to_dict.return_value = _failed_result(tile_index, "OSM2World timeout")
            else:
                r.status = "ok"
                r.roundtrip_verdict = "ROUNDTRIP_PASS"
                r.reason = ""
                r.fbx_bytes = 1000
                r.to_dict.return_value = _ok_result(tile_index, 5)
            return r

        with patch.object(_cook_mod, "load_buildings_from_overpass_json",
                          return_value=_BUILDINGS), \
             patch.object(_cook_mod, "assign_buildings_to_tiles",
                          return_value=assignment), \
             patch.object(_cook_mod, "PINNED_BUILDINGS", tmp_path / "b.json"), \
             patch.object(_cook_mod, "PINNED_XODR", tmp_path / "m.xodr"), \
             patch.object(_cook_mod, "generate_tile_fbx", side_effect=_fake_generate):

            (tmp_path / "b.json").write_bytes(b"{}")
            (tmp_path / "m.xodr").write_bytes(b"<OpenDRIVE/>")

            rc = _cook_mod.cook_all_tiles(
                osm2world_home="/fake/osm2world",
                blender_exe=None,
                report_dir=tmp_path / "report",
                artifacts_dir=tmp_path / "artifacts",
                run_roundtrip=False,
                verbose=False,
            )

        # All tiles were attempted.
        assert len(attempted) == n_tiles, (
            f"Expected all {n_tiles} tiles attempted, got {len(attempted)}"
        )
        # Non-zero exit code because one tile failed.
        assert rc != 0

    def test_anomalies_surfaced_in_summary(self, tmp_path: Path):
        """Anomalies list in COOK_RESULTS.json must contain only non-ok tiles."""
        assignment = assign_buildings_to_tiles(_BUILDINGS, _GRID)
        ordered_cells = sorted(
            ((cell, len(bs)) for cell, bs in assignment.tiles.items()),
            key=lambda kv: (-kv[1], kv[0]),
        )
        tile_order = [cell for cell, _ in ordered_cells]

        def _fake_generate(**kwargs):
            tile_index = kwargs["tile_index"]
            r = MagicMock()
            if tile_index == tile_order[1]:
                # Second tile fails.
                r.status = "failed"
                r.roundtrip_verdict = ""
                r.reason = "Blender crash"
                r.fbx_bytes = 0
                r.to_dict.return_value = _failed_result(tile_index, "Blender crash")
            else:
                r.status = "ok"
                r.roundtrip_verdict = "ROUNDTRIP_PASS"
                r.reason = ""
                r.fbx_bytes = 1000
                r.to_dict.return_value = _ok_result(tile_index, 5)
            return r

        with patch.object(_cook_mod, "load_buildings_from_overpass_json",
                          return_value=_BUILDINGS), \
             patch.object(_cook_mod, "assign_buildings_to_tiles",
                          return_value=assignment), \
             patch.object(_cook_mod, "PINNED_BUILDINGS", tmp_path / "b.json"), \
             patch.object(_cook_mod, "PINNED_XODR", tmp_path / "m.xodr"), \
             patch.object(_cook_mod, "generate_tile_fbx", side_effect=_fake_generate):

            (tmp_path / "b.json").write_bytes(b"{}")
            (tmp_path / "m.xodr").write_bytes(b"<OpenDRIVE/>")

            _cook_mod.cook_all_tiles(
                osm2world_home="/fake/osm2world",
                blender_exe=None,
                report_dir=tmp_path / "report",
                artifacts_dir=tmp_path / "artifacts",
                run_roundtrip=False,
                verbose=False,
            )

        results_path = tmp_path / "report" / "COOK_RESULTS.json"
        assert results_path.exists(), "COOK_RESULTS.json must be written"
        doc = json.loads(results_path.read_text(encoding="utf-8"))

        anomalies = doc["anomalies"]
        assert len(anomalies) == 1, (
            f"Expected exactly 1 anomaly (the failed tile), got {len(anomalies)}"
        )
        assert anomalies[0]["status"] == "failed"
        assert "Blender crash" in anomalies[0]["reason"]


# ---------------------------------------------------------------------------
# Tests: result aggregation correctness
# ---------------------------------------------------------------------------
class TestResultAggregation:
    def test_summary_counts_match_result_list(self):
        """_build_summary counts must equal what the results list contains."""
        from ultimate_pipeline.tiling.tile_fbx_generator import TileAssignment

        assignment = assign_buildings_to_tiles(_BUILDINGS, _GRID)
        tiles_copy = dict(assignment.tiles)
        synthetic_assignment = TileAssignment(
            grid=assignment.grid,
            tiles=tiles_copy,
            unplaceable=assignment.unplaceable,
        )

        cells = sorted(assignment.tiles.keys())
        all_results = []
        for i, cell in enumerate(cells):
            if i == 0:
                all_results.append(_failed_result(cell, "OSM2World timeout"))
            else:
                all_results.append(_ok_result(cell, len(assignment.tiles[cell])))

        summary = _cook_mod._build_summary(
            run_id="run123",
            assignment=synthetic_assignment,
            all_results=all_results,
            wall_elapsed_sec=99.9,
            source_provenance={"buildings_source": "x"},
        )

        assert summary["tiles_attempted"] == len(cells)
        assert summary["tiles_ok"] == len(cells) - 1
        assert summary["tiles_failed"] == 1
        assert summary["tiles_empty"] == 0
        assert summary["roundtrip_pass"] == len(cells) - 1
        assert summary["roundtrip_fail"] == 0
        assert len(summary["anomalies"]) == 1

    def test_summary_schema_has_required_keys(self):
        """Final summary must contain all required top-level keys."""
        from ultimate_pipeline.tiling.tile_fbx_generator import TileAssignment

        assignment = assign_buildings_to_tiles(_BUILDINGS, _GRID)
        all_results = [_ok_result(c, 5) for c in assignment.tiles]
        summary = _cook_mod._build_summary(
            run_id="run456",
            assignment=assignment,
            all_results=all_results,
            wall_elapsed_sec=42.0,
            source_provenance={},
        )

        required_keys = {
            "schema_version", "artifact_type", "run_id", "map_name",
            "tile_size_m", "wall_elapsed_sec", "buildings_loaded",
            "buildings_placed", "buildings_unplaceable", "occupied_cells",
            "tiles_attempted", "tiles_ok", "tiles_failed", "tiles_empty",
            "roundtrip_pass", "roundtrip_fail", "anomalies", "results",
            "source_provenance", "claim_boundary",
        }
        missing = required_keys - set(summary.keys())
        assert not missing, f"Summary missing keys: {missing}"

    def test_buildings_placed_plus_unplaceable_equals_loaded(self):
        """placed + unplaceable == loaded must hold in the summary."""
        assignment = assign_buildings_to_tiles(_BUILDINGS, _GRID)
        all_results = [_ok_result(c, len(bs)) for c, bs in assignment.tiles.items()]
        summary = _cook_mod._build_summary(
            run_id="run789",
            assignment=assignment,
            all_results=all_results,
            wall_elapsed_sec=10.0,
            source_provenance={},
        )
        assert (
            summary["buildings_placed"] + summary["buildings_unplaceable"]
            == summary["buildings_loaded"]
        ), (
            f"placed {summary['buildings_placed']} + unplaceable "
            f"{summary['buildings_unplaceable']} != loaded {summary['buildings_loaded']}"
        )


# ---------------------------------------------------------------------------
# Integration-flavored: test with real pinned source (structural only, no render)
# ---------------------------------------------------------------------------
_PINNED_BUILDINGS = (
    _REPO_ROOT
    / "campaigns" / "ingolstadt_cooked_perception_v1" / "source"
    / "ingolstadt_buildings_overpass.json"
)


@pytest.mark.skipif(not _PINNED_BUILDINGS.exists(), reason="pinned buildings source absent")
class TestFullGridPartitionStructural:
    """Structural test against the real pinned source (no render).

    Verifies that the orchestrator's partition step -- which mirrors the probe --
    produces exactly the expected 20 occupied cells and that every tile would be
    attempted.
    """

    def test_all_20_tiles_enumerated_by_partition(self):
        from ultimate_pipeline.tiling.tile_fbx_generator import (
            load_buildings_from_overpass_json,
        )

        buildings = load_buildings_from_overpass_json(str(_PINNED_BUILDINGS))
        grid = TileGridSpec(
            tile_size_m=1000.0,
            header_offset_xy=(832671.676, 5458671.104),
        )
        assignment = assign_buildings_to_tiles(buildings, grid)

        n_cells = len(assignment.tiles)
        assert n_cells == 20, (
            f"Expected 20 occupied cells (matching probe), got {n_cells}. "
            "If the buildings source changed, re-verify the probe."
        )

    def test_cook_order_covers_all_cells_without_duplication(self):
        from ultimate_pipeline.tiling.tile_fbx_generator import (
            load_buildings_from_overpass_json,
        )

        buildings = load_buildings_from_overpass_json(str(_PINNED_BUILDINGS))
        grid = TileGridSpec(
            tile_size_m=1000.0,
            header_offset_xy=(832671.676, 5458671.104),
        )
        assignment = assign_buildings_to_tiles(buildings, grid)

        ordered = sorted(
            ((cell, len(bs)) for cell, bs in assignment.tiles.items()),
            key=lambda kv: (-kv[1], kv[0]),
        )
        tile_order = [cell for cell, _ in ordered]

        # All occupied cells appear exactly once in the cook order.
        assert len(tile_order) == len(set(tile_order)), "Duplicate cells in cook order"
        assert set(tile_order) == set(assignment.tiles.keys()), (
            "Cook order does not match occupied cells"
        )

    def test_densest_tile_is_first_in_cook_order(self):
        from ultimate_pipeline.tiling.tile_fbx_generator import (
            load_buildings_from_overpass_json,
        )

        buildings = load_buildings_from_overpass_json(str(_PINNED_BUILDINGS))
        grid = TileGridSpec(
            tile_size_m=1000.0,
            header_offset_xy=(832671.676, 5458671.104),
        )
        assignment = assign_buildings_to_tiles(buildings, grid)

        ordered = sorted(
            ((cell, len(bs)) for cell, bs in assignment.tiles.items()),
            key=lambda kv: (-kv[1], kv[0]),
        )
        first_cell, first_count = ordered[0]
        # The probe confirmed (6,8) is the densest tile.
        assert first_cell == (6, 8), (
            f"Expected densest tile (6,8) first, got {first_cell}"
        )
        # Threshold lowered from 626 to 625 (GAP-020): load_buildings_from_overpass_json's
        # relation loader used to treat ANY relation with outer/blank-role way members as
        # a building, without checking the relation itself was actually tagged
        # type=multipolygon + building=*. The pinned source contains OSM relation
        # 6180405 ("Neues Schloss" castle, Ingolstadt) which IS tagged building=yes but
        # is a type=site relation (an OSM grouping construct, not multipolygon ring
        # geometry) whose 11 way members are disparate related features, not a closed
        # ring assembly. The old code blindly stitched all 11 members' "outer" rings
        # into one bogus TileBuilding for this relation; the new code correctly requires
        # tags.get("type") == "multipolygon" and "building" in tags before treating a
        # relation as a building multipolygon, excluding this one relation. Verified
        # directly against the pinned Overpass JSON: exactly 1 of 19 relations fails
        # that check, matching the 626->625 (-1) count change exactly.
        assert first_count >= 625, (
            f"Densest tile should have >=625 buildings, got {first_count}"
        )

    def test_no_building_attempted_in_two_tiles(self):
        """Partition disjointness: no building source_id appears in two cook batches."""
        from ultimate_pipeline.tiling.tile_fbx_generator import (
            load_buildings_from_overpass_json,
        )

        buildings = load_buildings_from_overpass_json(str(_PINNED_BUILDINGS))
        grid = TileGridSpec(
            tile_size_m=1000.0,
            header_offset_xy=(832671.676, 5458671.104),
        )
        assignment = assign_buildings_to_tiles(buildings, grid)

        all_placed_ids = [
            b.source_id
            for cell_buildings in assignment.tiles.values()
            for b in cell_buildings
        ]
        assert len(all_placed_ids) == len(set(all_placed_ids)), (
            "Partition violation: at least one building would be cooked in two tiles"
        )
