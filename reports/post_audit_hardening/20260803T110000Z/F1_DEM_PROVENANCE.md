# F1 — DEM provenance, validity, and coverage

- run_id: `20260803T110000Z`  - status: **PASS**
- generated_at_utc: `2026-08-03T10:31:09.720912+00:00`

## CRS contract

- verdict: **OSM2ODR_NATIVE_VERIFIED** (claimed_geoReference_disproven;osm2odr_native_frame_matches_osm)
- claimed header CRS: `+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs +type=crs`
- claimed-CRS placement of header bounds (WGS84): `{'lon_min': 13.56642001213345, 'lat_min': 49.190451605186034, 'lon_max': 13.76006739410691, 'lat_max': 49.30926083210751}`
- verified native frame: `+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs`
- native-frame placement of header bounds (WGS84): `{'lon_min': 11.322214553035723, 'lat_min': 48.70193914570195, 'lon_max': 11.527611357975239, 'lat_max': 48.808196059136904}`
- OSM source node bounds (WGS84): `{'lat_min': 48.6843318, 'lat_max': 48.8143429, 'lon_min': 11.3266919, 'lon_max': 11.5382271}`
- WP1 control point error under claimed CRS: `171725 m`

## True map extent (WGS84)

- `11.322215 .. 11.527513 E, 48.701939 .. 48.808207 N`
- sampling CRS source: `osm2odr_native_verified`

## DEM identity

- path: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\cities\ingolstadt\dem\dem_ing.tif`
- SHA-256: `583751dc3b2849628a827e1840a1c34b8d3d730b820ccd9f0a127d334a27a206`
- CRS: `GEOGCS["WGS 84",DATUM["World Geodetic System 1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AXIS["Latitude",NORTH],AXIS["Longitude",EAST]]`
- vertical datum: `EGM2008 (Copernicus DEM geoid-referenced heights)`
- bounds (degrees): `{'left': 11.312083322222236, 'bottom': 48.69208334444444, 'right': 11.537361100000014, 'top': 48.81847223333333}`
- resolution: `{'x': 0.0002777777777777778, 'y': 0.0002777777777777778}`  size: 811x455
- no-data: `None`
- elevation min/max/mean: 346.7928161621094/431.9171447753906/374.773193359375 m
- provider: `COP30`
- licence: `Copernicus DEM GLO-30 (Copernicus WorldDEM-30) distributed by OpenTopography; free of charge for all purposes under the Copernicus regulation policy.`

## Coverage gate

- verdict: **True** (covered)
- DEM bounds vs map extent overlap: `{'lon_min': 11.322214547562044, 'lat_min': 48.701939121121065, 'lon_max': 11.527512789923767, 'lat_max': 48.80820708731479}`

F1 gates (CRS contract resolvable, DEM identity complete, full map coverage) must ALL pass before F2..F7 may proceed.