#!/usr/bin/env python3
"""Backwards-compatible shim for the canonical pipeline implementation.

Use `up pipeline run` or `python -m ultimate_pipeline.cli pipeline run` for the
user-facing interface. The implementation lives in `ultimate_pipeline.main_pipeline`.
"""
from __future__ import annotations

from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    from ultimate_pipeline.main_pipeline import main as pipeline_main
    from ultimate_pipeline.utils.timestamped_print import timestamped_print_scope

    with timestamped_print_scope():
        return int(pipeline_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
