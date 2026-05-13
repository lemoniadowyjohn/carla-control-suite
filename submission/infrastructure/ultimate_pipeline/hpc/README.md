# HPC CARLA OpenDRIVE Toolbox (curated)

This bundle is meant to replace a large pile of older scripts with **a tiny, HPC-friendly toolbox**
focused on your current goal: **load OpenDRIVE (.xodr) into CARLA reliably and run experiments**.

## Files (keep these; delete the rest)
1) `hpc_preflight.py`
   - Checks CARLA PythonAPI import, server connectivity, and whether your canonical loader is importable.

2) `hpc_load_opendrive_batch.py`
   - Loads one XODR file or a directory of XODRs into CARLA, using:
     `ultimate_pipeline.core.carla_opendrive_loader.load_opendrive_world()`
   - Writes a CSV summary (spawn points count, etc.)
   - Optional baseline map pre-load (`--baseline-map Town01`) to avoid "Town10HD_Opt" startup noise.

3) `spawn_manager.py`
   - Small set of robust spawning helpers (safe spawn with retries, clear spawn-point picking).
   - Use this from QA scripts / dataset generation to reduce "spawn failed" flakiness.

4) `carla_server_launcher.py` (optional)
   - Cross-platform-ish launcher for CARLA server with offscreen/low-quality flags.
   - Uses `CARLA_ROOT` env var by default.

## Typical HPC workflow
A) Start CARLA server (separate terminal / job):
   - Linux example:
     export CARLA_ROOT=/path/to/CARLA
     python carla_server_launcher.py --offscreen --low-quality --port 2000
   - Or start CARLA however you normally do on the cluster.

B) Preflight check:
   python hpc_preflight.py --host 127.0.0.1 --port 2000

C) Load + verify OpenDRIVE maps:
   python hpc_load_opendrive_batch.py --xodr /path/to/maps --baseline-map Town01

Notes:
- These scripts intentionally avoid GUI / pygame (HPC-safe).
- They try to import your canonical loader; if unavailable, they fall back to `client.generate_opendrive_world()`.

---

## YOLO training on HPC (sanity-scale, thesis-friendly)

This repo also includes a small, reproducible YOLO training entrypoint that writes a
single deterministic JSON report per job:

- Entry point: `ultimate_pipeline/hpc/train_yolo.py`
- Configs: `ultimate_pipeline/hpc/configs/yolo_manual.json`, `yolo_auto.json`, `yolo_mixed.json`
- Reports: `ultimate_pipeline/logs/hpc/<exp-name>_yolo_report.json`

The included SLURM job scripts are ready-to-submit examples:

- `ultimate_pipeline/hpc/jobs/ingolstadt_manual_yolo.sh`
- `ultimate_pipeline/hpc/jobs/ingolstadt_auto_yolo.sh`
- `ultimate_pipeline/hpc/jobs/ingolstadt_mixed_yolo.sh`

Submit them from the repo root (or any directory, as long as `$SLURM_SUBMIT_DIR` points
to the repo root):

```bash
sbatch ultimate_pipeline/hpc/jobs/ingolstadt_manual_yolo.sh
sbatch ultimate_pipeline/hpc/jobs/ingolstadt_auto_yolo.sh
sbatch ultimate_pipeline/hpc/jobs/ingolstadt_mixed_yolo.sh
```

### Ultralytics dependency

`train_yolo.py` uses Ultralytics YOLO. On an HPC environment, install it inside your
job environment (venv/conda) before running:

```bash
pip install ultralytics
```

---

## Docker smoke test (optional)

Some HPC systems use containers (Docker/Apptainer/Singularity). This folder includes a
minimal Dockerfile that can be used as a *local* smoke test for the YOLO entrypoint.

Files:
- `ultimate_pipeline/hpc/Dockerfile.yolo_smoke`
- `ultimate_pipeline/hpc/docker_smoke_test.sh`

Example (local machine with Docker):

```bash
docker build -f ultimate_pipeline/hpc/Dockerfile.yolo_smoke -t ultimate-pipeline-yolo-smoke .
docker run --rm -it ultimate-pipeline-yolo-smoke bash ultimate_pipeline/hpc/docker_smoke_test.sh
```

This smoke test does **not** require CARLA; it only checks that:
- the repo imports cleanly
- the training entrypoint runs and fails gracefully if Ultralytics is missing
