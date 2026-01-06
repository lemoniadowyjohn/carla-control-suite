# ultimate_pipeline/core/validation_report.py

import json
import os
import time
from datetime import datetime


class ValidationReport:
    """
    Unified logging + diagnostics report for the ultimate pipeline.

    Fully compatible with:
      - old pipeline (log_success / log_failure / log_skipped)
      - new modular pipeline (add, add_dict, add_warning, get_failing_roads)
    """

    LOG_PATH = None

    def __init__(self):
        # high-level pipeline stage entries (old system)
        self.stage_entries = []

        # new diagnostics buckets
        self.data = {
            "warnings": [],
            "errors": [],
            "success": [],
            "skipped": [],
            "details": {},  # structure_scan, semantic_risk, final_carla_test
            "failing_roads": set(),
            "timestamp": datetime.now().isoformat(),
        }

    # ===========================================================
    # INITIALIZATION (old system)
    # ===========================================================
    @staticmethod
    def init(out_dir: str):
        log_dir = os.path.join(out_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        ValidationReport.LOG_PATH = os.path.join(log_dir, "pipeline_report.json")

    # ===========================================================
    # INTERNAL WRITER
    # ===========================================================
    def _write(self):
        if not self.LOG_PATH:
            return

        serializable = {
            "stage_entries": self.stage_entries,
            "diagnostics": {
                **self.data,
                "failing_roads": list(self.data["failing_roads"])
            }
        }

        try:
            with open(self.LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=4)
        except Exception as e:
            print(f"⚠ ValidationReport: failed to write JSON: {e}")

    # ===========================================================
    # OLD API (for backward compatibility)
    # ===========================================================
    def log_success(self, stage: str, msg: str = ""):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.stage_entries.append({
            "timestamp": ts,
            "stage": stage,
            "status": "success",
            "details": msg,
        })
        self._write()

    def log_failure(self, stage: str, reason: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.stage_entries.append({
            "timestamp": ts,
            "stage": stage,
            "status": "failure",
            "details": reason,
        })
        self._write()

    def log_skipped(self, stage: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.stage_entries.append({
            "timestamp": ts,
            "stage": stage,
            "status": "skipped",
            "details": "stage disabled or not executed",
        })
        self._write()

    # ===========================================================
    # NEW API (required by modular pipeline)
    # ===========================================================
    def add(self, level: str, stage: str, message: str):
        entry = {"stage": stage, "message": message, "level": level}

        if level == "warning":
            self.data["warnings"].append(entry)
        elif level == "error":
            self.data["errors"].append(entry)
        elif level == "success":
            self.data["success"].append(entry)
        elif level == "skipped":
            self.data["skipped"].append(entry)
        else:
            self.data["warnings"].append(entry)

        self._write()

    def add_warning(self, stage: str, msg: str):
        self.add("warning", stage, msg)

    def add_dict(self, stage: str, dictionary: dict):
        self.data["details"][stage] = dictionary
        self._write()

    def record_failing_road(self, rid: str):
        self.data["failing_roads"].add(str(rid))
        self._write()

    def get_failing_roads(self):
        return list(self.data["failing_roads"])

    # ===========================================================
    # Export full report
    # ===========================================================
    def save_json(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # Convert non-JSON types (like sets) into serializable forms
        serializable = {
            "stage_entries": self.stage_entries,
            "diagnostics": {
                **self.data,
                "failing_roads": list(self.data["failing_roads"])
            },
            "timestamp": datetime.now().isoformat(),
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=4)

        print(f"[ValidationReport] saved → {path}")
