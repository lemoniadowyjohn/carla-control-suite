"""Tests for the runtime-tile loading contract without a CARLA server."""

from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.carla_tools.tile_world_runner import TileLoadResult, TileWorldRunner
from ultimate_pipeline.tiling.runtime_tile_builder import RuntimeTileRequest, build_runtime_tile

from tests.unit.test_runtime_tile_builder import _write_source


class _Client:
    def set_timeout(self, timeout: float) -> None:
        self.timeout = timeout


def _runtime_tile(tmp_path: Path) -> Path:
    source = tmp_path / "source.xodr"
    output = tmp_path / "runtime.xodr"
    _write_source(source)
    build_runtime_tile(
        RuntimeTileRequest(
            input_xodr=source,
            output_xodr=output,
            center_x=5.0,
            center_y=0.0,
            tile_size_m=20.0,
            buffer_m=0.0,
        )
    )
    return output


def test_runtime_loader_rejects_unmanifested_tile_without_importing_carla(tmp_path: Path) -> None:
    tile = _runtime_tile(tmp_path)
    tile.with_suffix(".runtime_tile.json").unlink()

    result = TileWorldRunner(_Client()).load_runtime_tile(str(tile))

    assert result.ok is False
    assert result.reason == "runtime_tile_manifest_not_found"


def test_runtime_loader_checks_manifest_and_delegates_only_after_static_validation(tmp_path: Path, monkeypatch) -> None:
    tile = _runtime_tile(tmp_path)
    runner = TileWorldRunner(_Client())
    calls: list[tuple[str, bool, float]] = []

    def _load(path: str, *, reset_world: bool, sleep_sec: float) -> TileLoadResult:
        calls.append((path, reset_world, sleep_sec))
        return TileLoadResult(tile_path=path, ok=True)

    monkeypatch.setattr(runner, "load", _load)
    result = runner.load_runtime_tile(str(tile), reset_world=False, sleep_sec=0.0)

    assert result.ok is True
    assert calls == [(str(tile.resolve()), False, 0.0)]


def test_runtime_loader_rejects_tampered_tile_before_carla_load(tmp_path: Path, monkeypatch) -> None:
    tile = _runtime_tile(tmp_path)
    tile.write_bytes(tile.read_bytes() + b"\n<!-- tampered -->\n")
    runner = TileWorldRunner(_Client())
    monkeypatch.setattr(runner, "load", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not load")))

    result = runner.load_runtime_tile(str(tile))

    assert result.ok is False
    assert result.reason == "runtime_tile_hash_mismatch"
