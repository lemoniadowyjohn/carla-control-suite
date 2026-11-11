# O07 Runtime Strategy Selection

## Decision: DUAL_PATH_REQUIRED

### Rationale

1. **Road-network validation** requires the full OpenDRIVE (32,710 roads, 3,646 junctions) to be loaded dynamically via generate_opendrive_world().
2. **Visual/collision validation** requires the packaged visual map (GLB/FBX/OBJ) to be loaded via load_world() with the registered Ingolstadt map name.
3. **Runtime identity verification** requires both paths to produce consistent map identity (same road count, junction count, lane count, signal count).
4. **Phase L rerun** must use the dynamic OpenDRIVE path (not the built-in Town10HD_Opt).
5. **Phase N rerun** must verify the packaged visual map matches the dynamic OpenDRIVE map.

### Strategy Details

| Path | Method | Purpose | Verification |
|------|--------|---------|--------------|
| Dynamic XODR | client.generate_opendrive_world(xodr_text) | Road-network validation | Source hash vs runtime hash, road count, junction count, lane count, signal count |
| Packaged Visual | client.load_world(map_name) | Visual/collision validation | Map name check, visual smoke test, structural comparison with dynamic path |

### Enforcement Rules

1. **No fallback to Town10HD_Opt**: If generate_opendrive_world() fails or produces a map with < 1000 roads, hard-stop with error.
2. **Source hash verification**: SHA-256 of the XODR text passed to generate_opendrive_world() must match the source hash.
3. **Runtime hash verification**: SHA-256 of world.get_map().to_opendrive() must match the source hash.
4. **Structural inventory comparison**: Road count, junction count, lane count, signal count from runtime must match the source candidate.
5. **Map name verification**: world.get_map().name must contain 'Ingolstadt' (not 'Town10HD_Opt').
6. **UP_THESIS_STRICT=1**: The map_identity_guard.py alidate_world_map() must enforce hard stop on Town fallback.

### Phase L Rerun Strategy

- Use generate_opendrive_world() with the authoritative XODR text
- Verify runtime identity at each gate
- Use the same gate structure as original Phase L but with correct map

### Phase N Rerun Strategy

- Start from N1 (runtime map identity)
- Use the correctly loaded map from Phase L rerun
- Verify all 23 gates against the correct map
