# 6.5 Negative controls

- Verdict: `ALL_PASS`
- J6 round-trip verdict: `ROUNDTRIP_PASS`

### fbx_no_axis_reflection
- mechanism: J6 round-trip re-import inventory comparison (bounds within 0.01 m, same vertex/face/UV/material counts)
- verdict: `PASS`
- detected: False

### fbx_no_100x_scale
- mechanism: manifest export global_scale + round-trip bounds match
- verdict: `PASS`
- detected: False
  - global_scale: 1.0

### stale_fbx
- mechanism: 
- verdict: `PASS`
- detected: False
  - results: [{'file': 'ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx', 'sidecar_match': True, 'recorded': 'dae9c8d457fd', 'actual': 'dae9c8d457fd'}]

### manifest_hash_mismatch
- mechanism: J1 input_hash_linkage + artifact_hash_match provenance sidecars
- verdict: `PASS`
- detected: False
  - obj_input_hash_linkage: True
  - obj_artifact_hash_match: True

### stale_artifact_substitution
- mechanism: J1_glb json_utf8 + json_valid (reject corrupt GLB as in prior full-map run)
- verdict: `PASS`
- detected: False
  - glb_json_utf8: True
  - glb_json_valid: True

