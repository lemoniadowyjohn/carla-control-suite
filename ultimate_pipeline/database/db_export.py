"""
DB export tool: dump tables to CSV/JSON for local or HPC use.

Examples:
    python -m ultimate_pipeline.database.db_export --out-dir exports/
    python -m ultimate_pipeline.database.db_export --out-dir /scratch/$USER/carla_db_exports
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.database.db_manager import Database


TABLES = ["dataset_entries", "experiments", "domain_gap_metrics"]


def export_table(db: Database, table: str, out_dir: Path):
    conn = db._connect()
    try:
        df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    finally:
        conn.close()

    csv_path = out_dir / f"{table}.csv"
    json_path = out_dir / f"{table}.json"

    df.to_csv(csv_path, index=False)

    records = df.to_dict(orient="records")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    return csv_path, json_path


def main():
    parser = argparse.ArgumentParser(description="Export CARLA pipeline DB tables.")
    parser.add_argument(
        "--out-dir",
        type=str,
        required=True,
        help="Output directory for CSV/JSON files.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db = Database()
    db._validate_schema()

    print(f"Using DB: {SETTINGS.DB_FILE}")
    print(f"Export directory: {out_dir}")
    print("=" * 60)

    for table in TABLES:
        csv_path, json_path = export_table(db, table, out_dir)
        print(f"✅ Exported {table}:")
        print(f"   CSV → {csv_path}")
        print(f"   JSON → {json_path}")

    print("\n🎉 Export complete.")


if __name__ == "__main__":
    main()
