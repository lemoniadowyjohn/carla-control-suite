# ultimate_pipeline/hpc/yolo_backend.py

from __future__ import annotations
import os
from typing import Dict, Any

from ultralytics import YOLO


class YOLOBackend:
    """
    Wrapper around Ultralytics YOLO for:
    - training
    - validation
    - metric extraction
    """

    @staticmethod
    def train_and_eval(cfg: Dict[str, Any]) -> Dict[str, Any]:
        """
        cfg expects:
        {
           "model": "yolov8n-seg.pt",
           "data": "/path/to/data.yaml",
           "imgsz": 640,
           "epochs": 40,
           "batch": 8,
           "device": 0 or "cpu",
           "project": "runs/exp_name"
        }
        """

        model_path = cfg["model"]
        data_yaml  = cfg["data"]
        imgsz      = cfg.get("imgsz", 640)
        epochs     = cfg.get("epochs", 40)
        batch      = cfg.get("batch", 8)
        device     = cfg.get("device", 0)
        project    = cfg.get("project", "runs/train")

        # Load YOLO
        model = YOLO(model_path)

        # Train
        model.train(
            data=data_yaml,
            epochs=epochs,
            imgsz=imgsz,
            batch=batch,
            device=device,
            project=project,
            name="train"
        )

        # Evaluate
        results = model.val(
            data=data_yaml,
            imgsz=imgsz,
            batch=batch,
            device=device,
            project=project,
            name="val"
        )

        # Extract metrics
        # YOLO returns: results.metrics.box.map, results.metrics.seg.mp, results.metrics.seg.miou
        # We convert to your standard PerceptionMetrics format.

        miou = {}
        if hasattr(results.metrics, "seg"):
            miou_global = float(results.metrics.seg.miou)
            miou["global"] = miou_global

        mAP = float(results.metrics.box.map)

        return {
            "miou": miou,
            "mAP": mAP
        }
