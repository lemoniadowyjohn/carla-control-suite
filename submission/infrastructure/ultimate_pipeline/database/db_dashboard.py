"""
Streamlit dashboard for visualizing CARLA pipeline database contents.

Run with:
    streamlit run ultimate_pipeline/database/db_dashboard.py
from the repo root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.database.db_manager import Database


# ==========================================================
# DB helpers
# ==========================================================
def load_table(db: Database, table_name: str) -> pd.DataFrame:
    """
    Load a full table into a DataFrame.
    Assumes schema already validated.
    """
    conn = db._connect()
    try:
        return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    finally:
        conn.close()


def pretty_json_cell(value: str | None) -> str:
    if not value:
        return ""
    try:
        return json.dumps(json.loads(value), indent=2)
    except Exception:
        return value


# ==========================================================
# Main UI
# ==========================================================
def main():
    st.set_page_config(
        page_title="CARLA Pipeline DB Dashboard",
        layout="wide",
    )
    st.title("📊 CARLA Pipeline Database Dashboard")

    db_path = Path(SETTINGS.DB_FILE)

    # ---------------- Sidebar ----------------
    st.sidebar.header("Database")
    st.sidebar.write(f"**Path:** `{db_path}`")
    st.sidebar.write(f"**Exists:** {db_path.exists()}")

    if not db_path.exists():
        st.error("Database file does not exist yet. Run the pipeline to create it.")
        return

    # ---------------- DB init + schema validation ----------------
    try:
        db = Database()
        db._validate_schema()
    except Exception as e:
        st.error("❌ Database schema error")
        st.markdown(
            """
            The database schema does not match the expected structure.
            This usually means the DB was created by an older pipeline version.
            """
        )
        st.code(str(e))
        return

    # ---------------- Tabs ----------------
    tab_dataset, tab_exp, tab_gap = st.tabs(
        ["📷 Dataset Entries", "🧪 Experiments", "🌍 Domain Gap Metrics"]
    )

    # ==========================================================
    # Dataset Entries
    # ==========================================================
    with tab_dataset:
        st.subheader("Dataset Entries")

        df = load_table(db, "dataset_entries")
        if df.empty:
            st.info("No dataset entries logged yet.")
        else:
            with st.expander("Raw table", expanded=True):
                st.dataframe(df, use_container_width=True)

            st.markdown("### Filters")
            col1, col2 = st.columns(2)

            with col1:
                dataset_names = ["<all>"] + sorted(
                    df["dataset_name"].dropna().unique().tolist()
                )
                dataset_filter = st.selectbox("Dataset", dataset_names)

            with col2:
                map_types = ["<all>"] + sorted(
                    df["map_type"].dropna().unique().tolist()
                )
                map_filter = st.selectbox("Map type", map_types)

            filtered = df
            if dataset_filter != "<all>":
                filtered = filtered[filtered["dataset_name"] == dataset_filter]
            if map_filter != "<all>":
                filtered = filtered[filtered["map_type"] == map_filter]

            st.markdown("### Summary")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Rows", len(filtered))
            with c2:
                st.metric("Unique datasets", filtered["dataset_name"].nunique())
            with c3:
                st.metric("Augmented samples", int(filtered["augmentation"].sum()))

            st.markdown("### Preview")
            st.dataframe(filtered.head(100), use_container_width=True)

    # ==========================================================
    # Experiments
    # ==========================================================
    with tab_exp:
        st.subheader("Experiments")

        df = load_table(db, "experiments")
        if df.empty:
            st.info("No experiments logged yet.")
        else:
            st.markdown("### Overview")
            st.dataframe(df, use_container_width=True)

            st.markdown("### Select experiment")
            exp_ids = df["id"].tolist()
            if exp_ids:
                exp_id = st.selectbox("Experiment ID", exp_ids)
                row = df[df["id"] == exp_id].iloc[0]

                st.markdown("#### Config JSON")
                st.code(
                    pretty_json_cell(row.get("config_json")),
                    language="json",
                )

                st.markdown("#### Results JSON")
                st.code(
                    pretty_json_cell(row.get("results_json")),
                    language="json",
                )

    # ==========================================================
    # Domain Gap Metrics
    # ==========================================================
    with tab_gap:
        st.subheader("Domain Gap Metrics")

        df = load_table(db, "domain_gap_metrics")
        if df.empty:
            st.info("No domain gap metrics logged yet.")
        else:
            st.markdown("### Filters")
            col1, col2 = st.columns(2)

            with col1:
                tiles = ["<all>"] + sorted(
                    df["tile_id"].dropna().unique().tolist()
                )
                tile_filter = st.selectbox("Tile ID", tiles)

            with col2:
                metrics = ["<all>"] + sorted(
                    df["metric_name"].dropna().unique().tolist()
                )
                metric_filter = st.selectbox("Metric", metrics)

            filtered = df
            if tile_filter != "<all>":
                filtered = filtered[filtered["tile_id"] == tile_filter]
            if metric_filter != "<all>":
                filtered = filtered[filtered["metric_name"] == metric_filter]

            st.markdown("### Summary")
            st.dataframe(filtered, use_container_width=True)

            if not filtered.empty:
                try:
                    st.line_chart(filtered[["metric_value"]])
                except Exception:
                    st.info("Metric values not suitable for plotting.")


if __name__ == "__main__":
    main()
