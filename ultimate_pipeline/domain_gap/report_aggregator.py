# ultimate_pipeline/domain_gap/report_aggregator.py

from __future__ import annotations

import json
import os
from glob import glob
from typing import Dict, Any, List, Optional


class ReportAggregator:
    """
    Aggregates experiment-level reports into a unified summary table.

    Input:
        JSON files written by ExperimentLogger / PerceptionGapReporter

    Output:
        - list of flattened rows (one per experiment)
        - optionally written to JSON (CSV-friendly structure)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate_experiments(
        exp_dir: str,
        out_json: Optional[str] = None,
        *,
        strict: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Parameters
        ----------
        exp_dir:
            Directory containing experiment JSON reports.

        out_json:
            Optional output path for aggregated JSON.

        strict:
            If True:
                missing keys raise exceptions.
            If False:
                missing fields are tolerated.

        Returns
        -------
        List[Dict[str, Any]]
            One flat dict per experiment.
        """

        paths = sorted(glob(os.path.join(exp_dir, "*.json")))
        rows: List[Dict[str, Any]] = []

        if not paths:
            raise RuntimeError(f"No experiment reports found in: {exp_dir}")

        for p in paths:
            row = ReportAggregator._load_and_flatten(
                p,
                strict=strict,
            )
            rows.append(row)

        # deterministic ordering (important for plots / CSV export)
        rows.sort(key=lambda r: r.get("experiment", ""))

        if out_json:
            os.makedirs(os.path.dirname(out_json), exist_ok=True)
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2)

        return rows

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _load_and_flatten(
        path: str,
        *,
        strict: bool,
    ) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            rep = json.load(f)

        row: Dict[str, Any] = {}

        # --------------------------------------------------------------
        # Experiment metadata
        # --------------------------------------------------------------
        row["experiment"] = rep.get("experiment", os.path.basename(path))

        meta = rep.get("metadata", {})
        if isinstance(meta, dict):
            for k, v in meta.items():
                row[f"meta_{k}"] = v

        # --------------------------------------------------------------
        # Domain gap (flattened)
        # --------------------------------------------------------------
        dg = rep.get("domain_gap")
        if dg is None:
            if strict:
                raise KeyError(f"Missing domain_gap in {path}")
        else:
            ReportAggregator._flatten_dict(
                dg,
                prefix="dg",
                out=row,
            )

        # --------------------------------------------------------------
        # Perception gap (flattened)
        # --------------------------------------------------------------
        pg = rep.get("perception_gap")
        if pg is None:
            if strict:
                raise KeyError(f"Missing perception_gap in {path}")
        else:
            ReportAggregator._flatten_dict(
                pg,
                prefix="pg",
                out=row,
            )

        # --------------------------------------------------------------
        # Optional scalar scores (QMS, etc.)
        # --------------------------------------------------------------
        scores = rep.get("scores", {})
        if isinstance(scores, dict):
            for k, v in scores.items():
                row[f"score_{k}"] = v

        # --------------------------------------------------------------
        # Bookkeeping
        # --------------------------------------------------------------
        row["_source_file"] = os.path.basename(path)

        return row

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_dict(
        d: Dict[str, Any],
        *,
        prefix: str,
        out: Dict[str, Any],
    ) -> None:
        """
        Flatten nested dictionaries using prefix_key notation.

        Example:
            {"rmse": 0.1, "timings": {"union": 3.2}}
        →
            dg_rmse = 0.1
            dg_timings_union = 3.2
        """

        for k, v in d.items():
            key = f"{prefix}_{k}"
            if isinstance(v, dict):
                for kk, vv in v.items():
                    out[f"{key}_{kk}"] = vv
            else:
                out[key] = v
