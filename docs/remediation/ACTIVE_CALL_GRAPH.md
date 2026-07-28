# ACTIVE CALL GRAPH

Generated from repository analysis on `deepseek-observability-integration-verification` (SHA: db0d983a)

## Entry Points
- **run_pipeline.py**: Main CLI entry point
- **ultimate_pipeline/main_pipeline.py**: Monolithic pipeline orchestrator
- **ultimate_pipeline/entrypoints.py**: Alternative entry points
- **ultimate_pipeline/cli.py**: CLI interface

## Pipeline Stages (in execution order)

- **stage_00_preflight_carla.py**: Preflight CARLA checks, determinism, paths
- **stage_01_sanitize.py**: XODR sanitization, SUMO optional
- **stage_02_topology_semantics.py**: Topology lint, structure scan, semantic risk
- **stage_03_topology_repair.py**: Topology repair
- **stage_04_enrichment.py**: Enrichment: roundabouts, traffic lights, buildings, realism
- **stage_05_geometry.py**: DEM elevation + smoothing + geometry validator
- **stage_06_links.py**: PlanView smoothing + mesh continuity + micro-prune
- **stage_07_lanes.py**: Lane generation + lane/cross-section/offset repair + sidewalks
- **stage_08_integrity.py**: LaneLinks + markings + final integrity checks
- **stage_08_final_integrity.py**: Final integrity checks (duplicate?)
- **stage_09_tiling.py**: Tiling + adjacency + auto-scenarios
- **stage_10_tile_qa.py**: Tile QA (seams + CarlaFinalTest + spawn QA + stress tester)
- **stage_11_12_sim_domain.py**: Road defect scan, local perception, screenshots
- **stage_11_simulation.py**: Interactive simulator (optional)
- **stage_12_domain_gap.py**: Domain-gap analysis (classical; GNN/latent separate)
- **stage_14_finalization.py**: Quality gates wrapper + LLM QA

## Key Supporting Modules

- **ultimate_pipeline/config/settings.py**: Global settings with environment overrides
- **ultimate_pipeline/contracts/gate_runner.py**: CumulativeGateRunner for gate management
- **ultimate_pipeline/quality/quality_gates.py**: Quality gate definitions
- **ultimate_pipeline/quality/quality_gate_manager.py**: Gate state management
- **ultimate_pipeline/contracts/stage_contracts.py**: Stage input/output contracts
- **ultimate_pipeline/osm/osm_to_xodr.py**: OSM to XODR conversion
- **ultimate_pipeline/geometry/planview_smoother.py**: Geometry smoothing (has issues)
- **ultimate_pipeline/geometry/mesh_continuity_repairer.py**: Mesh continuity repair (has issues)
- **ultimate_pipeline/enrichment/lane_generator.py**: Lane generation (has issues)
- **ultimate_pipeline/topology/topology_repair.py**: Topology repair (has issues)
- **ultimate_pipeline/topology/roundabout_reconstructor.py**: Roundabout reconstruction (has issues)
- **ultimate_pipeline/elevation/elevation_importer.py**: Elevation import (has issues)
- **ultimate_pipeline/elevation/elevation_smoother.py**: Elevation smoothing (has issues)
- **ultimate_pipeline/roadrunner/**: RoadRunner optional backend (recovery branch)

## Data Flow

- OSM input -> osm_to_xodr.py -> raw XODR
- raw XODR -> stage_01_sanitize.py -> sanitized XODR
- sanitized XODR -> stage_02_topology_semantics.py -> topology report
- -> stage_03_topology_repair.py -> repaired XODR
- -> stage_04_enrichment.py -> enriched XODR
- -> stage_05_geometry.py -> elevation + geometry validation
- -> stage_06_links.py -> planview smoothing
- -> stage_07_lanes.py -> lane generation
- -> stage_08_integrity.py -> lane links + markings
- -> stage_09_tiling.py -> tiles
- -> stage_10_tile_qa.py -> tile QA
- -> stage_11_12_sim_domain.py -> simulation/domain gap
- -> stage_14_finalization.py -> final quality gates

## Identified Architectural Issues (from problems.md)

- PROB-001: Multiple entry points (run_pipeline.py, main_pipeline.py, entrypoints.py, cli.py)
- PROB-002: Stage modules depend on runtime global injection (SETTINGS proxy)
- PROB-003: Duplicate package roots (submission/infrastructure/ultimate_pipeline)
- PROB-004: 55 modules only as .pyc bytecode
- PROB-005: Test collection errors (eager CARLA import, missing RigVerification)
- PROB-006: 1458 broad Exception handlers, 25 bare excepts
- PROB-007: Pass-only/placeholder functions in active paths
- PROB-008: Fragmented configuration
- PROB-009: Strict behavior opt-in not release-default
- PROB-010: Run manifest/hash best-effort
- PROB-011: Old runs archived before new run proven
- PROB-012: Database schema mandatory for offline generation
- PROB-013: Python assert for release invariants
- PROB-014: No enforced stage mutation contract
- PROB-015: No monotonic validity enforcement
- PROB-016: Validators and repairers not separated
- PROB-017: Class-global quality state leaks between runs
- PROB-018: No authoritative artifact promotion transaction
