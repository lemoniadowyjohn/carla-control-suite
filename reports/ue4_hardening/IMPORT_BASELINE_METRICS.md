# Import Baseline Metrics

Source log: `G:\CARLA\build_logs\ingolstadt_import_20261004T001601Z.log`

SHA256: `f984b0b45f93bd4ec5b5e669f43446fd488aee23a1386d2abaeb33ef90856176`

Measurement tool: `tools/ue4_import_log_analysis.py` (deterministic).

## Run window

| metric | value |
| --- | --- |
| first timestamp | 2026.10.04-00.18.06:237 |
| last timestamp | 2026.10.04-17.03.54:710 |
| duration | 60348 s (16.76 h) |
| **terminal state** | **SUCCESS_MARKER_MIDSTREAM_NOT_TERMINAL** |
| success marker at line | 814 of 26647 |

## Warning categories

| category | count |
| --- | --- |
| ASSET_RESOLUTION | 5733 |
| TANGENT_BINORMAL | 934 |
| ASSET_MANAGER_DUPLICATE | 403 |
| OTHER | 310 |
| SMOOTHING_GROUP | 26 |
| DDC | 6 |
| CONSOLE_LOOKUP_PERFORMANCE | 2 |

## Distance field (the dominant cost)

| metric | value |
| --- | --- |
| count | 27 |
| total_seconds | 31556.59 |
| total_hours | 8.766 |
| max_seconds | 2807.558 |
| p50_seconds | 1340.095 |
| p95_seconds | 2474.528 |
| p99_seconds | 2746.629 |
| over_10s | 26 |
| over_60s | 21 |
| over_300s | 20 |
| worst_mesh | Ingolstadt_Tile_7_8_Building_Bavaria |
| share of wall clock | 0.5229 |

### Worst individual meshes

| seconds | minutes | mesh | emitted at |
| --- | --- | --- | --- |
| 2807.558 | 46.79 | Ingolstadt_Tile_7_8_Building_Bavaria | 2026.10.04-11.05.22:599 |
| 2573.217 | 42.89 | Ingolstadt_Tile_6_8_Building_Abele_Optik | 2026.10.04-09.07.12:073 |
| 2244.255 | 37.40 | Ingolstadt_Tile_8_8_Building_Backhaus_Hackner | 2026.10.04-13.08.23:615 |
| 1935.085 | 32.25 | Ingolstadt_Tile_7_7_Building_Autohaus_Stock | 2026.10.04-10.17.44:250 |
| 1910.292 | 31.84 | Ingolstadt_Tile_9_9_Building_La_Piazzetta | 2026.10.04-14.27.14:232 |
| 1882.686 | 31.38 | Ingolstadt_Tile_6_7_Building_Antalya | 2026.10.04-17.03.26:285 |
| 1881.549 | 31.36 | Ingolstadt_Tile_7_9_Building_Kleeblattl | 2026.10.04-11.37.34:406 |
| 1851.614 | 30.86 | Ingolstadt_Tile_8_7_Building_Apart_Ebner | 2026.10.04-12.29.46:078 |
| 1824.995 | 30.42 | Ingolstadt_Tile_6_7_Building_Antalya | 2026.10.04-08.20.59:436 |
| 1763.606 | 29.39 | Ingolstadt_Tile_10_9_Building_Kita_Am_Blumenviertel | 2026.10.04-01.13.24:873 |
| 1548.885 | 25.81 | Ingolstadt_Tile_7_6_Building_Donauhotel | 2026.10.04-09.44.56:008 |
| 1500.838 | 25.01 | Ingolstadt_Tile_8_9_Building_Hotel_NH_Ingolstadt | 2026.10.04-13.34.38:965 |
| 1435.126 | 23.92 | Ingolstadt_Tile_10_9_Building_Kita_Am_Blumenviertel | 2026.10.04-16.10.12:591 |
| 1340.095 | 22.33 | Ingolstadt_Tile_6_6_Building_Kche_-_gut_und_gnstig | 2026.10.04-01.37.24:784 |
| 1210.857 | 20.18 | Ingolstadt_Tile_8_6_Building1 | 2026.10.04-11.58.09:867 |
| 1162.207 | 19.37 | Ingolstadt_Tile_6_6_Building_Kche_-_gut_und_gnstig | 2026.10.04-16.30.32:319 |
| 991.211 | 16.52 | Ingolstadt_Tile_9_8_Building0 | 2026.10.04-13.54.22:726 |
| 660.796 | 11.01 | Ingolstadt_Tile_6_9_Building_Istanbul_Market | 2026.10.04-09.18.58:576 |
| 434.543 | 7.24 | Ingolstadt_Tile_10_7_Building_CA33 | 2026.10.04-00.42.00:449 |
| 328.990 | 5.48 | Ingolstadt_Tile_10_7_Building_CA33 | 2026.10.04-15.43.42:988 |
| 124.713 | 2.08 | Ingolstadt_Tile_9_7_Building_Anglerverein_Ingolstadt | 2026.10.04-13.37.36:368 |
| 34.342 | 0.57 | Ingolstadt_Tile_9_6_Building_Mechanische_Werksttte_001 | 2026.10.04-13.35.30:709 |
| 31.997 | 0.53 | Ingolstadt_Tile_10_6_Building_tedox | 2026.10.04-00.34.26:534 |
| 30.225 | 0.50 | Ingolstadt_Tile_10_8_Building_Rampe | 2026.10.04-00.42.39:630 |
| 25.349 | 0.42 | Ingolstadt_Tile_10_6_Building_tedox | 2026.10.04-15.37.53:435 |
| 20.974 | 0.35 | Ingolstadt_Tile_10_8_Building_Rampe | 2026.10.04-15.45.12:716 |
| 0.585 | 0.01 | Ingolstadt_Tile_9_8_Building_Penny_Ingolstadt_Mailing | 2026.10.04-13.54.26:996 |

## Shaders

| metric | value |
| --- | --- |
| queue_first_observed | 3084 |
| queue_last_observed | 1 |
| queue_min_observed | 1 |
| worker_denominators | [9] |
| worker_progress_samples | 17138 |
| observed_compile_span_seconds | 0.0 |

## Geometry warnings

| metric | value |
| --- | --- |
| smoothing_group_warnings | 27 |
| tangent_degenerate_total | 438 |
| tangent_degenerate_unique_meshes | 190 |
| binormal_nearly_zero_total | 496 |
| binormal_nearly_zero_unique_meshes | 212 |

## Asset manager / resolution

| metric | value |
| --- | --- |
| duplicate PrimaryAssetID (all verbosities) | 775 |
| duplicate PrimaryAssetID (warning verbosity) | 403 |
| unique colliding IDs | 2 |
| failed to find object (total / unique) | 5720 / 5711 |

Colliding PrimaryAssetIDs:

- `Map:/Game/Carla/Maps/BaseLargeMap/LargeMap`
- `Map:/Game/Carla/Maps/TestMaps/EmptyMap`

