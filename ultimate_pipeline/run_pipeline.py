#!/usr/bin/env python3
"""
Unified entrypoint for the entire ultimate_pipeline.
Runs: sanitization → topology repair → enrichment → tiling → validation.
"""

from __future__ import annotations

from ultimate_pipeline.utils.bootstrap import bootstrap_console

bootstrap_console()

import sys
import os



from pathlib import Path

# Ensure repo root is on sys.path so `import ultimate_pipeline...` works
# regardless of working directory (PyCharm, CLI, double-click, etc.).
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.utils.timestamped_print import enable_timestamped_print
enable_timestamped_print()

def _import_pipeline_and_settings():
    """Import pipeline + settings robustly for both package and repo-root execution."""
    try:
        # Preferred: package layout
        from ultimate_pipeline.main_pipeline import MainPipeline  # type: ignore
        from ultimate_pipeline.config.settings import SETTINGS  # type: ignore
        return MainPipeline, SETTINGS
    except Exception as e:
        raise RuntimeError(
            "Forbidden fallback import path used. "
            "This repo requires ultimate_pipeline.* namespaces only. "
            "Run via: python -m ultimate_pipeline.cli"
        ) from e


def main() -> int:
    print("\n==============================================")
    print("      🚀 ULTIMATE PIPELINE — ENTRYPOINT")
    print("==============================================\n")

    MainPipeline, SETTINGS = _import_pipeline_and_settings()

    pipeline = MainPipeline(SETTINGS)
    try:
        out_dir = pipeline.run()
    except Exception:
        print("\n==============================================")
        print("      ❌ PIPELINE FAILED (see traceback above)")
        print("==============================================\n")
        return 1

    print("\n==============================================")
    print("      🎉 PIPELINE COMPLETED SUCCESSFULLY")
    if out_dir:
        print(f"      📁 Output dir: {out_dir}")
        print(f"Output dir: {out_dir}")
    print("==============================================\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
