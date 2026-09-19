# Production Closure Baseline - 20260919T000000Z

Coordination worktree: `.codex/worktrees/prod-closure-20260919`

Production branch: `integration/production-large-map-20260918`

Local production HEAD is `f5333f3ae623194809350afa3bc212f53c3577d6`, two commits ahead of `origin/integration/production-large-map-20260918` (`398193d4fc3cfb4164daf805438168813ae36aec`). The static prompt baseline `integration/session-batch1-20260912` remains the lineage root at `1a42cd89bbaaeca95e6f326225afa5a4c23e707d`; `main` is not used.

## Integrated Work

- P0-A staging integrity: `c75fd8c9`, merged at `42d6865b`.
- P0-A stage capability contract: `e99ec35b`, merged at `234e1ef1`.
- P0-B final artifact authority/order: `22e3811c`, merged at `398193d4`.
- P1-F canonical geometry authority: `fab0f8c7`, merged at `9ccb5d98`.
- P1-G lane-count classification: `e2befc36`, merged locally at `f5333f3a`; not yet pushed to origin production.

## Map Provenance

- Automatic map of record: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr`
- SHA-256: `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`
- Size: `149799632` bytes
- Manual reference: `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr`
- Manual SHA-256: `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`
- Pinned road OSM: `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm`
- OSM SHA-256: `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`

The map, manual reference, and OSM hashes were verified against files in the clean coordinator worktree.

## Tool Availability

- Python: `3.12.2`
- Git: `2.46.2.windows.1`
- Git LFS: `3.5.1`
- Blender: available, `E:\Program Files\Blender Foundation\Blender 4.3\blender.exe`, version `4.3.0`
- SUMO netconvert: available at `C:\Sumo\sumo-win64extra-1.24.0\sumo-1.24.0\bin\netconvert.exe`, version `1.24.0`
- OSM2World: unavailable/unverified in the clean worktree; configured repo-relative JAR was not found.
- CARLA packaged runtime: installed at `E:\CARLA\CARLA_0.9.16`, but prior evidence shows RPC startup remains blocked.
- CARLA source/UE4.26: not usable on this machine.
- GPU: Quadro P3200 Max-Q, driver `573.22`, 6144 MiB VRAM.

## Verification This Run

Focused offline regression pack:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests/unit/test_large_map_package.py tests/unit/test_tile_fbx_generator.py ultimate_pipeline/tests/unit/test_stage_capability_contract.py ultimate_pipeline/tests/unit/test_main_pipeline_stage_contract_wiring.py ultimate_pipeline/tests/unit/test_final_artifact_authority.py ultimate_pipeline/tests/unit/test_final_evidence_ordering.py ultimate_pipeline/tests/unit/test_classify_lane_count_transitions.py -q --tb=short
```

Result: `129 passed, 6 warnings in 14.69s`.

Default pytest plugin autoload is currently `INCOMPLETE` for this focused pack: the tests visibly reached 100%, but Python children continued consuming CPU until stopped. The same pack returns normally with plugin autoload disabled.

## Evidence State

Offline structural/code evidence is current through local production `f5333f3a`. UE import, cook, CARLA load, streaming, and 6 GB runtime qualification remain `BLOCKED_EXTERNAL`; no offline result is promoted to those evidence levels.
