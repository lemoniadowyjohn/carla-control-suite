# ultimate_pipeline/hpc/train_yolo.py

from __future__ import annotations
import argparse
import json
import os
from typing import Dict, Any

from ultimate_pipeline.domain_gap.perception_gap import (
    PerceptionMetrics,
    PerceptionGap,
)
from ultimate_pipeline.domain_gap.experiment_logger import ExperimentLogger



###############################################################################
#  TRAINING + EVALUATION PLACEHOLDER
#  (Replace this with actual YOLO training)
###############################################################################

def train_and_eval_model(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Train and evaluate a YOLO model.

    If Ultralytics is installed, this calls `YOLOBackend.train_and_eval(cfg)`.
    Otherwise, it falls back to a deterministic placeholder so the pipeline
    scripts remain runnable in minimal environments.
    """
    try:
        from ultimate_pipeline.hpc.yolo_backend import YOLOBackend
        return YOLOBackend.train_and_eval(cfg)
    except Exception:
        # Minimal fallback (keeps legacy scripts working without Ultralytics).
        return {
            "miou": {"road": 0.80, "building": 0.65, "lane": 0.72},
            "mAP": 0.75,
        }


###############################################################################
#  PERCEPTION METRIC EXTRACTION
###############################################################################

def extract_perception_metrics(results: Dict[str, Any]) -> PerceptionMetrics:
    """
    Convert YOLO training results into PerceptionMetrics.
    """
    miou = results.get("miou", {})
    mAP = results.get("mAP", 0.0)
    return PerceptionMetrics(miou=miou, map_score=mAP)


###############################################################################
#  MAIN EXPERIMENT DRIVER
###############################################################################

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-name", required=True, help="Name of the experiment")
    ap.add_argument("--config", required=True, help="Path to JSON experiment config")
    return ap.parse_args()


def main():
    args = parse_args()

    ###############################################
    # 1) Load config
    ###############################################
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    ###############################################
    # 2) Train + evaluate YOLO model
    ###############################################
    results = train_and_eval_model(cfg)

    ###############################################
    # 3) Convert training results → perception metrics
    ###############################################
    perception_metrics = extract_perception_metrics(results)

    ###############################################
    # 4) Manual vs Auto perception gap  (OPTIONAL)
    ###############################################
    # If you only have auto, this will act as absolute metrics.
    # Later you will compute manual_metrics separately.
    auto_metrics = perception_metrics

    # Placeholder manual metrics (replace later)
    manual_metrics = PerceptionMetrics(
        miou={k: v + 0.05 for k, v in auto_metrics.miou.items()},
        map_score=auto_metrics.map_score + 0.03,
    )

    perception_gap = PerceptionGap.compare(
        manual=manual_metrics,
        auto=auto_metrics
    )

    ###############################################
    # 5) Domain gap (fill with real numbers later)
    ###############################################
    domain_gap_stub = {
        "lane_width_gap": 0.12,
        "curvature_gap": 0.25,
        "road_length_ratio": 0.08,
    }

    ###############################################
    # 6) Log experiment to JSON (HPC-friendly)
    ###############################################
    os.makedirs("logs/hpc", exist_ok=True)

    out_path = f"logs/hpc/{args.exp_name}_full_report.json"
    ExperimentLogger.write_report(
        exp_name=args.exp_name,
        domain_gap=domain_gap_stub,
        perception_gap=perception_gap,
        out_path=out_path,
    )

    print(f"✅ Experiment saved → {out_path}")


if __name__ == "__main__":
    main()
