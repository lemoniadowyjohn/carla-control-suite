"""Namespace shim for running `python -m ultimate_pipeline...` from inside the package dir.

Why this exists:
- The repo's package directory is `ultimate_pipeline/`.
- Some tests spawn subprocesses **from inside that directory** and run commands
  like `python -m ultimate_pipeline.tools.run_perception_pair`.
- In that working directory, Python expects to find a *child* directory named
  `ultimate_pipeline/` on sys.path. That normally doesn't exist, so the module
  cannot be located.

Solution:
This inner package is a lightweight shim that turns `ultimate_pipeline` into a
namespace package spanning:
  1) this inner dir (for the shim), and
  2) the outer, real package dir (one level up).

It is import-safe and has no runtime effect when the repo is used normally from
its parent directory.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pkgutil

_inner = Path(__file__).resolve().parent
_outer = _inner.parent  # .../ultimate_pipeline (real package dir)
_repo_root = _outer.parent

# Ensure repo root is available so the outer package dir can be discovered.
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Make this a namespace package that also searches the outer directory.
try:
    __path__ = pkgutil.extend_path(__path__, __name__)  # type: ignore[name-defined]
except NameError:  # pragma: no cover
    pass
