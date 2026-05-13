# ultimate_pipeline/data/curator.py

from __future__ import annotations
import os
import json
import shutil
from glob import glob
from typing import Dict

class DatasetCurator:
    """
    Build synthetic dataset shards (train, val, test) with consistent metadata.
    """

    @staticmethod
    def curate(input_dir: str, out_dir: str, ratio=(0.7, 0.2, 0.1)):
        all_images = sorted(glob(f"{input_dir}/rgb/*.png"))
        n = len(all_images)

        n_train = int(n * ratio[0])
        n_val = int(n * ratio[1])

        splits = {
            "train": all_images[:n_train],
            "val": all_images[n_train:n_train+n_val],
            "test": all_images[n_train+n_val:]
        }

        for split, imgs in splits.items():
            split_dir = os.path.join(out_dir, split)
            os.makedirs(split_dir, exist_ok=True)
            for img in imgs:
                shutil.copy(img, split_dir)

        print(f"Dataset curated: {out_dir}")
