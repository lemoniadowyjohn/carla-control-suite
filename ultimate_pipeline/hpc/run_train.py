# hpc/run_train.py
import json
import sys
from ultimate_pipeline.experiments.trainer import Trainer

if len(sys.argv) != 2:
    raise RuntimeError("Usage: run_train.py <config.json>")

cfg_path = sys.argv[1]
with open(cfg_path) as f:
    cfg = json.load(f)

# HARD REQUIREMENT
if "dataset_hash" not in cfg:
    raise RuntimeError("Config missing dataset_hash")

trainer = Trainer(cfg)
trainer.train()
