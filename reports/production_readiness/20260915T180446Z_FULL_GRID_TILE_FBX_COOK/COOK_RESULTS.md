# Full-Grid Per-Tile FBX Cook -- 20260915T180446Z

- **Run ID:** `20260915T180446Z`
- **Branch:** `feature/full-grid-tile-fbx-cook-v1-20260915`
- **Tiles attempted:** 20
- **Tiles OK:** 20
- **Tiles failed:** 0
- **Roundtrip PASS:** 20
- **Roundtrip FAIL:** 0
- **Wall clock:** 331.5s
- **Claim boundary:** Offline FBX generation only. No UE4/UE5 Editor invoked.

## Per-Tile Results

| tile (tx,ty) | buildings | objects | vertices | faces | FBX size (KB) | roundtrip | total_sec | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| (6,8) | 626 | 636 | 10112 | 14031 | 1593.2 | ROUNDTRIP_PASS | 19.948 | ok |
| (7,8) | 573 | 573 | 11629 | 17681 | 1542.0 | ROUNDTRIP_PASS | 21.301 | ok |
| (8,8) | 493 | 493 | 7984 | 11807 | 1249.2 | ROUNDTRIP_PASS | 18.88 | ok |
| (7,9) | 429 | 429 | 9014 | 13717 | 1171.1 | ROUNDTRIP_PASS | 20.65 | ok |
| (7,7) | 411 | 411 | 10197 | 15672 | 1144.5 | ROUNDTRIP_PASS | 15.891 | ok |
| (8,7) | 409 | 409 | 6480 | 9329 | 1037.7 | ROUNDTRIP_PASS | 15.565 | ok |
| (6,7) | 395 | 395 | 5785 | 7932 | 981.8 | ROUNDTRIP_PASS | 15.409 | ok |
| (9,9) | 395 | 395 | 9075 | 14219 | 1095.5 | ROUNDTRIP_PASS | 14.775 | ok |
| (8,9) | 353 | 353 | 8935 | 13818 | 1004.1 | ROUNDTRIP_PASS | 17.473 | ok |
| (7,6) | 326 | 326 | 5989 | 8896 | 857.5 | ROUNDTRIP_PASS | 18.896 | ok |
| (10,9) | 303 | 303 | 5544 | 8443 | 799.1 | ROUNDTRIP_PASS | 15.586 | ok |
| (6,6) | 263 | 263 | 6508 | 10265 | 753.9 | ROUNDTRIP_PASS | 14.228 | ok |
| (8,6) | 263 | 263 | 3432 | 4874 | 646.2 | ROUNDTRIP_PASS | 14.276 | ok |
| (9,8) | 193 | 193 | 2712 | 3938 | 487.7 | ROUNDTRIP_PASS | 14.913 | ok |
| (6,9) | 159 | 159 | 3487 | 5352 | 437.8 | ROUNDTRIP_PASS | 18.475 | ok |
| (10,7) | 74 | 74 | 892 | 1175 | 190.5 | ROUNDTRIP_PASS | 16.184 | ok |
| (9,7) | 28 | 28 | 260 | 326 | 77.4 | ROUNDTRIP_PASS | 16.355 | ok |
| (9,6) | 8 | 8 | 76 | 98 | 31.7 | ROUNDTRIP_PASS | 14.838 | ok |
| (10,6) | 6 | 6 | 72 | 93 | 27.2 | ROUNDTRIP_PASS | 12.9 | ok |
| (10,8) | 5 | 5 | 60 | 80 | 24.9 | ROUNDTRIP_PASS | 14.45 | ok |

## Source Provenance

```json
{
  "buildings_source": "campaigns\\ingolstadt_cooked_perception_v1\\source\\ingolstadt_buildings_overpass.json",
  "buildings_source_sha256": "f3e8200118845910e136b478a68bd6eb67b985fef6357b98f76ecc6f520e30f5",
  "map_of_record": "campaigns\\ingolstadt_cooked_perception_v1\\candidate\\ingolstadt_perception_map_of_record_20260905_202847.xodr",
  "map_of_record_sha256": "2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798",
  "header_offset_xy": [
    832671.676,
    5458671.104
  ],
  "tile_size_m": 1000.0
}
```

## Anomalies

None.
