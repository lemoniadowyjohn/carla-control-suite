# C3 OSM Input Guard

Date: 2026-08-15

## Verdict

`OSM_INPUT_GUARD_WIRED_GREEN`

The main OSM acquisition/conversion path now fails closed before reusing, downloading, or converting an OSM XML input that is empty, malformed, an HTML/API error response, or the wrong XML root.

## Change

- Added `OSMInputValidationError`, `looks_like_html_or_api_error`, and `validate_osm_xml_input` in `ultimate_pipeline/osm/osm_downloader.py`.
- Wired validation into `OSMDownloader.ensure_osm_xml_exists`.
- Wired validation into `OSMDownloader.download_xml`.
- Wired validation into `ultimate_pipeline/osm/osm_to_xodr_wrapper.py`.
- Wired validation into the direct `ultimate_pipeline/osm/osm_to_xodr.py` converter.

## Tests

Red state:

```text
ImportError: cannot import name 'OSMInputValidationError' from 'ultimate_pipeline.osm.osm_downloader'
```

Targeted green:

```text
tests/unit/test_osm_input_guard.py ......                                [ 50%]
tests/unit/test_lane_width_policy.py ......                              [100%]
12 passed in 0.25s
```

Direct script smoke:

```text
ultimate_pipeline/osm/osm_to_xodr.py --help exited 0
```

Full suite:

```text
721 passed, 49 warnings in 164.96s
```

## ESCALATE_TO_CLAUDE

None.
