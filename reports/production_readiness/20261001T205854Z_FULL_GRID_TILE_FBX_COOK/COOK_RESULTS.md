# Full-Grid Per-Tile FBX Cook -- 20261001T205854Z

- **Run ID:** `20261001T205854Z`
- **Branch:** `feature/full-grid-tile-fbx-cook-v1-20260915`
- **Tiles attempted:** 20
- **Tiles OK:** 12
- **Tiles failed:** 8
- **Roundtrip PASS:** 12
- **Roundtrip FAIL:** 0
- **Wall clock:** 226.3s
- **Claim boundary:** Offline FBX generation only. No UE4/UE5 Editor invoked.

## Per-Tile Results

| tile (tx,ty) | buildings | objects | vertices | faces | FBX size (KB) | roundtrip | total_sec | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| (6,8) | 625 | 0 | 0 | 0 | 0.0 |  | 5.05 | failed |
| (7,8) | 573 | 0 | 0 | 0 | 0.0 |  | 4.537 | failed |
| (8,8) | 493 | 0 | 0 | 0 | 0.0 |  | 4.047 | failed |
| (7,9) | 429 | 0 | 0 | 0 | 0.0 |  | 3.887 | failed |
| (7,7) | 411 | 0 | 0 | 0 | 0.0 |  | 4.901 | failed |
| (8,7) | 409 | 0 | 0 | 0 | 0.0 |  | 4.482 | failed |
| (6,7) | 395 | 0 | 0 | 0 | 0.0 |  | 4.451 | failed |
| (9,9) | 395 | 395 | 9075 | 14219 | 1095.5 | ROUNDTRIP_PASS | 22.158 | ok |
| (8,9) | 353 | 353 | 8935 | 13818 | 1004.1 | ROUNDTRIP_PASS | 21.859 | ok |
| (7,6) | 326 | 326 | 5989 | 8896 | 857.5 | ROUNDTRIP_PASS | 18.306 | ok |
| (10,9) | 303 | 303 | 5544 | 8443 | 799.1 | ROUNDTRIP_PASS | 18.245 | ok |
| (6,6) | 263 | 263 | 6508 | 10265 | 753.9 | ROUNDTRIP_PASS | 19.242 | ok |
| (8,6) | 263 | 263 | 3432 | 4874 | 646.2 | ROUNDTRIP_PASS | 16.017 | ok |
| (9,8) | 193 | 193 | 2712 | 3938 | 487.7 | ROUNDTRIP_PASS | 13.532 | ok |
| (6,9) | 159 | 0 | 0 | 0 | 0.0 |  | 4.178 | failed |
| (10,7) | 74 | 74 | 892 | 1175 | 190.5 | ROUNDTRIP_PASS | 14.147 | ok |
| (9,7) | 28 | 28 | 260 | 326 | 77.4 | ROUNDTRIP_PASS | 11.284 | ok |
| (9,6) | 8 | 8 | 76 | 98 | 31.7 | ROUNDTRIP_PASS | 11.469 | ok |
| (10,6) | 6 | 6 | 72 | 93 | 27.2 | ROUNDTRIP_PASS | 11.71 | ok |
| (10,8) | 5 | 5 | 60 | 80 | 24.9 | ROUNDTRIP_PASS | 10.816 | ok |

## Source Provenance

```json
{
  "buildings_source": "campaigns\\ingolstadt_cooked_perception_v1\\source\\ingolstadt_buildings_overpass.json",
  "buildings_source_sha256": "f3e8200118845910e136b478a68bd6eb67b985fef6357b98f76ecc6f520e30f5",
  "map_of_record": "campaigns\\ingolstadt_cooked_perception_v1\\candidate\\ingolstadt_perception_map_of_record_20260916_232831.xodr",
  "map_of_record_sha256": "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8",
  "header_offset_xy": [
    832671.676,
    5458671.104
  ],
  "tile_size_m": 1000.0,
  "provenance_authority": "verify_pinned_map('auto_map_of_record')",
  "registry_sha256": "884ce8b49335bac69f4f89e33c67f8f6fed10bcb616c535d4f420e4cd91790a9"
}
```

## Anomalies

- tile [6, 8]: status=failed reason='OSM2World status=failed: OSM2World did not produce any requested outputs' roundtrip=
- tile [7, 8]: status=failed reason='OSM2World status=failed: OSM2World did not produce any requested outputs' roundtrip=
- tile [8, 8]: status=failed reason='OSM2World status=failed: OSM2World did not produce any requested outputs' roundtrip=
- tile [7, 9]: status=failed reason='OSM2World status=failed: OSM2World did not produce any requested outputs' roundtrip=
- tile [7, 7]: status=failed reason='OSM2World status=failed: OSM2World did not produce any requested outputs' roundtrip=
- tile [8, 7]: status=failed reason='OSM2World status=failed: OSM2World did not produce any requested outputs' roundtrip=
- tile [6, 7]: status=failed reason='OSM2World status=failed: OSM2World did not produce any requested outputs' roundtrip=
- tile [6, 9]: status=failed reason='OSM2World status=failed: OSM2World did not produce any requested outputs' roundtrip=
