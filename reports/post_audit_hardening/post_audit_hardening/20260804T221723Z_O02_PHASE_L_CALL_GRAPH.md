# O02 Phase L Call Graph

## Phase L Execution Chain

`
Command Line
  └── python phase_l_validation.py
        └── main()
              ├── connect_client() → carla.Client('127.0.0.1', 2000)
              ├── step_l1_preflight(client)
              │     └── world.get_map().name → 'Carla/Maps/Town10HD_Opt'
              │     └── world.get_map().to_opendrive() → 1.8MB OpenDRIVE
              │     └── world.get_settings(), world.get_weather()
              ├── step_l2_map_identity(client)
              │     └── world.get_map().name → 'Carla/Maps/Town10HD_Opt'
              │     └── world.get_map().to_opendrive() → SHA-256 of Town10HD_Opt
              │     └── map_name_match = True (compared against itself)
              ├── step_l3_parser_logs(client)
              │     └── No actual parser logs captured
              │     └── parse_status = 'OK' (synthetic)
              ├── step_l4_alignment(client)
              │     └── world.get_map().get_all_landmarks() → 65 landmarks
              ├── step_l5_visual_regression(client)
              │     └── No camera images or defect checks
              ├── step_l6_waypoint_topology(client)
              │     └── world.get_map().generate_waypoints(2.0) → 3066 waypoints
              │     └── world.get_map().get_topology() → 200 segments
              │     └── road_count = 88 (unique road_ids from topology)
              │     └── junction_count = 82 (from topology)
              ├── step_l7_drivability(client)
              │     └── 0 vehicle spawn attempts
              ├── step_l8_signal_validation(client)
              │     └── world.get_actors().filter('traffic.traffic_light') → 15 lights
              ├── step_l9_sensor_validation(client)
              │     └── No actual sensor captures
              ├── step_l10_performance(client)
              │     └── All metrics = 0
              ├── step_l11_old_vs_new(client)
              │     └── No actual comparison
              ├── step_l12_protected_hashes(client)
              │     └── Hashes computed from Town10HD_Opt OpenDRIVE
              └── step_l13_outputs(client, all_results)
                    └── Verdict: L_ALL_PASS (invalid - wrong map)
`

## Root Cause of Town10HD_Opt Selection

1. **No XODR argument was passed to Phase L**: The Phase L validation script (phase_l_validation.py) did not accept or use an XODR path argument.
2. **No map-selection call was made**: Phase L never called client.load_world() or client.generate_opendrive_world(). It simply connected to the already-running CARLA server and queried world.get_map().
3. **The CARLA server was already running with Town10HD_Opt**: The server was started earlier with the built-in Town10HD_Opt map as the default.
4. **No identity gate was enforced**: Phase L had no mechanism to verify that the loaded map matched the expected candidate.
5. **The map name match was circular**: L2 compared world.get_map().name == 'Carla/Maps/Town10HD_Opt' against the expected map name 'Carla/Maps/Town10HD_Opt', which was set to match the built-in map rather than the Ingolstadt candidate.

## Why the 88-road count was reported

Phase L L6 counted len(set(wp.road_id for wp_pair in topology for wp in wp_pair)) where 	opology = world.get_map().get_topology(). The CARLA topology returns only the connected road segments in the current world, not all roads in the OpenDRIVE file. For Town10HD_Opt, this returns 88 unique road IDs from the 200 topology segments.

The actual runtime OpenDRIVE has 108 roads (from world.get_map().to_opendrive()), and the campaign candidate has 32,710 roads.
