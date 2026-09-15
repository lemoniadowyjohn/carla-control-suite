# Structure Elevation Plausibility Gate

`GAP-009` and `GAP-010` are addressed by a read-only Stage 5 quality gate.
It samples final OpenDRIVE plan-view geometry with the canonical geometry
kernel, evaluates the active cubic elevation polynomial at interior points,
and compares those heights to the existing DEM sampler.

Bridge and elevated roads are checked for remaining above terrain; tunnels are
checked for remaining below terrain. `underpass` and `covered` remain
explicitly terrain-ambiguous because their OSM tags do not establish a valid
above/below-ground expectation. Missing structure, geometry, elevation, or
terrain evidence is `INCOMPLETE`, not a pass. The gate never fabricates deck
height, overburden, or a replacement elevation profile.

The pinned Ingolstadt measurement is currently `INCOMPLETE`: the F1 CRS
contract fails closed with `no_frame_matches_osm_source` before OSM structure
classification or DEM sampling can begin. Therefore this branch makes no
claim about the number of implausible current-map bridges or tunnels. The
machine-readable record is
[CODEX_STRUCTURE_ELEVATION_PLAUSIBILITY_EVIDENCE.json](CODEX_STRUCTURE_ELEVATION_PLAUSIBILITY_EVIDENCE.json).

Focused verification passed: `37 passed`, including the new positive,
negative, tunnel, missing-terrain, active-polynomial, gate-manager, and
kernel-delegation tests. No CARLA process, map-of-record mutation, or frozen
evidence mutation occurred.
