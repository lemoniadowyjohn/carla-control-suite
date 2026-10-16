"""Redacted, append-only audit journal.

Every state-changing GUI action is journalled.  The journal is append-only
(one JSON object per line), every record carries a monotonic sequence and an
ISO-8601 timestamp, and every record is redacted before it is written.

Redaction is mandatory for secrets, absolute private paths, user data and
proprietary map payloads.  A bounded retention policy is applied on open; the
retention *choice* is still an operator decision (Q18), so the default is
explicit, conservative and recorded in the journal header.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

__all__ = ["AuditJournal", "redact", "AUDIT_SCHEMA", "DEFAULT_RETENTION_RECORDS"]

AUDIT_SCHEMA = "audit-journal/v1"

#: Q18 is unanswered, so the default is a conservative bounded ring. Raising it
#: is an operator decision, not something a service may do at runtime.
DEFAULT_RETENTION_RECORDS = 5000

_SECRET_KEY_RE = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|credential|auth|bearer|cookie|session[_-]?key)",
    re.IGNORECASE,
)

#: Windows user-home segments and drive-lettered private roots.
_PRIVATE_PATH_RE = re.compile(
    r"(?i)\b([A-Z]:\\Users\\[^\\\s\"']+)", re.UNICODE
)

#: Proprietary / large map payload extensions that must never be journalled.
_PROPRIETARY_SUFFIXES = (".xodr", ".fbx", ".pak", ".umap", ".tga", ".bin")

_REDACTED = "[REDACTED]"


def redact(value: Any, *, max_length: int = 512) -> Any:
    """Recursively redact secrets, private paths and proprietary payloads."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                out[key] = _REDACTED
            else:
                out[key] = redact(item, max_length=max_length)
        return out

    if isinstance(value, (list, tuple)):
        return [redact(item, max_length=max_length) for item in value]

    if isinstance(value, str):
        text = _PRIVATE_PATH_RE.sub(r"\1\[PRIVATE]", value)
        for suffix in _PROPRIETARY_SUFFIXES:
            if text.lower().endswith(suffix):
                text = f"{text[:-len(suffix)]}{suffix}[PROPRIETARY_PAYLOAD_REDACTED]"
        if len(text) > max_length:
            text = text[:max_length] + "...[TRUNCATED]"
        return text

    return value


class AuditJournal:
    """Append-only JSON-lines journal with redaction and bounded retention."""

    def __init__(
        self,
        path: Path,
        *,
        retention_records: int = DEFAULT_RETENTION_RECORDS,
        actor: str = "operator",
    ) -> None:
        self.path = Path(path)
        self.retention_records = max(1, int(retention_records))
        self.actor = actor
        self._lock = threading.Lock()
        self._seq = 0
        self._lines = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = self._scan_last_seq()
        self._apply_retention()
        self._lines = self._count_lines()

    # -- internals ---------------------------------------------------------
    def _scan_last_seq(self) -> int:
        if not self.path.exists():
            return 0
        last = 0
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    seq = record.get("seq")
                    if isinstance(seq, int) and seq > last:
                        last = seq
        except OSError:
            return 0
        return last

    def _count_lines(self) -> int:
        if not self.path.exists():
            return 0
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return sum(1 for raw in handle if raw.strip())
        except OSError:
            return 0

    def _apply_retention(self) -> None:
        """Trim the file to the retention bound, preserving the newest records."""
        if not self.path.exists():
            self.path.touch()
            return
        with self.path.open("r", encoding="utf-8") as handle:
            lines = [ln for ln in (raw.strip() for raw in handle) if ln]
        if len(lines) <= self.retention_records:
            return
        kept = lines[-self.retention_records:]
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    # -- public API --------------------------------------------------------
    @property
    def next_seq(self) -> int:
        return self._seq + 1

    def append(
        self,
        action: str,
        *,
        subject: str = "",
        detail: dict[str, Any] | None = None,
        confirmation_class: str = "",
        outcome: str = "OK",
    ) -> dict[str, Any]:
        """Append one redacted record and return it."""
        with self._lock:
            self._seq += 1
            record: dict[str, Any] = {
                "schema": AUDIT_SCHEMA,
                "seq": self._seq,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "record_id": uuid.uuid4().hex,
                "actor": self.actor,
                "action": action,
                "subject": redact(subject),
                "detail": redact(detail or {}),
                "confirmation_class": confirmation_class,
                "outcome": outcome,
            }
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._lines += 1
            # Retention is enforced on every append, not only on open, so a
            # long-lived GUI session cannot grow the journal without bound.
            if self._lines > self.retention_records:
                self._apply_retention()
                self._lines = self._count_lines()
        return record

    def record(self, action: str, **kwargs: Any) -> dict[str, Any]:
        """Alias kept for readability at call sites."""
        return self.append(action, **kwargs)

    def read(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Read records newest-last, optionally only the most recent ``limit``."""
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if limit is not None and limit >= 0:
            records = records[-limit:]
        return records

    def tail(self, count: int = 20) -> list[dict[str, Any]]:
        return self.read(limit=count)

    def retention_report(self) -> dict[str, Any]:
        records = self.read()
        return {
            "path": str(self.path),
            "retention_records": self.retention_records,
            "current_records": len(records),
            "oldest_timestamp": records[0]["timestamp"] if records else None,
            "newest_timestamp": records[-1]["timestamp"] if records else None,
            "retention_policy_source": "DEFAULT (operator decision Q18 still open)",
        }

    def recent_actions(self, count: int = 10) -> list[str]:
        return [record["action"] for record in self.tail(count)]

    def __len__(self) -> int:
        return len(self.read())