# Full-Grid Per-Tile FBX Cook -- 20260924T100614Z

- **Run ID:** `20260924T100614Z`
- **Branch:** `feature/full-grid-tile-fbx-cook-v1-20260915`
- **Tiles attempted:** 20
- **Tiles OK:** 20
- **Tiles failed:** 0
- **Roundtrip PASS:** 20
- **Roundtrip FAIL:** 0
- **Wall clock:** 448.5s
- **Claim boundary:** Offline FBX generation only. No UE4/UE5 Editor invoked.

## Per-Tile Results

| tile (tx,ty) | buildings | objects | vertices | faces | FBX size (KB) | roundtrip | total_sec | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| (6,8) | 625 | 625 | 9928 | 13789 | 1565.7 | ROUNDTRIP_PASS | 31.732 | ok |
| (7,8) | 573 | 573 | 11671 | 17746 | 1543.4 | ROUNDTRIP_PASS | 30.699 | ok |
| (8,8) | 493 | 493 | 7992 | 11821 | 1249.4 | ROUNDTRIP_PASS | 26.365 | ok |
| (7,9) | 429 | 429 | 9022 | 13731 | 1171.4 | ROUNDTRIP_PASS | 28.975 | ok |
| (7,7) | 411 | 411 | 10341 | 15892 | 1149.6 | ROUNDTRIP_PASS | 23.859 | ok |
| (8,7) | 409 | 409 | 6496 | 9357 | 1038.3 | ROUNDTRIP_PASS | 19.205 | ok |
| (6,7) | 395 | 395 | 5867 | 8059 | 984.7 | ROUNDTRIP_PASS | 20.576 | ok |
| (9,9) | 395 | 395 | 9075 | 14219 | 1095.5 | ROUNDTRIP_PASS | 21.218 | ok |
| (8,9) | 353 | 353 | 8935 | 13818 | 1004.1 | ROUNDTRIP_PASS | 22.685 | ok |
| (7,6) | 326 | 326 | 5989 | 8896 | 857.5 | ROUNDTRIP_PASS | 23.208 | ok |
| (10,9) | 303 | 303 | 5544 | 8443 | 799.1 | ROUNDTRIP_PASS | 22.128 | ok |
| (6,6) | 263 | 263 | 6508 | 10265 | 753.9 | ROUNDTRIP_PASS | 23.898 | ok |
| (8,6) | 263 | 263 | 3432 | 4874 | 646.2 | ROUNDTRIP_PASS | 22.574 | ok |
| (9,8) | 193 | 193 | 2712 | 3938 | 487.7 | ROUNDTRIP_PASS | 21.002 | ok |
| (6,9) | 159 | 159 | 3499 | 5372 | 438.1 | ROUNDTRIP_PASS | 22.411 | ok |
| (10,7) | 74 | 74 | 892 | 1175 | 190.5 | ROUNDTRIP_PASS | 23.41 | ok |
| (9,7) | 28 | 28 | 260 | 326 | 77.4 | ROUNDTRIP_PASS | 15.014 | ok |
| (9,6) | 8 | 8 | 76 | 98 | 31.7 | ROUNDTRIP_PASS | 13.685 | ok |
| (10,6) | 6 | 6 | 72 | 93 | 27.2 | ROUNDTRIP_PASS | 17.389 | ok |
| (10,8) | 5 | 5 | 60 | 80 | 24.9 | ROUNDTRIP_PASS | 17.435 | ok |

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
  "tile_size_m": 1000.0
}
```

## Anomalies

None.
