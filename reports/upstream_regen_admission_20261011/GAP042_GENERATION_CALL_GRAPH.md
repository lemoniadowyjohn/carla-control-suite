# GAP042 generation call graph (source-read, no inference from naming)

## 1. CityMapGenerator (procedural RANDOM city — NOT XODR-driven)

- `ACityMapGenerator::PreSave` — `Plugins/Carla/Source/Carla/CityMapGenerator.cpp:63`.
  Guard: `#if WITH_EDITOR` (editor-only). Body: if `bGenerateRoadMapOnSave`,
  broadcast save, and if NOT cooking (`!GIsCookerLoadingPackage`) call
  `GenerateRoadMap()`. NOTE: PreSave does NOT call GenerateRoads; road meshes
  come only from `UpdateMap()`.
- `ACityMapGenerator::UpdateMap` (`:83`) — calls `UpdateSeeds()`,
  `GenerateGraph()`, then `GenerateRoads()` iff `bGenerateRoads` (default true,
  `:109` header), then `GenerateRoadMap()` iff triggered.
- `GenerateGraph` (`:109`) — builds a RANDOM DCEL city graph
  (`MapGen::GraphGenerator::Generate(MapSizeX, MapSizeY, Seed)`). No XODR input.
- `GenerateRoads` (`:153`) — stamps instanced meshes (`RoadTwoLanes_*`,
  intersections) along the RANDOM graph edges. Ignores diagonal edges.
- `GenerateRoadMap` (`:262`) — routing graph data (waypoints), not render meshes.
- Callers of `GenerateRoads` anywhere in source: ONLY `UpdateMap` (`:88`).
  `UpdateMap` callers: editor UI flows (not traced further — irrelevant: the
  output would be a random grid, not Ingolstadt roads).
- FALSIFICATION: invoking CityMapGenerator on Ingolstadt tiles would overlay a
  random-grid city, not generate XODR roads. It is the WRONG generator for this gap.

## 2. OpenDRIVE actor (traffic, not meshes)

- `AOpenDriveActor::BuildRoutes` (`OpenDrive/OpenDriveActor.cpp:136`) spawns
  `ARoutePlanner` + `AVehicleSpawnPoint`s. No mesh generation.
- `PrepareAssetsForCookingCommandlet::SaveWorld` (`:423`) spawns the actor when
  `<Package>/Maps/<World>/OpenDrive/<World>.xodr` exists, saves, then DESTROYS
  actor/routes/spawners. Transient traffic setup only.

## 3. Runtime procedural roads (transient, unpackaged)

- `UCarlaEpisode::LoadNewOpendriveEpisode` (`Game/CarlaEpisode.cpp:146`):
  parses XODR string → `GenerateMesh()` (in-memory road + crosswalk meshes) →
  writes `Carla/Maps/Nav/OpenDriveMap.obj` (Recast navmesh input) + server-side
  `Carla/Maps/OpenDrive/OpenDriveMap.xodr`. Invoked via the
  generate_opendrive_world RPC path. Nothing is package-backed.

## 4. Pre-placed Static meshes (the only packaged road mechanism)

- `PrepareMapsForCooking` (`PrepareAssetsForCookingCommandlet.cpp:639`) builds
  `/Game/<Pkg>/Static/{Road,RoadLine,Terrain,SideWalk}/<Map>` paths and
  `SpawnMeshesToWorld` (`:174`) loads + spawns whatever meshes exist there
  (tile-name filtered). `LoadAssetDataFromPaths` on absent paths yields zero
  assets (no error). No generator feeds these paths for Ingolstadt.

## 5. Terrain

- No terrain/landscape generator exists in the searched source. Terrain reaches
  packages ONLY as pre-placed/imported meshes via mechanism 4. The
  `Static/Terrain/Ingolstadt/` dir currently holds 5711 BUILDING uassets
  (misplaced import output), zero terrain meshes.

## 6. Editor/commandlet hooks for baking XODR roads into tiles

- NONE FOUND: no OpenDRIVE-to-actor importer, no road-bake commandlet, no
  cook-time road generation trigger. `git grep` for ImportOpenDrive,
  OpenDriveImporter, GenerateRoadGeometry, RoadMapGenerator, RoadGenerator:
  all empty (except unrelated RoadMap routing hits).
