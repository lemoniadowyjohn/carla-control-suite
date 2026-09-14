# Runtime Tile Subset Contract

The analytical `TileExtractor` remains a domain-gap observation-window tool.
It is not a runtime artifact and this implementation does not alter it.

`up tile build-runtime` creates a separate artifact type. It selects roads in a
core plus buffer, closes only junctions touched by that spatial selection,
keeps the connecting roads and immediate exits needed by those junctions, and
removes road and lane links at the resulting outer boundary. The output keeps
stable source road IDs but rebases its geometry into a local coordinate frame.
Its global CRS and geometry-freeze attestation are removed because they no
longer describe the translated coordinates.

Each output has a sidecar `.runtime_tile.json` manifest containing source and
output SHA-256 values, structural counts, closure changes, a candidate spawn
road, and an offline validation result. `TileWorldRunner.load_runtime_tile()`
requires that manifest, verifies the hash, and re-runs static validation before
it can call CARLA. The backwards-compatible generic tile loader is unchanged.

The CLI probe documented in `RUNTIME_TILE_SUBSET_EVIDENCE.json` produced a
locally rebased, 1,280-road subset from the pinned Ingolstadt map. It passed
the standalone structural contract and was deterministic across two rebuilds.
The generated XODR is a local, untracked candidate and is not a new
map-of-record.

No CARLA server was started for this work. `READY_FOR_LIVE_CARLA_VALIDATION`
means only that the offline structural prerequisite passed. A controlled CARLA
load, waypoint/spawn check, drive route, and VRAM measurement remain required
before claiming runtime or rendering benefits.
