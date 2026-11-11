# P13 - Runtime Inventory Methods

The earlier reports compared counts from DIFFERENT counting methods:

| Method | Source count | Runtime count |
|--------|-------------|---------------|
| XML road elements (source artifact) | 32,710 | 32,710 |
| waypoint-derived unique road IDs | (not used) | 32,654 |
| topology-derived unique road IDs | (not used) | 32,654 |
| **runtime `world.get_map().to_opendrive()` XML roads (authoritative)** | **32,710** | **32,710** |
| XML junction elements (source artifact) | 3,646 | 3,646 |
| runtime `to_opendrive()` XML junctions | 3,646 | 3,646 |

## Conclusion

The 32,654 / 32,654 road figure was a waypoint- or topology-derived count, not an
OpenDRIVE XML count. `world.get_map().to_opendrive()` is the authoritative runtime
OpenDRIVE representation. Using it, the source and runtime inventories are identical:

- source XML roads: 32,710 == runtime XML roads: 32,710
- source unique road IDs: 32,710 == runtime unique road IDs: 32,710
- source XML junctions: 3,646 == runtime XML junctions: 3,646
- source unique junction IDs: 3,646 == runtime unique junction IDs: 3,646
- lane sections: 32,710 == 32,710
- driving lanes: 34,674 == 34,674

Missing road IDs: 0
Unexpected road IDs: 0
Missing junction IDs: 0
Unexpected junction IDs: 0

## Verdict: P4_RUNTIME_EQUIVALENCE_PASS
