# C0 Offline Buildings Guard

Date: 2026-08-15

## Verdict

`C0_OFFLINE_BUILDINGS_GREEN`

## Failure

During clean C0 regeneration, stage 4 attempted live Overpass downloads for `buildings.geojson` because the local
GeoJSON was absent. That breaks the offline/reproducible C0 contract even though the raw authoritative OSM source is
already available and the building loader has an OSM XML fallback.

## Fix

`ultimate_pipeline/pipeline_stages/stage_04_enrichment.py` now skips building-GeoJSON download when offline mode is
enabled through either:

- `settings.OFFLINE_ONLY=True`
- `UP_OFFLINE_ONLY=1`

If a local `buildings.geojson` exists, it is still used. If it is missing in offline mode, the path resolves to
`None` and the existing raw OSM XML fallback handles building extraction.

`ultimate_pipeline/config/settings.py` now reads `UP_OFFLINE_ONLY` into `settings.OFFLINE_ONLY`, so run manifests can
reflect the offline intent.

## Evidence

Targeted red:

```text
ImportError: cannot import name 'resolve_buildings_geojson_for_stage4'
```

Targeted green:

```text
4 passed in 0.10s
```

Full suite:

```text
744 passed, 49 warnings in 164.02s (0:02:44)
```

## ESCALATE_TO_CLAUDE

- The next C0 rerun should set `UP_OFFLINE_ONLY=1` so the run is both behaviorally offline and provenance-visible as
  offline.
