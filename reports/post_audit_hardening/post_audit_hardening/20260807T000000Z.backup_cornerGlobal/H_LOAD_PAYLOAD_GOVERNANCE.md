# Stage H - Governed exact CARLA load payload (Phase Q4 Strategy B)

## Verdict: `H_GOVERNED_PAYLOAD_EXACT`

The loader normalizes `<geoReference>` in memory, so the bytes CARLA consumes
differ from the committed candidate file.  Stage H governs that hidden
transformation: a byte-exact load-payload artifact is produced before CARLA
execution, and release mode rejects any runtime-only transformation.

## Artifacts
| artifact | path |
|---|---|
| Q03 load-payload manifest | `Q03_LOAD_PAYLOAD_MANIFEST.json` |
| Q04 georeference semantic diff | `Q04_GEOREFERENCE_SEMANTIC_DIFF.json` |
| governed payload (byte-exact) | `governed_payload.xodr` |
| Stage H report | `H_LOAD_PAYLOAD_GOVERNANCE.json` |

## Hash chain reconciliation
| element | SHA-256 |
|---|---|
| repaired candidate raw bytes (`ingolstadt_fixed_final.xodr`) | `80ebb0054afd7...` (matches signed repaired SHA) |
| repaired candidate LF text (= P04 `payload_sha256`) | `516e329cb6fc...` (matches recorded) |
| enriched semantic candidate raw bytes | `8b60d8f428c7...` |
| enriched candidate LF text | `d604ac393e12...` |
| **governed payload** (canonical) | `3f7370ef5ff0...` (raw bytes == manifest hash) |
| runtime `to_opendrive()` recorded (P4/Phase L) | `9630d9f673fd...` |

## Coordinate contract (georeference normalization invariance)
| check | result |
|---|---|
| road_ids_equal | PASS |
| junction_ids_equal | PASS |
| signal_ids_equal | PASS |
| object_ids_equal | PASS |
| header_bounds_equal | PASS |
| offset_equal | PASS |
| coordinate_contract_pass | **PASS** |

The only semantic difference between the enriched candidate and the governed
payload is the canonicalized single-line `<geoReference>` text plus ElementTree
reserialization.  Road, junction, lane, signal and object identity, header
bounds and offset are structurally invariant.

## Release-mode verifier
`release_payload_verifier` self-tests:
- exact governed bytes: accepted
- mismatched bytes: `RuntimeError` raised (`release_mode_governed_payload_mismatch`)

## Line-ending note
`save_text` writes `\n`-terminated text which Windows stores as CRLF; the
governed payload artifact is re-written byte-exact (LF) so its raw file hash
equals the canonical manifest hash and the artifact is platform-stable.
