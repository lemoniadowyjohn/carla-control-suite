#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
from typing import Optional, Dict, Any

from ultimate_pipeline.core.crash_classifier import CrashClassifier


def crash_intake(
        *,
        out_dir: str,
        vreport,
        stage: str,
        xodr_path: Optional[str] = None,
        carla_log_path: Optional[str] = None,
        sumo_log_path: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Collect log tails, classify crash, persist crash artifact.

    This must be safe to call from failure paths. It should never raise.
    """
    try:
        os.makedirs(out_dir, exist_ok=True)

        carla_tail = CrashClassifier.extract_recent_log(carla_log_path or "", tail=240)
        sumo_tail = CrashClassifier.extract_recent_log(sumo_log_path or "", tail=240)

        category = CrashClassifier.classify(carla_log=carla_tail, sumo_log=sumo_tail)

        crash_record = {
            "stage": stage,
            "category": category,
            "xodr_path": xodr_path,
            "carla_log_path": carla_log_path,
            "sumo_log_path": sumo_log_path,
            "carla_log_tail": carla_tail,
            "sumo_log_tail": sumo_tail,
            "extra": extra or {},
        }

        crash_json = os.path.join(out_dir, f"crash_{stage}.json")
        with open(crash_json, "w", encoding="utf-8") as f:
            json.dump(crash_record, f, indent=2)

        try:
            vreport.add_dict("crashes", {stage: {"category": category, "artifact": crash_json}})
        except Exception:
            pass

        return crash_record
    except Exception:
        return {"stage": stage, "category": CrashClassifier.UNKNOWN, "xodr_path": xodr_path}
