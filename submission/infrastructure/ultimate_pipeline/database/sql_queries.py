"""
Predefined SQL queries + helpers for domain gap analytics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ultimate_pipeline.database.db_manager import Database


@dataclass
class MetricSummary:
    metric_name: str
    count: int
    mean: float | None
    std: float | None
    min: float | None
    max: float | None


def summary_by_metric(db: Database) -> List[MetricSummary]:
    """
    Aggregate metrics across all tiles, grouped by metric_name.
    """
    conn = db._connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            metric_name,
            COUNT(*) as count,
            AVG(metric_value) as mean,
            SUM((metric_value - AVG(metric_value)) * (metric_value - AVG(metric_value))) OVER (PARTITION BY metric_name) / NULLIF(COUNT(*) - 1, 0) as var,
            MIN(metric_value) as min_val,
            MAX(metric_value) as max_val
        FROM domain_gap_metrics
        GROUP BY metric_name
        """
    )
    rows = cur.fetchall()
    conn.close()

    summaries = []
    for r in rows:
        metric_name, count, mean, var, min_val, max_val = r
        std = (var ** 0.5) if var is not None else None
        summaries.append(
            MetricSummary(
                metric_name=metric_name,
                count=count,
                mean=mean,
                std=std,
                min=min_val,
                max=max_val,
            )
        )
    return summaries


def tile_metric_vector(db: Database, tile_id: str) -> Dict[str, float]:
    """
    Returns a dict {metric_name: metric_value} for a given tile.
    Useful for manual vs auto comparison.
    """
    conn = db._connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT metric_name, metric_value
        FROM domain_gap_metrics
        WHERE tile_id = ?
        """,
        (tile_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return {name: value for name, value in rows}


def metric_distribution_for_map(db: Database, metric_name: str) -> Dict[str, Any]:
    """
    Returns (tile_id, metric_value) for a given metric_name.
    """
    conn = db._connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT tile_id, metric_value
        FROM domain_gap_metrics
        WHERE metric_name = ?
        ORDER BY tile_id
        """,
        (metric_name,),
    )
    rows = cur.fetchall()
    conn.close()
    return {
        "metric_name": metric_name,
        "tiles": [r[0] for r in rows],
        "values": [r[1] for r in rows],
    }


def delete_all_metrics(db: Database):
    """
    Utility for regenerating domain gap metrics from scratch.
    """
    conn = db._connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM domain_gap_metrics")
    conn.commit()
    conn.close()
