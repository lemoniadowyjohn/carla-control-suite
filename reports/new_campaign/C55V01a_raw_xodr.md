# C55V01a Raw XODR

Verdict: SOURCE_MATCHED_RAW_XODR_STAGED

Generated two raw XODR candidates from the pinned OSM using the reviewed donor conversion path.

| Artifact | SHA-256 | Semantic SHA-256 | Bytes |
| --- | --- | --- | --- |
| raw run 1 | 6044a87d8d6e116b444fe4413a46ab97085033def004b62d011233f4ddc0e93d | 019fc30e989e596b6dedccf82aefa4bad011b0c54ed3e5f185d8b262824ec84e | 82318841 |
| raw run 2 | c8c57c7282f483592802307aa9ccc839eedf1468279690afa612b0bcd59734c2 | 019fc30e989e596b6dedccf82aefa4bad011b0c54ed3e5f185d8b262824ec84e | 82318841 |
| EPSG:32632 header-pinned candidate | ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d | 019fc30e989e596b6dedccf82aefa4bad011b0c54ed3e5f185d8b262824ec84e | 82318919 |

GeoReference: `+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs`
Roads: 32710
Junctions: 3646
LaneLinks: 32040
Signals: 0
Vertical datum: `LOCAL_FLAT_ZERO_NO_DEM`

The raw byte hashes differ, but the semantic hashes match. The header-pinned candidate preserves the raw run-1 semantic hash and changes only CRS metadata.
