# Thesis Experiments (Ingolstadt)

## Step 0: Validate cooked manual maps in CARLA
```powershell
python -m ultimate_pipeline.diagnostics.validate_manual_maps `
  --maps Grid0821 Grid0828 `
  --out .\thesis_runs\cooked_map_check
```

## Manual vs Manual (Structural sanity)
```powershell
python -m ultimate_pipeline.experiments.thesis.exp_manual_vs_manual_structural `
  --out-dir .\thesis_runs\manual_vs_manual
```

## Manual vs Auto (Structural)
```powershell
python -m ultimate_pipeline.experiments.thesis.exp_domain_gap_manual_vs_auto `
  --manual-town Grid0828 `
  --auto-xodr .\ultimate_pipeline_out\run_001_*\08_final*.xodr `
  --out-dir .\thesis_runs\manual_vs_auto
```

## Perception on cooked towns (Grid0821/0828)
```powershell
python -m ultimate_pipeline.tools.run_perception_safe `
  --manual-town Grid0821 `
  --town Grid0821 `
  --use-current-world `
  --out .\thesis_runs\perception_grid0821 `
  --frames 200 --fps 10

python -m ultimate_pipeline.tools.run_perception_safe `
  --manual-town Grid0828 `
  --town Grid0828 `
  --out .\thesis_runs\perception_grid0828 `
  --frames 200 --fps 10
```

## Batch experiments (run_thesis_experiments.py)
```powershell
python -m ultimate_pipeline.experiments.thesis.run_thesis_experiments `
  --auto_run_dir .\ultimate_pipeline_out\run_001_* `
  --manual-town Grid0828 `
  --out .\thesis_runs\thesis_run_001 `
  --capture-perception
```

Notes:
- Grid0821 is more stable when using `--use-current-world` to avoid CARLA map travel.
- Manual references are hard-wired:
  - Grid0821 -> manual_maps/Grid0821.xodr
  - Grid0828 -> manual_maps/manual_ingolstadt_grid0828.xodr
