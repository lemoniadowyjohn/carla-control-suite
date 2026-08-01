"""Aggregate existing pipeline outputs into CSVs, plots, and LaTeX tables.

This script only reads artifacts that already exist under ``ultimate_pipeline_out``.
It does not launch CARLA or run any pipeline stages. Usage (from repo root):

```
python -m ultimate_pipeline.analysis.pipeline_output_summary \
  --output-dir _analysis_out/pipeline_summary
```
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "ultimate_pipeline_out"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "_analysis_out" / "pipeline_summary"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Failed to read {path}: {exc}")
        return {}


def _infer_run_id(rel_parts: Tuple[str, ...]) -> str:
    if not rel_parts:
        return "unknown"
    if rel_parts[0] == "thesis_final_runs" and len(rel_parts) >= 2:
        return "/".join(rel_parts[:2])
    return rel_parts[0]


def _infer_map_name(run_dir: Path) -> str:
    manifest_path = run_dir / "run_manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    input_xodr = (
        manifest.get("inputs", {})
        .get("INPUT_XODR", {})
        .get("path")
    )
    if input_xodr:
        return Path(str(input_xodr)).stem
    return run_dir.name


def collect_map_statistics(output_root: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    records: List[Dict[str, Any]] = []
    speed_rows: List[Dict[str, Any]] = []
    for json_path in output_root.rglob("map_statistics.json"):
        rel_parts = json_path.relative_to(output_root).parts
        run_id = _infer_run_id(rel_parts)
        category = "thesis_final" if "thesis_final_runs" in rel_parts else "pipeline_run"
        run_dir = json_path.parent
        map_name = _infer_map_name(run_dir)

        data = _read_json(json_path)
        roads = data.get("roads", {})
        lanes = data.get("lanes", {})
        traffic = data.get("traffic", {})
        geometry = data.get("geometry", {})

        total_length_m = roads.get("total_length_m")
        lanes_total = lanes.get("total_lanes")
        lanes_per_km = None
        if total_length_m and lanes_total:
            try:
                lanes_per_km = lanes_total / (total_length_m / 1000.0)
            except ZeroDivisionError:
                lanes_per_km = None

        records.append(
            {
                "run_id": run_id,
                "category": category,
                "map_name": map_name,
                "roads_count": roads.get("count"),
                "road_length_m": total_length_m,
                "road_length_km": total_length_m / 1000.0 if total_length_m else None,
                "road_length_avg_m": roads.get("avg_length_m"),
                "road_length_min_m": roads.get("min_length_m"),
                "road_length_max_m": roads.get("max_length_m"),
                "junctions_count": data.get("junctions", {}).get("count"),
                "lanes_total": lanes_total,
                "lanes_per_road": lanes.get("avg_lanes_per_road"),
                "lane_width_min": lanes.get("width_min"),
                "lane_width_avg": lanes.get("width_avg"),
                "lane_width_max": lanes.get("width_max"),
                "lanes_per_km": lanes_per_km,
                "geometry_line": geometry.get("geometry_counts", {}).get("line"),
                "geometry_poly3": geometry.get("geometry_counts", {}).get("poly3"),
                "geometry_param_poly3": geometry.get("geometry_counts", {}).get("paramPoly3"),
                "signals_total": traffic.get("signals_total"),
                "success": bool(data.get("success", False)),
                "source_path": str(json_path.relative_to(output_root)),
            }
        )

        for speed, count in (traffic.get("speed_limit_distribution") or {}).items():
            try:
                speed_int = int(speed)
                count_int = int(count)
            except (TypeError, ValueError):
                continue
            speed_rows.append(
                {
                    "run_id": run_id,
                    "category": category,
                    "map_name": map_name,
                    "speed_kph": speed_int,
                    "count": count_int,
                }
            )
    return records, speed_rows


def collect_thesis_structural_summaries(output_root: Path) -> pd.DataFrame:
    thesis_root = output_root / "thesis_final_runs"
    if not thesis_root.is_dir():
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    for json_path in thesis_root.rglob("structural_summary.json"):
        rel_parts = json_path.relative_to(thesis_root).parts
        run_tag = rel_parts[0] if rel_parts else "unknown"
        stage = rel_parts[1] if len(rel_parts) > 1 else ""
        data = _read_json(json_path)
        rows.append(
            {
                "run_tag": run_tag,
                "stage": stage,
                "map_id": data.get("map_id"),
                "map_type": data.get("map_type"),
                "status": data.get("status"),
                "failure_reason": data.get("failure_reason"),
                "roads": data.get("roads"),
                "junctions": data.get("junctions"),
                "lane_sections": data.get("lane_sections"),
                "coor_points": data.get("coor_points"),
                "sha256": data.get("sha256"),
                "xodr_path": data.get("xodr_path"),
                "source_path": str(json_path.relative_to(output_root)),
            }
        )
    return pd.DataFrame(rows)


def collect_thesis_summary_tables(thesis_root: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    carla_rows: List[Dict[str, Any]] = []
    perception_rows: List[Dict[str, Any]] = []

    for run_dir in thesis_root.iterdir():
        if not run_dir.is_dir():
            continue
        summary_dir = run_dir / "08_summary_tables"
        if not summary_dir.is_dir():
            continue

        carla_path = summary_dir / "carla_loadability.csv"
        perception_path = summary_dir / "perception_proxy.csv"

        if carla_path.is_file():
            df = pd.read_csv(carla_path)
            df.insert(0, "run_tag", run_dir.name)
            carla_rows.append(df)

        if perception_path.is_file():
            df = pd.read_csv(perception_path)
            df.insert(0, "run_tag", run_dir.name)
            perception_rows.append(df)

    carla_df = pd.concat(carla_rows, ignore_index=True) if carla_rows else pd.DataFrame()
    perception_df = pd.concat(perception_rows, ignore_index=True) if perception_rows else pd.DataFrame()
    return carla_df, perception_df


def summarize_numeric(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for col in columns:
        if col not in df:
            continue
        series = df[col].dropna()
        if series.empty:
            continue
        rows.append(
            {
                "metric": col,
                "count": int(series.count()),
                "mean": float(series.mean()),
                "std": float(series.std()),
                "min": float(series.min()),
                "median": float(series.median()),
                "max": float(series.max()),
            }
        )
    return pd.DataFrame(rows)


def plot_bar(df: pd.DataFrame, x_col: str, y_col: str, title: str, ylabel: str, path: Path) -> None:
    if df.empty or y_col not in df or x_col not in df:
        return
    ordered = df.dropna(subset=[y_col]).sort_values(y_col, ascending=False)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(ordered[x_col], ordered[y_col], color="#1f77b4", edgecolor="black", linewidth=0.8)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_speed_distribution(speed_df: pd.DataFrame, path: Path) -> None:
    if speed_df.empty:
        return
    agg = (
        speed_df.groupby("speed_kph")["count"]
        .sum()
        .reset_index()
        .sort_values("speed_kph")
    )
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(agg["speed_kph"], agg["count"], color="#ff7f0e", edgecolor="black", linewidth=0.8)
    ax.set_xlabel("Speed limit (arbitrary units)")
    ax.set_ylabel("Count across runs")
    ax.set_title("Aggregated speed-limit annotations")
    plt.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_scatter(df: pd.DataFrame, x_col: str, y_col: str, title: str, xlabel: str, ylabel: str, path: Path) -> None:
    if df.empty or x_col not in df or y_col not in df:
        return
    valid = df.dropna(subset=[x_col, y_col])
    if valid.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(valid[x_col], valid[y_col], color="#2ca02c", edgecolors="black", linewidths=0.5)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    plt.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize existing ultimate_pipeline outputs (no CARLA required).")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for CSVs/plots (default: _analysis_out/pipeline_summary/<timestamp>)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / timestamp)
    output_dir.mkdir(parents=True, exist_ok=True)

    map_records, speed_rows = collect_map_statistics(OUTPUT_ROOT)
    map_df = pd.DataFrame(map_records)
    speed_df = pd.DataFrame(speed_rows)

    thesis_structural = collect_thesis_structural_summaries(OUTPUT_ROOT)
    thesis_root = OUTPUT_ROOT / "thesis_final_runs"
    carla_df, perception_df = collect_thesis_summary_tables(thesis_root) if thesis_root.is_dir() else (pd.DataFrame(), pd.DataFrame())

    if not map_df.empty:
        map_df.to_csv(output_dir / "map_statistics_runs.csv", index=False)
        agg_df = summarize_numeric(
            map_df,
            [
                "roads_count",
                "road_length_km",
                "lanes_total",
                "lanes_per_road",
                "lanes_per_km",
                "lane_width_avg",
                "signals_total",
            ],
        )
        agg_df.to_csv(output_dir / "map_statistics_aggregate.csv", index=False)
        agg_df.to_latex(output_dir / "map_statistics_aggregate.tex", index=False, float_format="%.2f")

        plot_bar(map_df, "run_id", "roads_count", "Road segments per run", "Road count", output_dir / "roads_per_run.png")
        plot_bar(map_df, "run_id", "road_length_km", "Total drivable length per run", "Road length (km)", output_dir / "road_length_per_run.png")
        plot_scatter(
            map_df,
            "road_length_km",
            "lanes_total",
            "Lane volume vs road length",
            "Road length (km)",
            "Total lanes",
            output_dir / "lanes_vs_length.png",
        )
        if not speed_df.empty:
            speed_df.to_csv(output_dir / "speed_limit_distribution.csv", index=False)
            plot_speed_distribution(speed_df, output_dir / "speed_limit_distribution.png")
    else:
        print("[info] No map_statistics.json files found under ultimate_pipeline_out.")

    if not thesis_structural.empty:
        thesis_structural.to_csv(output_dir / "thesis_structural_summaries.csv", index=False)
        thesis_structural.to_latex(output_dir / "thesis_structural_summaries.tex", index=False)

    if not carla_df.empty:
        carla_df.to_csv(output_dir / "thesis_carla_loadability.csv", index=False)
    if not perception_df.empty:
        perception_df.to_csv(output_dir / "thesis_perception_proxy.csv", index=False)

    print(f"[done] Outputs written to {output_dir}")


if __name__ == "__main__":
    main()
