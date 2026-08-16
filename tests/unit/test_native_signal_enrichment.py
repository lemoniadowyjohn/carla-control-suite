from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.signals.native_signal_enrichment import apply_native_signal_enrichment


def test_native_signal_enrichment_fails_closed_when_osm_missing(tmp_path: Path) -> None:
    xodr = tmp_path / "map.xodr"
    xodr.write_text(
        '<?xml version="1.0" encoding="utf-8"?><OpenDRIVE><header/></OpenDRIVE>',
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="OSM missing"):
        apply_native_signal_enrichment(
            xodr_path=xodr,
            osm_path=tmp_path / "missing.osm",
            min_signals=1,
        )
