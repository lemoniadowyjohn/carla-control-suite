from __future__ import annotations

import hashlib
import json
from typing import Any


class _StableJSONEncoder(json.JSONEncoder):
    """JSON encoder that preserves tuple/list distinction and handles more types."""
    
    def iterencode(self, o, _one_shot=False):
        """Override to add type markers for tuples."""
        return super().iterencode(self._add_type_markers(o), _one_shot)
    
    def encode(self, o):
        return super().encode(self._add_type_markers(o))
    
    def _add_type_markers(self, obj):
        """Recursively add type markers to distinguish tuples from lists."""
        if isinstance(obj, tuple):
            return {"__tuple__": True, "items": [self._add_type_markers(item) for item in obj]}
        elif isinstance(obj, list):
            return [self._add_type_markers(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: self._add_type_markers(v) for k, v in obj.items()}
        elif isinstance(obj, set):
            return {"__set__": True, "items": [self._add_type_markers(item) for item in sorted(obj, key=str)]}
        elif isinstance(obj, frozenset):
            return {"__frozenset__": True, "items": [self._add_type_markers(item) for item in sorted(obj, key=str)]}
        return obj


def stable_hash(obj: Any, *, algo: str = "sha256") -> str:
    """
    Deterministic hash for Python objects.
    Canonicalizes via JSON with sorted keys and stable separators.
    Preserves distinction between tuples and lists.
    """
    encoder = _StableJSONEncoder(sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    s = encoder.encode(obj)
    h = hashlib.new(algo)
    h.update(s.encode("utf-8"))
    return h.hexdigest()
