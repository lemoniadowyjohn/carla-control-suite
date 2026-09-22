# Claim Boundary: Semantic Organizer

This document defines the reliability claims for the CARLA Semantic Organizer.

## Evidence Levels

1. **OFFLINE_CLASSIFICATION_VERIFIED**
   - Pure tag resolution, folder path computation, and plan generation are verified mathematically/offline.
   - Classification logic is pure, deterministic, and free of side effects.

2. **FILESYSTEM_PLACEMENT_VERIFIED**
   - Filesystem copy/move of non-UAsset containers (e.g. .fbx) is verified safe at the OS layer.
   - Ensures containers are placed according to the deterministic semantic classification.

3. **UE_ASSET_ORGANIZATION_UNVERIFIED**
   - Unreal Engine asset reference validation and live tag assignment require the Unreal Editor Asset API / live environment.
   - Raw filesystem moves of .uasset files are BLOCKED in production to prevent breaking UE4 internal references.
