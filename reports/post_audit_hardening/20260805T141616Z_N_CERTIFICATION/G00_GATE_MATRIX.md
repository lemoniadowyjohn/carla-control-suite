# Phase N Gate Matrix (G0-G28)

| Gate | Description | Status | Evidence |
|------|-------------|--------|----------|
| G0 | Repository identity | PASS | branch=fix/post-audit-phase-e-junctions-roundabouts-20260803 commit=f5aabc0a4f170e564aa03efcb906966880859a9f |
| G1 | Phase L evidence credibility | PASS | verdict=L_ALL_PASS evidence_dir=reports/post_audit_hardening\20260805T122525Z |
| G2 | Runtime map identity | PASS | map=Carla/Maps/OpenDriveMap (not a built-in Town) |
| G3 | Source/runtime equivalence | PASS | P4_RUNTIME_EQUIVALENCE_PASS; missing/unexpected roads=0/0, junctions=0/0 |
| G4 | Clean-server validation | PASS | server 0.9.16, GPU Quadro P3200, rpc 127.0.0.1:2000 |
| G5 | Parser/map-load health | PASS | parse_status=OK fatal=0 |
| G6 | Waypoint/topology generation | PASS | waypoints=878138 topology_segments=47486 |
| G7 | Vehicle drivability evidence | BLOCKED | no live vehicle spawns in Phase L re-run (vehicle_successful_spawns=0) |
| G8 | Signal validation | PASS | traffic_light_count=0 (OpenDRIVE map exposes no signals); status PASS |
| G9 | Sensor validation evidence | BLOCKED | sensor status flags present but no captured frames recorded |
| G10 | Performance measurement | BLOCKED | map_load_time_ms=539.97 but fps=0, ram/vram=0 |
| G11 | Old-vs-new comparison evidence | BLOCKED | no captured old-vs-new comparison data |
| G12 | Protected hashes | PASS | all_hashes_verified=True planView=9630d9f673fdea87 |
| G13 | Repair mutation audit | PASS | changed_road_count=12 classes={'SOLE_ZERO_LENGTH_CONNECTOR_GEOMETRY': 12} |
| G14 | Repair acceptance gate | PASS | strict_gate_errors=0 warnings=1 |
| G15 | Non-positive geometry lengths | PASS | count=0 |
| G16 | Non-finite geometry fields | PASS | count=0 |
| G17 | Duplicate/unordered geometry s | PASS | duplicate=0 unordered=0 |
| G18 | Roads without planView/geometry | PASS | without_planview=0 without_geometry=0 |
| G19 | Idempotency | PASS | idempotent=True |
| G20 | Packaged visual map identity | BLOCKED | packaged visual map (cooked) not loaded in this environment |
| G21 | Full route/traffic/pedestrian stress | BLOCKED | requires packaged visual map + scenario tools (not available) |
| G22 | Elevation/physics validation | BLOCKED | requires packaged visual map collision/elevation artifacts |
| G23 | Endurance | BLOCKED | long-duration run not executed |
| G24 | Old-vs-new map comparison | BLOCKED | requires packaged old candidate for direct comparison |
| G25 | Runtime to_opendrive SHA consistency | PASS | L2==P4 runtime: 9630d9f673fdea87058139d9e2241c7084dc2e2550674bba4bfffc78c6d0ae80 |
| G26 | Runtime load time | PASS | load_time_s=333.9 |
| G27 | Server stability | PASS | server_crashes=0, rpc_timeouts=0 |
| G28 | Final evidence manifest validity | PASS | N00/N18 + EVIDENCE_MANIFEST generated in this run |