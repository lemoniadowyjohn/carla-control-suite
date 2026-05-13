# ultimate_pipeline/experiments/runner.py

from __future__ import annotations
import json
import os

from .trainer import Trainer
from .evaluator import Evaluator
from ultimate_pipeline.domain_gap.experiment_logger import ExperimentLogger
from ultimate_pipeline.domain_gap.report_aggregator import ReportAggregator


class ExperimentRunner:
    """
    Orchestrates:
        1) training
        2) evaluation
        3) domain gap computation
        4) perception gap computation
        5) experiment logging
        6) entry in global experiment summary
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

    def run(self):
        exp_name = self.cfg["experiment"]["name"]
        out_dir = f"logs/experiments/{exp_name}"
        os.makedirs(out_dir, exist_ok=True)

        print(f"=== Running experiment: {exp_name} ===")

        # 1) Train
        trainer = Trainer(self.cfg)
        trainer.train()

        # 2) Evaluate on real test set
        evaluator = Evaluator(self.cfg)
        perception_metrics = evaluator.evaluate()

        # 3) Compute domain gap
        domain_gap = evaluator.compute_domain_gap()

        # 4) Compute perception gap against manual map
        perception_gap = evaluator.compute_perception_gap()

        # 5) Log experiment
        report_path = f"{out_dir}/experiment.json"
        ExperimentLogger.write_report(
            exp_name=exp_name,
            domain_gap=domain_gap,
            perception_gap=perception_gap,
            out_path=report_path,
        )

        print(f"✔ Experiment {exp_name} complete → {report_path}")

        # 6) Regenerate global summary
        ReportAggregator.aggregate_experiments(
            exp_dir="logs/experiments",
            out_json="logs/experiments_summary.json"
        )
