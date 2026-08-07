"""Shared helpers for Phase Q modules.

All modules in this package are offline-capable: CARLA imports are guarded so
that test/CI environments without the simulator remain import-safe.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: os.PathLike | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: os.PathLike | str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: os.PathLike | str, payload: Any) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str, sort_keys=False)
    return str(path)


def load_text(path: os.PathLike | str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def save_text(path: os.PathLike | str, text: str) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_encoding(text: str) -> str:
    """Force lossless UTF-8 round-trip (byte-identity helper for hashing)."""
    return text.encode("utf-8").decode("utf-8")


_XML_NS = re.compile(r"xmlns[:=][\"'][^\"']*[\"']")


def strip_xml_namespaces(text: str) -> str:
    """Best-effort removal of xmlns declarations so CARLA-style XODR parses."""
    return _XML_NS.sub("", text)


class XodrTree:
    """Lazy wrapper around an OpenDRIVE XML document.

    Parsing is deferred so callers that never need the tree do not pay the
    cost.  The raw text is preserved for exact hashing.
    """

    def __init__(self, xodr_text: str):
        self.text = ensure_encoding(xodr_text or "")
        self._root: Optional[ET.Element] = None
        self._parse_error: Optional[str] = None

    @property
    def root(self) -> ET.Element:
        if self._root is None:
            if self._parse_error:
                raise RuntimeError(f"XODR parse failed earlier: {self._parse_error}")
            try:
                self._root = ET.fromstring(strip_xml_namespaces(self.text))
            except ET.ParseError as exc:
                self._parse_error = str(exc)
                raise RuntimeError(f"XODR XML parse error: {exc}") from exc
        return self._root

    @property
    def sha256(self) -> str:
        return sha256_text(self.text)

    def find(self, path: str) -> Optional[ET.Element]:
        return self.root.find(path)

    def findall(self, path: str) -> List[ET.Element]:
        return list(self.root.findall(path))

    def iter(self, tag: str) -> List[ET.Element]:
        return [e for e in self.root.iter() if _local_name(e.tag) == tag]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def norm_id(value: Any) -> str:
    """Normalize an OpenDRIVE id for set comparison."""
    if value is None:
        return ""
    s = str(value).strip()
    if s.startswith("'"):
        s = s[1:]
    if s.endswith("'"):
        s = s[:-1]
    return s


def guarded_import_carla() -> Any:
    """Import the CARLA PythonAPI, or raise ImportError with a clear message."""
    return __import__("carla")


def import_carla_or_none() -> Optional[Any]:
    """Return the carla module if importable in this interpreter, else None."""
    if "carla" not in sys.modules:
        try:
            import carla  # noqa: F401
        except Exception:
            return None
    return sys.modules.get("carla")


def iter_children(el: ET.Element) -> List[ET.Element]:
    return list(el)
