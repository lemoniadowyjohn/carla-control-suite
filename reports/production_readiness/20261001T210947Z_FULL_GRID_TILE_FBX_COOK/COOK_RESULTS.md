# Full-Grid Per-Tile FBX Cook -- 20261001T210947Z

- **Run ID:** `20261001T210947Z`
- **Branch:** `feature/full-grid-tile-fbx-cook-v1-20260915`
- **Tiles attempted:** 20
- **Tiles OK:** 12
- **Tiles failed:** 8
- **Roundtrip PASS:** 12
- **Roundtrip FAIL:** 0
- **Wall clock:** 262.1s
- **Claim boundary:** Offline FBX generation only. No UE4/UE5 Editor invoked.

## Per-Tile Results

| tile (tx,ty) | buildings | objects | vertices | faces | FBX size (KB) | roundtrip | total_sec | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| (6,8) | 625 | 0 | 0 | 0 | 0.0 |  | 7.283 | failed |
| (7,8) | 573 | 0 | 0 | 0 | 0.0 |  | 7.221 | failed |
| (8,8) | 493 | 0 | 0 | 0 | 0.0 |  | 6.325 | failed |
| (7,9) | 429 | 0 | 0 | 0 | 0.0 |  | 6.24 | failed |
| (7,7) | 411 | 0 | 0 | 0 | 0.0 |  | 7.264 | failed |
| (8,7) | 409 | 0 | 0 | 0 | 0.0 |  | 6.151 | failed |
| (6,7) | 395 | 0 | 0 | 0 | 0.0 |  | 6.744 | failed |
| (9,9) | 395 | 395 | 9075 | 14219 | 1095.5 | ROUNDTRIP_PASS | 24.78 | ok |
| (8,9) | 353 | 353 | 8935 | 13818 | 1004.1 | ROUNDTRIP_PASS | 25.378 | ok |
| (7,6) | 326 | 326 | 5989 | 8896 | 857.5 | ROUNDTRIP_PASS | 17.532 | ok |
| (10,9) | 303 | 303 | 5544 | 8443 | 799.1 | ROUNDTRIP_PASS | 19.152 | ok |
| (6,6) | 263 | 263 | 6508 | 10265 | 753.9 | ROUNDTRIP_PASS | 20.391 | ok |
| (8,6) | 263 | 263 | 3432 | 4874 | 646.2 | ROUNDTRIP_PASS | 18.986 | ok |
| (9,8) | 193 | 193 | 2712 | 3938 | 487.7 | ROUNDTRIP_PASS | 19.239 | ok |
| (6,9) | 159 | 0 | 0 | 0 | 0.0 |  | 6.261 | failed |
| (10,7) | 74 | 74 | 892 | 1175 | 190.5 | ROUNDTRIP_PASS | 13.919 | ok |
| (9,7) | 28 | 28 | 260 | 326 | 77.4 | ROUNDTRIP_PASS | 12.025 | ok |
| (9,6) | 8 | 8 | 76 | 98 | 31.7 | ROUNDTRIP_PASS | 11.955 | ok |
| (10,6) | 6 | 6 | 72 | 93 | 27.2 | ROUNDTRIP_PASS | 10.73 | ok |
| (10,8) | 5 | 5 | 60 | 80 | 24.9 | ROUNDTRIP_PASS | 12.169 | ok |

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
