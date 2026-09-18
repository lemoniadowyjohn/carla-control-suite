from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_hash(obj: Any, *, algo: str = "sha256") -> str:
    """
    Deterministic hash for Python objects.
    Canonicalizes via JSON with sorted keys and stable separators.
    """
    s = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    h = hashlib.new(algo)
    h.update(s.encode("utf-8"))
    return h.hexdigest()
