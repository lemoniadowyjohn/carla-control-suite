from __future__ import annotations
import os
import yaml
from typing import Dict


class DatasetBuilder:
    """
    Creates YOLO data.yaml files for:
    - manual dataset
    - auto dataset
    - mixed dataset
    """

    @staticmethod
    def build_auto_dataset(root: str, out_yaml: str):
        """
        root:
           images/train
           images/val
           labels/train
           labels/val
        """
        data = {
            "path": root,
            "train": "images/train",
            "val": "images/val",
            "names": ["road", "lane", "building"]   # adjust later
        }
        with open(out_yaml, "w") as f:
            yaml.dump(data, f)

    @staticmethod
    def build_manual_dataset(root: str, out_yaml: str):
        DatasetBuilder.build_auto_dataset(root, out_yaml)

    @staticmethod
    def build_mixed_dataset(auto_root: str, manual_root: str, out_yaml: str):
        data = {
            "train": [
                f"{auto_root}/images/train",
                f"{manual_root}/images/train"
            ],
            "val": [
                f"{auto_root}/images/val",
                f"{manual_root}/images/val"
            ],
            "names": ["road", "lane", "building"]
        }
        with open(out_yaml, "w") as f:
            yaml.dump(data, f)
