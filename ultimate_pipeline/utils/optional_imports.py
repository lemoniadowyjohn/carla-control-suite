# ultimate_pipeline/utils/optional_deps.py
from __future__ import annotations

from importlib import import_module
from typing import Any, Optional

def optional_import(module: str) -> Optional[Any]:
    try:
        return import_module(module)
    except Exception:
        return None

def require(dep: Any, module: str, feature: str) -> None:
    if dep is None:
        raise RuntimeError(
            f"Optional dependency '{module}' is required for {feature} "
            f"but is not installed."
        )
