# ultimate_pipeline/dashboard/hpc_experiments_dashboard.py

from __future__ import annotations
import glob
import json
import os
from typing import Dict, Any, List

import streamlit as st
import pandas as pd


LOG_PATTERN = "logs/hpc/*_full_report.json"


def load_experiments(pattern: str = LOG_PATTERN) -> List[Dict[str, Any]]:
    exps = []
    for path in glob.glob(pattern):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["_path"] = path
            exps.append(data)
        except Exception as e:
            print(f"Failed to read {path}: {e}")
    return exps


def flatten_experiment(exp: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turn nested experiment JSON into flat columns for DataFrame.
    Assumes schema from ExperimentLogger.write_report:
    {
      "experiment": "...",
      "domain_gap": {...},
      "perception_gap": {...}
    }
    """
    row: Dict[str, Any] = {}
    row["experiment"] = exp.get("experiment", "unknown")
    row["_path"] = exp.get("_path", "")

    domain = exp.get("domain_gap", {})
    percep = exp.get("perception_gap", {})

    # Flatten domain gap
    for k, v in domain.items():
        row[f"domain_{k}"] = v

    # Flatten perception gap
    for k, v in percep.items():
        row[f"perception_{k}"] = v

    return row


def main():
    st.set_page_config(page_title="HPC Experiments Dashboard", layout="wide")

    st.title("🧪 HPC Experiments Dashboard")
    st.write("Explore domain-gap and perception-gap across all experiments.")

    exps = load_experiments()
    if not exps:
        st.warning("No experiment reports found under logs/hpc/*_full_report.json")
        return

    flat_rows = [flatten_experiment(e) for e in exps]
    df = pd.DataFrame(flat_rows)

    st.subheader("Experiments Overview")
    st.dataframe(df)

    # Sidebar filters
    st.sidebar.header("Filters")
    selected_exp = st.sidebar.selectbox(
        "Select experiment",
        options=df["experiment"].tolist()
    )

    sel_row = df[df["experiment"] == selected_exp].iloc[0]
    st.subheader(f"Details: {selected_exp}")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Domain-Gap Metrics**")
        domain_cols = [c for c in df.columns if c.startswith("domain_")]
        st.table(sel_row[domain_cols])

    with col2:
        st.markdown("**Perception-Gap Metrics**")
        percep_cols = [c for c in df.columns if c.startswith("perception_")]
        st.table(sel_row[percep_cols])

    st.markdown("---")
    st.subheader("Correlation: Domain Gap vs Perception")

    numeric_cols = df.select_dtypes(include="number").columns.tolist()

    x_metric = st.selectbox("Domain metric (x-axis)", [c for c in numeric_cols if c.startswith("domain_")])
    y_metric = st.selectbox("Perception metric (y-axis)", [c for c in numeric_cols if c.startswith("perception_")])

    st.write(f"Scatter: {x_metric} vs {y_metric}")
    st.scatter_chart(df[[x_metric, y_metric]])

    st.markdown("### Raw JSON of selected experiment")
    path = sel_row["_path"]
    with open(path, "r", encoding="utf-8") as f:
        raw_json = json.load(f)
    st.json(raw_json)


if __name__ == "__main__":
    main()
