from __future__ import annotations

import pytest

from ultimate_pipeline.osm.osm_downloader import (
    OSMDownloader,
    OSMInputValidationError,
    validate_osm_xml_input,
)


def test_validate_osm_xml_input_accepts_nonempty_osm(tmp_path):
    osm = tmp_path / "valid.osm"
    osm.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <node id="1" lat="48.0" lon="11.0" />
  <way id="2"><nd ref="1" /><tag k="highway" v="residential" /></way>
</osm>
""",
        encoding="utf-8",
    )

    assert validate_osm_xml_input(osm) == osm


@pytest.mark.parametrize(
    ("name", "payload", "message"),
    [
        ("empty.osm", "", "empty"),
        ("html.osm", "<html><body>Overpass timeout</body></html>", "HTML/API error"),
        (
            "api_error.osm",
            '<?xml version="1.0"?><osm version="0.6"><remark>runtime error: query timed out</remark></osm>',
            "HTML/API error",
        ),
        (
            "wrong_root.osm",
            '<?xml version="1.0"?><osm-script><query type="way" /></osm-script>',
            "root element",
        ),
    ],
)
def test_validate_osm_xml_input_rejects_bad_inputs(tmp_path, name, payload, message):
    osm = tmp_path / name
    osm.write_text(payload, encoding="utf-8")

    with pytest.raises(OSMInputValidationError, match=message):
        validate_osm_xml_input(osm)


def test_ensure_existing_osm_validates_before_reuse(tmp_path):
    osm = tmp_path / "bad.osm"
    osm.write_text("<html>not osm</html>", encoding="utf-8")

    with pytest.raises(OSMInputValidationError, match="HTML/API error"):
        OSMDownloader().ensure_osm_xml_exists(
            {"lat_min": 0.0, "lat_max": 1.0, "lon_min": 0.0, "lon_max": 1.0},
            osm,
        )
