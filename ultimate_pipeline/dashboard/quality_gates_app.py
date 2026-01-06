# ultimate_pipeline/dashboard/quality_gates_app.py

from __future__ import annotations

import json
import os
from typing import Any, Dict

import streamlit as st


def _load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    st.set_page_config(page_title="Ultimate Pipeline – Quality Gates", layout="wide")

    st.title("🧪 Ultimate Pipeline – Quality Gate Dashboard")

    logs_dir = st.text_input("Logs directory", value="logs")

    vreport_path = os.path.join(logs_dir, "validation_report_full.json")
    gate_failures_path = os.path.join(os.path.dirname(logs_dir), "gate_failures.json")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Validation Report")
        vreport = _load_json(vreport_path)
        if not vreport:
            st.warning(f"No validation_report_full.json found at {vreport_path}")
        else:
            st.json(vreport.get("quality_gates", {}))

    with col2:
        st.subheader("Failing Gates")
        failures = _load_json(gate_failures_path)
        if not failures:
            st.success("No failing gates detected (or gate_failures.json missing).")
        else:
            for name, detail in failures.items():
                with st.expander(f"❌ {name}", expanded=False):
                    st.json(detail)


if __name__ == "__main__":
    main()
