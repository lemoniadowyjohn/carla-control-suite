"""Offline CLI coverage for the runtime tile build command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ultimate_pipeline.cli import cli
from tests.unit.test_runtime_tile_builder import _write_source


def test_tile_build_runtime_emits_a_hash_bound_runtime_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source.xodr"
    output = tmp_path / "runtime.xodr"
    _write_source(source)

    result = CliRunner().invoke(
        cli,
        [
            "tile",
            "build-runtime",
            "--input-xodr",
            str(source),
            "--output-xodr",
            str(output),
            "--center-x",
            "5",
            "--center-y",
            "0",
            "--tile-size-m",
            "20",
            "--buffer-m",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "READY_FOR_LIVE_CARLA_VALIDATION"
    assert Path(payload["tile_path"]).is_file()
    assert Path(payload["manifest_path"]).is_file()


def test_tile_load_runtime_help_does_not_import_or_start_carla() -> None:
    result = CliRunner().invoke(cli, ["tile", "load-runtime", "--help"])

    assert result.exit_code == 0
    assert "explicitly running CARLA server" in result.output
