# ultimate_pipeline/domain_gap/report_writer.py
"""
Named entry point for domain-gap report finalisation logic.

This module re-exports the primary finalisation functions from
run_full_domain_gap so that reviewers have a stable, importable reference
to the report-writing boundary without a high-risk code split.

The implementation lives in run_full_domain_gap._finalize_results /
_finalize_smoke_results.  A full extraction is deferred (T-MODULARIZE-RUN-FULL-
DOMAIN-GAP-001) until a safe split with complete test coverage is confirmed.
"""

from __future__ import annotations

from ultimate_pipeline.run_full_domain_gap import (  # noqa: F401 — public re-export
    _finalize_results as finalize_results,
    _finalize_smoke_results as finalize_smoke_results,
    _write_summary_outputs as write_summary_outputs,
    _check_csv_json_parity as check_csv_json_parity,
)

__all__ = [
    "finalize_results",
    "finalize_smoke_results",
    "write_summary_outputs",
    "check_csv_json_parity",
]
