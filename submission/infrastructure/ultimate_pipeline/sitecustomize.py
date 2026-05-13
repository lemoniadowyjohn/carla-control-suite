"""Site customization for repo-local module execution.

This repo keeps the *package directory* named `ultimate_pipeline/`.
When running commands from inside that directory (e.g. test subprocesses
that call `python -m ultimate_pipeline...`), Python's module resolution
needs the **parent** directory on sys.path.

Python automatically imports `sitecustomize` (if present on sys.path) on
startup, so this is a minimal, safe, and cross-platform way to make
`python -m ultimate_pipeline...` work regardless of current working dir.
"""

from __future__ import annotations

import sys
from pathlib import Path

here = Path(__file__).resolve().parent
parent = here.parent

# If we're in the package dir itself, add the parent (repo root) to sys.path.
# This is idempotent and does nothing when already correct.
if here.name == "ultimate_pipeline" and str(parent) not in sys.path:
    sys.path.insert(0, str(parent))
