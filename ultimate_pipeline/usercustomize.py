"""Repo-local import fix for subprocess calls.

Pytest spawns subprocesses from inside the `ultimate_pipeline/` package dir and
executes commands like:

    python -m ultimate_pipeline.tools.run_perception_pair

When the current working directory is the package directory itself, Python needs
the parent directory on sys.path to resolve the package name.

This file is loaded automatically by Python (if present on sys.path) after the
system `sitecustomize`.
"""

from __future__ import annotations

import sys
from pathlib import Path

here = Path(__file__).resolve().parent
parent = here.parent

if here.name == "ultimate_pipeline" and str(parent) not in sys.path:
    sys.path.insert(0, str(parent))
