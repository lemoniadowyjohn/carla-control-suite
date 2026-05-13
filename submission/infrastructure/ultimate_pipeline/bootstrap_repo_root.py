"""Ensure repo root is on ``sys.path``.

When running ``python ultimate_pipeline/main_pipeline.py``, Python sets
``sys.path[0]`` to the ``ultimate_pipeline/`` directory, not the repo root.
Imports like ``import tools.preanchor_xodr`` may fail unless repo root is on
``sys.path``.

Import this module early to make such imports reliable.
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_root_on_syspath() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_s = str(repo_root)
    if repo_root_s not in sys.path:
        sys.path.insert(0, repo_root_s)
    return repo_root


# Execute on import (safe no-op if already present).
ensure_repo_root_on_syspath()
