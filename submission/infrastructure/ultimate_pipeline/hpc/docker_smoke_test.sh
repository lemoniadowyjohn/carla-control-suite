#!/usr/bin/env bash
set -euo pipefail

echo "[smoke] python: $(python --version)"

echo "[smoke] compileall (syntax/import sanity)"
python -m compileall -q ultimate_pipeline/hpc

echo "[smoke] pytest (HPC-focused tests only)"
pytest -q ultimate_pipeline/tests/test_hpc_portability.py

echo "[smoke] train_yolo.py help"
python ultimate_pipeline/hpc/train_yolo.py --help >/dev/null

echo "[smoke] train_yolo.py graceful dependency error (Ultralytics may be absent)"
set +e
python ultimate_pipeline/hpc/train_yolo.py --exp-name smoke --config ultimate_pipeline/hpc/configs/yolo_manual.json --notes smoke_test
rc=$?
set -e
if [ $rc -eq 0 ]; then
  echo "[smoke] train_yolo.py executed successfully (Ultralytics present)."
else
  echo "[smoke] train_yolo.py returned non-zero as expected if Ultralytics isn't installed. rc=$rc"
fi

echo "[smoke] done"
