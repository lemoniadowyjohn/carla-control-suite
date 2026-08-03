# ultimate_pipeline/domain_gap/experiment_logger.py

from __future__ import annotations

import json
import os
import time
import hashlib
from typing import Dict, Any, Optional


class ExperimentLogger:
    """
    Central logger for domain-gap and perception experiments.

    Design goals:
    - deterministic
    - append-safe (HPC jobs)
    - provenance-aware
    - correlation-ready

    Output is a single JSON document per experiment.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def write_report(
        *,
        experiment_name: str,
        domain_gap: Dict[str, Any],
        perception_gap: Optional[Dict[str, Any]],
        out_path: str,
        settings_snapshot: Optional[Dict[str, Any]] = None,
        map_hashes: Optional[Dict[str, str]] = None,
        runtime_sec: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> None:
        """
        Write a complete experiment report.

        Parameters
        ----------
        experiment_name:
            Human-readable experiment identifier
            (e.g. "geom_only_seed42")

        domain_gap:
            Output of run_full_domain_gap() or subset thereof

        perception_gap:
            Output of perception comparison (may be None)

        out_path:
            Target JSON file path

        settings_snapshot:
            Optional SETTINGS snapshot (dict, already serializable)

        map_hashes:
            Optional map hashes:
                {
                    "manual_md5": "...",
                    "auto_md5": "..."
                }

        runtime_sec:
            Optional total runtime of the experiment

        notes:
            Optional free-text annotation
        """

        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        report: Dict[str, Any] = {
            "experiment": {
                "name": experiment_name,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "epoch": time.time(),
            },
            "results": {
                "domain_gap": domain_gap,
                "perception_gap": perception_gap,
            },
            "provenance": {
                "settings": settings_snapshot,
                "map_hashes": map_hashes,
                "runtime_sec": runtime_sec,
            },
            "notes": notes,
        }

        # clean None entries (important for HPC diffs)
        report = ExperimentLogger._prune_none(report)

        # attach deterministic fingerprint (sha256 primary, md5 legacy)
        report["_fingerprint_sha256"] = ExperimentLogger._fingerprint_sha256(report)
        report["_fingerprint_md5"] = ExperimentLogger._fingerprint_md5(report)
        report["_fingerprint"] = report["_fingerprint_sha256"]

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"[ExperimentLogger] Report written → {out_path}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint_sha256(obj: Dict[str, Any]) -> str:
        """
        Compute a stable SHA-256 fingerprint of the experiment contents.
        """
        clean = ExperimentLogger._strip_fingerprint_keys(obj)
        blob = json.dumps(clean, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    @staticmethod
    def _fingerprint_md5(obj: Dict[str, Any]) -> str:
        """
        Compute a stable MD5 fingerprint of the experiment contents (legacy).
        """
        clean = ExperimentLogger._strip_fingerprint_keys(obj)
        blob = json.dumps(clean, sort_keys=True).encode("utf-8")
        return hashlib.md5(blob).hexdigest()

    @staticmethod
    def _strip_fingerprint_keys(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: ExperimentLogger._strip_fingerprint_keys(v)
                for k, v in obj.items()
                if not str(k).startswith("_fingerprint")
            }
        if isinstance(obj, list):
            return [ExperimentLogger._strip_fingerprint_keys(v) for v in obj]
        return obj

    @staticmethod
    def _prune_none(obj: Any) -> Any:
        """
        Recursively remove None values from dictionaries.
        """
        if isinstance(obj, dict):
            return {
                k: ExperimentLogger._prune_none(v)
                for k, v in obj.items()
                if v is not None
            }
        if isinstance(obj, list):
            return [ExperimentLogger._prune_none(v) for v in obj]
        return obj
