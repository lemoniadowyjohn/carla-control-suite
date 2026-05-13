# Manual vs Generated Domain Gap (CARLA 0.9.16, Windows)

## Prereqs
- CARLA 0.9.16 installed at `E:\CARLA\CARLA_0.9.16`
- Manual maps present in runtime: `Grid0821`, `Grid0828`
- Python env activated (repo `.venv` or your own)

## Start CARLA (low-VRAM safe)
```powershell
python -m ultimate_pipeline.diagnostics.validate_manual_maps --no-start --help  # to see options
# To start CARLA automatically:
python -m ultimate_pipeline.diagnostics.validate_manual_maps --maps Grid0821 Grid0828 --carla-exe E:\CARLA\CARLA_0.9.16\CarlaUE4.exe
```
Flags used: `-d3d11 -nosound -quality-level=Low -windowed -ResX=1280 -ResY=720`
Python also enables `no_rendering_mode=True` during validation/capture to reduce GPU load.
Env override for map list: `UP_MANUAL_MAPS="Grid0821,Grid0828"`
Outputs (defaults):
- Validation report: `ultimate_pipeline_out/validation/manual_maps_report.json`
- Domain-gap structural: `ultimate_pipeline_out/domain_gap_manual/`

## Validate manual maps
```powershell
python -m ultimate_pipeline.diagnostics.validate_manual_maps --maps Grid0821 Grid0828 --host 127.0.0.1 --port 2000 --carla-exe E:\CARLA\CARLA_0.9.16\CarlaUE4.exe
```
Writes JSON to `ultimate_pipeline_out/validation/manual_maps.json`.

## Run manual-map structural gap analysis
```powershell
python -m ultimate_pipeline.dev_tools.tools.run_domain_gap_analysis --manual-maps Grid0821 Grid0828 --carla-exe E:\CARLA\CARLA_0.9.16\CarlaUE4.exe --out ultimate_pipeline_out/domain_gap_manual
```
Outputs per-map structural metrics under `ultimate_pipeline_out/domain_gap_manual/`.

## Compare with generated XODR (optional)
Add `--auto-xodr <path-to-generated.xodr>` to the command above. An `auto_xodr.json` will be written alongside manual results.
