# C0/C1 Auto Map Of Record Evidence

Date: 2026-08-15

## Verdict

`PARTIAL_VERIFIED_RETROFIT_NOT_PINNED`

The width-faithful auto candidate is real and passes the offline evidence checks I ran, but it is not a clean regenerated current-HEAD pipeline output. It was produced as the C5 file-level repair over the E2 candidate, so I did not pin it as the canonical auto map of record.

## Inputs

| Input | Path | SHA-256 | Status |
| --- | --- | --- | --- |
| OSM | `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm` | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` | Valid `<osm version="0.6">`, not HTML/API error |
| DEM | `cities/ingolstadt/dem/dem_ing.tif` | `3cfa665dde3782a015502beaf457854db2f639d01008a386c925d171e41f4ff8` | Present |

## Candidate Checked

| Field | Value |
| --- | --- |
| Path | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_drivable_width_faithful.xodr` |
| SHA-256 | `928e5b2397c9eb85448542178766ce8093f4f4457dabf4a7e2c86952b5898b2b` |
| Parent | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_drivable.xodr` |
| Parent SHA-256 | `352c9003e653027f41ecda5ef11f59a11b07b0ce7294ea1d7d21e4bcc7e63c52` |
| Provenance | C5 retrofit, not clean C0 regeneration |
| Committed | No, large generated artifact |

## Verification

| Check | Result |
| --- | ---: |
| Roads | 32,710 |
| Junctions | 3,646 |
| Signals | 3,467 |
| Objects | 66 |
| Driving width records | 34,679 |
| 6.0 m placeholder widths | 0 |
| Width distribution | 3.0 m: 462; 3.25 m: 2,355; 3.5 m: 31,777; 3.75 m: 85 |
| Median driving width | 3.5 m |
| Non-zero elevation records | 418,243 |
| Elevation range | 360.79471 m to 412.890089 m |
| G19 length-invariant violations | 0 / 32,710 |
| Preflight status | ok |
| Preflight errors | 0 |
| Preflight warnings | 80,265 (`geom_xy_large`: 80,261; `elev_jump`: 4) |

## Pinning Decision

I did not update `ultimate_pipeline/carla_tools/map_registry.py`.

Reason: strict C0 acceptance says the auto map of record must be regenerated through the governed OSM-to-XODR path at the current pushed commit. The candidate above is verified, but its provenance is explicitly a retrofit over the E2 artifact. Pinning it as if it were a clean regenerated map would weaken the audit trail.

## Required Next Step

Either:

1. Run the governed current-HEAD OSM-to-XODR regeneration and then pin that output.
2. Explicitly approve retrofit provenance as acceptable for the auto map of record, then pin SHA `928e5b2397c9eb85448542178766ce8093f4f4457dabf4a7e2c86952b5898b2b`.

## ESCALATE_TO_CLAUDE

- Decide whether retrofit provenance is acceptable for the auto map of record.
- If full regeneration is mandatory, identify the governed generation entrypoint and required config; `ultimate_pipeline.cli` does not currently expose a production map-generation command.
