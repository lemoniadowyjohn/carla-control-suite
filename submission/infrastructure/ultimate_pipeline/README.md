# Ultimate OSM → CARLA Pipeline

## Overview

This repository implements a research pipeline for generating large-scale
CARLA-compatible OpenDRIVE maps from OpenStreetMap (OSM) data and analyzing
the *domain gap* between automatically generated maps and a manually modeled
reference map of Ingolstadt.

The pipeline supports:
- deterministic map generation
- large-area OSM ingestion
- geometric and semantic repair
- domain gap analysis
- perception dataset generation
- optional CARLA-based validation
- scalable experimentation on HPC systems

The primary research goal is to evaluate how well perception models trained
on synthetic, automatically generated maps generalize to:
1) a manually authored CARLA map of the same city
2) unlabeled real-world data

---

## High-Level Pipeline Stages

1. **OSM → OpenDRIVE conversion**
2. **Topology & geometry sanitization**
3. **Lane, junction, and semantic enrichment**
4. **Optional CARLA validation (spawn & QA)**
5. **Tile extraction & large-area streaming**
6. **Domain gap analysis (geometry, semantics, perception)**
7. **Perception dataset generation**
8. **Training & evaluation (local or HPC)**

---

## Key Entry Points

### Map Generation
- `run_pipeline.py`  
  End-to-end OSM → CARLA OpenDRIVE generation pipeline.

### Domain Gap Analysis
- `run_full_domain_gap.py`  
  Computes geometric, semantic, perception, and learned (GNN) domain gaps.

### Perception
- `perception/run_training.py`  
  Canonical entry point for perception training and evaluation.

### Experiments
- `experiments/runner.py`  
- `experiments/trainer.py`  
- `experiments/evaluator.py`  

### Quality Gates
- `quality/*`  
  Automated checks for physical, semantic, and statistical validity.

---

## CARLA Dependency Policy

CARLA **is NOT required** for:
- map generation
- domain gap computation
- dataset preparation
- offline analysis

CARLA **is required only** for:
- spawn validation
- sensor simulation
- visual inspection

All CARLA usage can be disabled via:
`ultimate_pipeline/config/runtime.py`

## CARLA Visual Failures (Seams/Walls)

If CARLA shows vertical walls, trenches, torn seams, or flat voids, the root
cause is usually elevation discontinuities in the final OpenDRIVE file. These
issues often appear after pruning/tiling/repair steps. The pipeline includes a
post-final elevation seam gate to catch large Z jumps and stop before CARLA load.
If a DEM is available, an optional post-prune elevation autofix can re-project
elevation profiles once and re-check the seam gate.

Note: buildings are not visible in CARLA by default. OpenDRIVE object entries
are not rendered as meshes in stock CARLA; this is a simulator limitation.

## Map Validity and Perception Gating

Map validity is defined by post-final safety checks that are independent of CARLA:
the elevation seam gate (detects large Z jumps that create walls) and the origin
sanity check (rejects maps absurdly far from origin). These results are written
to `map_acceptance.json` with a compact `{valid, failed_gates, summary}` schema.
By default, perception capture is unchanged; if you set
`UP_REQUIRE_MAP_ACCEPTANCE_FOR_PERCEPTION=1`, perception steps will be skipped
unless the map is marked valid. The seam gate exists to prevent visual artifacts
and physics instability in CARLA, while the origin sanity check catches
coordinate system mistakes before they reach simulation.

---

## OSM2World Integration (Optional)

The pipeline includes optional support for **OSM2World**, a tool that generates 3D
scene geometry (buildings, vegetation) from OpenStreetMap data. This is used purely
for **perceptual clutter and thesis figures** - it does NOT affect OpenDRIVE generation
or CARLA loadability.

**Important**: OSM2World is for buildings/vegetation only. Roads are excluded because
CARLA/OpenDRIVE owns road geometry.

### Enabling OSM2World

Set the environment variable before running the pipeline:

```bash
# Windows
set ENABLE_OSM2WORLD=1
python -m ultimate_pipeline.main_pipeline

# Linux/macOS
ENABLE_OSM2WORLD=1 python -m ultimate_pipeline.main_pipeline
```

### Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `ENABLE_OSM2WORLD` | `0` | Set to `1` to enable the stage |
| `OSM2WORLD_HOME` | (built-in) | Path to OSM2World binary folder |
| `OSM2WORLD_JAR` | (auto-detect) | Explicit path to OSM2World JAR |
| `OSM2WORLD_CONFIG` | (built-in) | Path to external properties file |
| `OSM2WORLD_OUTPUTS` | `obj,png` | Comma-separated outputs: `obj`, `png`, `glb` |
| `OSM2WORLD_TIMEOUT_SEC` | `1800` | Timeout in seconds |

### Expected Artifacts

When enabled, the stage produces artifacts in `<output_dir>/osm2world/`:

| File | Description |
|------|-------------|
| `scene.obj` | 3D scene in OBJ format (primary, most reliable) |
| `preview.png` | Preview image |
| `scene.glb` | 3D scene in glTF binary (optional, validated) |
| `osm2world.properties` | Configuration file used |
| `osm2world_status.json` | Status with hashes, timing, cache key, and paths |
| `osm2world_*_stdout.log` | OSM2World stdout per output type |
| `osm2world_*_stderr.log` | OSM2World stderr per output type |

### Caching

The stage is **deterministic and cacheable**. If the input OSM file and config file
have not changed (verified by SHA-256 hash), cached outputs are reused automatically.
The cache key is stored in `osm2world_status.json`.

### Config Validation

If OSM2World prints "could not read config" in stderr, the stage is marked as **FAILED**
even if output files exist. This ensures the config is always applied correctly.

---

## Blender FBX Conversion (Optional)

The pipeline optionally converts OSM2World OBJ output to FBX format for import into
Unreal Engine / CARLA.

### Enabling Blender FBX

```bash
# Windows - enable both OSM2World and Blender
set ENABLE_OSM2WORLD=1
set ENABLE_BLENDER_FBX=1
python -m ultimate_pipeline.main_pipeline
```

### Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `ENABLE_BLENDER_FBX` | `0` | Set to `1` to enable FBX conversion |
| `BLENDER_EXE` | (built-in) | Path to Blender executable |
| `BLENDER_TIMEOUT_SEC` | `600` | Timeout in seconds |

### Expected Artifacts

When enabled, the stage produces additional artifacts in `<output_dir>/osm2world/`:

| File | Description |
|------|-------------|
| `scene.fbx` | 3D scene in FBX format for Unreal/CARLA |
| `blender_convert.py` | Auto-generated conversion script |
| `blender_stdout.log` | Blender stdout |
| `blender_stderr.log` | Blender stderr |
| `blender_status.json` | Status with hashes and timing |

---

## Standalone Stack Check

Test the full OSM2World + Blender stack without running the main pipeline:

```bash
# Basic check (OSM2World only)
python -m ultimate_pipeline.tools.check_osm2world_stack --osm path/to/file.osm --out ./test_out

# With Blender FBX conversion
python -m ultimate_pipeline.tools.check_osm2world_stack --osm path/to/file.osm --out ./test_out --blender

# Strict mode (fail on any warning)
python -m ultimate_pipeline.tools.check_osm2world_stack --osm path/to/file.osm --out ./test_out --strict
```

### Troubleshooting

**Java not found**: OSM2World requires Java. Install a JRE/JDK and ensure `java` is in PATH.

**"could not read config"**: The config file encoding may be wrong. The pipeline writes
configs as ASCII without BOM to avoid Java properties loader issues.

**GLB invalid for Blender**: GLB files are validated by checking the `glTF` header magic
bytes. If Blender cannot import the GLB, prefer using OBJ instead.

**Timeout**: Large OSM files may exceed the default timeout. Increase via
`OSM2WORLD_TIMEOUT_SEC` or `BLENDER_TIMEOUT_SEC`.

**Memory issues**: Very large areas may cause Java heap errors. Consider using a smaller
OSM extract or increasing Java heap size.

---

## Determinism

The pipeline supports deterministic execution via:
- fixed random seeds
- controlled map perturbations
- reproducible experiment manifests

---

## Research Context

This codebase accompanies a master’s thesis on:
**Domain gaps in synthetic environments for autonomous driving perception**

Focus:
- structural variability
- perceptual generalization
- natural vs. induced domain randomization

---

## Contact

This repository is designed for:
- autonomous driving research
- reproducible experimentation
- close collaboration with simulation & perception teams
