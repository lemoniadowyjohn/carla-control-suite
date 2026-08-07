# Stage P-Q - Final release closure

## Overall verdict: `Q_RELEASE_HOLD_LIVE_RUNTIME_REQUIRED`

## Gate summary

| Stage | Verdict | Evidence |
|---|---|---|
| A-F | commit-ready / pushed | GitHub-verified remote state |
| G | `SEMANTIC_CONTENT_PARTIAL` | `G_SEMANTIC_COMPLETENESS.json` (signals restored 0→3467; crosswalks & pedestrian lanes missing) |
| H | `H_GOVERNED_PAYLOAD_EXACT` | `Q03`/`Q04` manifest + `governed_payload.xodr` (coordinate contract PASS, release verifier OK) |
| I | packaged-map evidence produced | `I_PACKAGED_MAP_EVIDENCE.json` (packaged vs governed payload: SEMANTIC_EQUIVALENCE_PASS) |
| J | `BLOCKED_SERVER_UNAVAILABLE` | `J_BUILTIN_SMOKE.json` |
| K | `BLOCKED_SERVER_UNAVAILABLE` | `K_TRAFFIC_BUILTIN.json` |
| L | `BLOCKED_SERVER_UNAVAILABLE` | `L_GOVERNED_PAYLOAD_LOAD.json` |
| M | `BLOCKED_SERVER_UNAVAILABLE` | `M_RUNTIME_EQUIVALENCE.json` |
| N | `BLOCKED_SERVER_UNAVAILABLE` | `N_PERCEPTION_FPS.json` |

## Offline gates — complete
- Repaired candidate `ingolstadt_fixed_final.xodr`: raw bytes `80ebb005…` (signed, matches P04/O06).
- Phase H signal enrichment replayed idempotently onto repaired parent → `candidate_g_semantic_enriched.xodr`, 3467 signals, integrity clean, structural identity preserved (32710/3646 roads/junctions, 84781 lanes, elevation hash identical).
- Governed load payload generated from the enriched candidate using the loader's exact `<geoReference>` normalization. Manifest records input `d604ac39…` / payload `3f7370ef…`; release-mode verifier enforces byte-exactness; coordinate contract PASS.
- Hash chain reconciled: `80ebb005` (raw) → `516e329c` (LF text, == P04 payload) → `d604ac39` (enriched) → `3f7370ef` (governed payload) → `9630d9f6` (runtime to_opendrive).

## Live gates — BLOCKED (unavailable tool)
No `CarlaUE4` server executable exists on this host:
- Not found on PATH (`where CarlaUE4` → none).
- Not found on disk under `C:\CARLA`, `C:\Program Files\CARLA`, `...\Downloads`, or any depth-≤6 traversal of `C:\`.
- `CARLA_ROOT` environment variable unset; only the Python client API module is importable (no server).

The shared campaign contract requires unavailable tools to remain `BLOCKED` (never coerced into a `PASS`). Therefore:
- J built-in map smoke + K traffic cannot confirm the perception pipeline end-to-end.
- L governed-payload load (the auto-generated custom XODR) cannot confirm CARLA accepts the 80 MB payload or that signals render.
- M runtime identity cannot confirm the loaded map regenerates to_opendrive() matching expectation.
- N perception FPS cannot be measured.
- The residual `SEMANTIC_CONTENT_MISSING` categories (`crosswalk_objects`: 174 OSM vs 0; `pedestrian_lanes`: 78 OSM vs 0) are packaged-map/actor bindings that can only be validated against a live loaded map.

## Release decision
The map-side and payload-governance work is complete and committed (Stages A–I, H governed payload). The release is held pending availability of a CARLA server for the live verification gates (J–N). The governed payload artifact (`governed_payload.xodr`, `3f7370ef…`) is release-mode ready: once a server is available, `load_opendrive_world(..., governed_payload_sha256="3f7370ef…")` will load it byte-exactly.

## Files committed this run (run id 20260807T000000Z)
- `reconcile_semantic_completeness.py` + `G_SEMANTIC_COMPLETENESS.{json,md}`
- `replay_phase_h_on_repaired.py` + `G_REPLAY_PHASE_H.json`
- `candidate_g_semantic_enriched.xodr` (LFS)
- `govern_load_payload.py`; `Q03` / `Q04` / `governed_payload.xodr` (LFS) + `H_LOAD_PAYLOAD_GOVERNANCE.{json,md}`
- `stage_i_packaged_map.py` + `I_PACKAGED_MAP_EVIDENCE.{json,md}`
- `run_stage_jq_live.py` + `J_`…`N_` / `Q_FINAL` / `JQ_LIVE_RUNTIME_EVIDENCE.{json,md}` (BLOCKED)
- `phase_q/governed_payload.py` bug fixes (coordinate-contract field, set-slice)
- `.gitattributes` LFS rule for `governed_payload.xodr`

## Next action required from operator
Provide a launchable CARLA server (executable matching the client Python API version, or `CARLA_ROOT` set so `CarlaUE4` can start), then re-run `run_stage_jq_live.py`. All four live gates will then execute: built-in Town03 smoke → governed-payload custom-map load (byte-exact) → traffic spawns → perception capture + FPS, after which P-Q can close as a full release.
