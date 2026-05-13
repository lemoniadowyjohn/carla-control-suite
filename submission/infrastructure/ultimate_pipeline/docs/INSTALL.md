# Installation Notes

1. **Create an isolated environment** (recommended) and upgrade `pip`:
   ```powershell
   python -m venv .venv
   .venv\\Scripts\\activate
   pip install --upgrade pip
   ```

2. **Install the core dependencies** (this picks up the `pyproject.toml` metadata):
   ```bash
   pip install .
   ```
   *Use `pip install -e .` if you plan to edit the repository live.*

3. **Optional extras**
   - GPU/experiments stack:
     ```bash
     pip install .[experiments]
     ```
   - CARLA API (manual step because the wheel depends on your CARLA binary version):
     1. Download the matching Python API wheel from https://github.com/carla-simulator/carla/releases (e.g., `carla-0.9.14-py3.10-win-amd64.egg`).
     2. Install it with:
        ```bash
        pip install --no-deps path\\to\\carla-*.egg
        ```
     3. Confirm `pip install .[carla]` runs without importing CARLA at install time after the wheel is available in the wheel cache.
   - When CARLA cannot be installed, the repository remains import-safe because the CARLA boundary only triggers at runtime.

4. **Smoke-check commands**
   - `python -c "import ultimate_pipeline; print('IMPORT_OK')"`.
   - `python ultimate_pipeline/run_pipeline.py --help`.
   - `python -m ultimate_pipeline.cli --help`.
   - `python -m ultimate_pipeline.tools.run_perception_pair --help`.

5. **Tests**
   ```bash
   pytest -q ultimate_pipeline/tests
   ```

6. **Perception manifest**
   Every `run_perception_pair` execution now writes `pair_manifest.json` (including failure metadata such as `return_code`, CLI args, xodr hash, host/port, and failure reasons). The `PerceptionReturnCode` values are defined in `ultimate_pipeline/core/return_codes.py`.
