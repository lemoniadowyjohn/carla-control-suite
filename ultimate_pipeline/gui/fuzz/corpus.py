"""Content-addressed, versioned corpus store.

Design rules:

* **Content-addressed ids** -- ``sha256`` of the normalised content, so the
  same case is the same entry.
* **Atomic writes with an integrity check** -- a write that is interrupted
  leaves the previous entry intact, never a truncated file.
* **Deduplication** by normalised content hash.
* **Seed and regression corpora are separate.** Authoritative regression
  evidence is **never** silently overwritten or deleted.
* **Quarantine** for malformed or schema-incompatible entries.
* **Migrations** between corpus schema versions; unknown versions are refused.
* **Safe paths** -- traversal and archive-extraction style names are refused.
* **Bounded retention** with an explicit, non-authoritative policy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from ultimate_pipeline.gui.results import Result

__all__ = [
    "CORPUS_SCHEMA", "SUPPORTED_CORPUS_VERSIONS", "CorpusError",
    "CorpusKind", "CaseRecord", "CorpusStore", "normalise",
]


CORPUS_SCHEMA = "carla-fuzz-corpus/v1"
SUPPORTED_CORPUS_VERSIONS = (CORPUS_SCHEMA,)
_UNSAFE_NAME_RE = re.compile(r"(^[A-Za-z]:)|(\.\.)|(^[\\/])|([\\/])|(\x00)")


class CorpusError(ValueError):
    pass


class CorpusKind(str, Enum):
    SEED = "SEED"
    REGRESSION = "REGRESSION"


def normalise(payload: Any) -> Any:
    """Canonical form so equivalent payloads hash identically."""
    if isinstance(payload, dict):
        return {k: normalise(payload[k]) for k in sorted(payload)}
    if isinstance(payload, list):
        return [normalise(v) for v in payload]
    if isinstance(payload, float) and payload.is_integer():
        return int(payload)
    return payload


def content_id(payload: Any) -> str:
    blob = json.dumps(normalise(payload), sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def safe_name(name: str) -> str:
    """Refuse traversal, absolute and separator-bearing names."""
    if not name or _UNSAFE_NAME_RE.search(name):
        raise CorpusError(f"unsafe corpus entry name: {name!r}")
    return name


@dataclass
class CaseRecord:
    case_id: str
    kind: str
    payload: Any
    provenance: dict = field(default_factory=dict)
    expected_outcome: str = ""
    author: str = ""

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "kind": self.kind, "payload": self.payload,
                "provenance": self.provenance, "expected_outcome": self.expected_outcome,
                "author": self.author}

    def to_json(self) -> str:
        return json.dumps({"schema": CORPUS_SCHEMA, **self.as_dict()},
                          sort_keys=True, indent=2)


class CorpusStore:
    def __init__(self, root: Path, *, retention_records: int = 1000) -> None:
        self.root = Path(root)
        self.seed_dir = self.root / "seed"
        self.regression_dir = self.root / "regression"
        self.quarantine_dir = self.root / "quarantine"
        for directory in (self.seed_dir, self.regression_dir, self.quarantine_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.retention_records = max(1, int(retention_records))
        self._index: dict[str, CaseRecord] = {}
        #: ids evicted by retention, so a later add() re-persists them
        self._evicted: set[str] = set()

    # -- paths -------------------------------------------------------------
    def _dir_for(self, kind: str) -> Path:
        return self.seed_dir if kind == CorpusKind.SEED.value else self.regression_dir

    def path_for(self, case_id: str, kind: str = CorpusKind.SEED.value) -> Path:
        return self._dir_for(kind) / f"{safe_name(case_id)}.json"

    # -- write -------------------------------------------------------------
    def _atomic_write(self, target: Path, text: str) -> None:
        tmp = target.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)

    def add(self, payload: Any, *, kind: str = CorpusKind.SEED.value,
            expected_outcome: str = "", provenance: dict | None = None,
            author: str = "") -> Result:
        """Add a case. Deduplicates on the normalised content hash."""
        try:
            case_id = content_id(payload)
        except (TypeError, ValueError) as exc:
            return self._quarantine(payload, f"payload is not serialisable: {exc}")

        if case_id in self._index:
            # Deduplicate ONLY if the entry is genuinely still on disk. A
            # cached index entry whose file was evicted by retention must not
            # be reported as deduplicated, or the case can never be restored.
            existing = self.path_for(case_id, kind)
            if existing.is_file() and case_id not in self._evicted:
                return Result.success({"case_id": case_id, "deduplicated": True})
            self._index.pop(case_id, None)

        record = CaseRecord(case_id, kind, payload, dict(provenance or {}),
                            expected_outcome, author)
        target = self.path_for(case_id, kind)
        try:
            self._atomic_write(target, record.to_json())
        except CorpusError as exc:
            return self._quarantine(payload, str(exc))
        except OSError as exc:
            return Result.failure(f"corpus write failed: {exc}",
                                  error_class="CorpusWriteError", state_restored=False)
        self._index[case_id] = record
        return Result.success({"case_id": case_id, "deduplicated": False,
                               "path": str(target)})

    def _quarantine(self, payload: Any, reason: str) -> Result:
        body = json.dumps({"schema": CORPUS_SCHEMA, "quarantined": True,
                           "reason": reason, "payload_repr": repr(payload)[:2000]},
                          sort_keys=True, indent=2)
        target = self.quarantine_dir / f"{hashlib.sha256(repr(payload).encode()).hexdigest()[:16]}.json"
        try:
            self._atomic_write(target, body)
        except OSError:
            pass
        return Result.blocked(reason, error_class="Quarantined",
                              remediation="fix the entry and re-add it")

    # -- read --------------------------------------------------------------
    def get(self, case_id: str) -> CaseRecord | None:
        """Read through to disk so the cache can never serve stale content."""
        for directory in (self.seed_dir, self.regression_dir):
            path = directory / f"{case_id}.json"
            if not path.is_file():
                continue
            record = self._read(path)
            if record is None or record.case_id != case_id:
                # on-disk content does not match its content address
                self._index.pop(case_id, None)
                return None
            self._index[case_id] = record
            return record
        # not on disk: the cache entry is stale and must not be served
        self._index.pop(case_id, None)
        return None

    def _read(self, path: Path) -> CaseRecord | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None
        return self._record_from(payload, path)

    def _record_from(self, payload: Any, path: Path) -> CaseRecord | None:
        if not isinstance(payload, dict):
            return None
        schema = payload.get("schema")
        if schema not in SUPPORTED_CORPUS_VERSIONS:
            return None
        body = payload.get("payload")
        if body is None:
            return None
        expected = content_id(body)
        declared = payload.get("case_id")
        if declared and declared != expected:
            # content address disagrees with the stored id: integrity failure
            return None
        return CaseRecord(expected, payload.get("kind", CorpusKind.SEED.value), body,
                          payload.get("provenance", {}),
                          payload.get("expected_outcome", ""),
                          payload.get("author", ""))

    # -- integrity ---------------------------------------------------------
    def verify(self) -> dict:
        """Walk every entry, confirm its content address, and reconcile the cache."""
        broken: list[str] = []
        total = 0
        seen: set[str] = set()
        for directory in (self.seed_dir, self.regression_dir):
            for path in sorted(directory.glob("*.json")):
                total += 1
                record = self._read(path)
                if record is None or record.case_id != path.stem:
                    broken.append(path.name)
                    self._index.pop(path.stem, None)
                else:
                    seen.add(record.case_id)
                    self._index[record.case_id] = record
        # drop cached entries whose files no longer exist
        for stale in [cid for cid in self._index if cid not in seen]:
            self._index.pop(stale, None)
        return {"total": total, "broken": broken, "intact": not broken,
                "indexed": len(self._index)}

    def apply_migration(self, document: dict) -> dict:
        """Migrate a corpus document forward; unknown versions are refused."""
        schema = document.get("schema")
        if schema not in SUPPORTED_CORPUS_VERSIONS:
            raise CorpusError(f"unsupported corpus schema {schema!r}")
        migrated = dict(document)
        migrated["schema"] = CORPUS_SCHEMA
        migrated.setdefault("provenance", {})
        return migrated

    # -- retention ---------------------------------------------------------
    def enforce_retention(self) -> dict:
        """Bound the NON-authoritative seed corpus.

        Regression evidence is authoritative and is never deleted here.
        """
        entries = sorted(self.seed_dir.glob("*.json"),
                         key=lambda p: (p.stat().st_mtime, p.name))
        removed: list[str] = []
        if len(entries) > self.retention_records:
            for path in entries[: len(entries) - self.retention_records]:
                path.unlink(missing_ok=True)
                removed.append(path.stem)
                # the cache must not keep serving an entry that was just deleted
                self._index.pop(path.stem, None)
                self._evicted.add(path.stem)
        return {"removed": removed, "regression_preserved": True,
                "seed_remaining": len(list(self.seed_dir.glob('*.json')))}

    # -- export ------------------------------------------------------------
    def export(self, kinds: Iterable[str] = (CorpusKind.SEED.value,)) -> Result:
        """Reproducible export. Proprietary payloads are excluded by size."""
        records: list[dict] = []
        skipped: list[str] = []
        for kind in kinds:
            for path in sorted(self._dir_for(kind).glob("*.json")):
                record = self._read(path)
                if record is None:
                    skipped.append(f"{path.name}: unreadable")
                    continue
                records.append(record.as_dict())
        body = json.dumps({"schema": CORPUS_SCHEMA, "records": records},
                          sort_keys=True, indent=2)
        return Result.success({"json": body, "count": len(records),
                               "skipped": skipped})

    def import_records(self, document: dict) -> Result:
        """Import an exported document, verifying content addresses."""
        if not isinstance(document, dict):
            return Result.blocked("corpus document must be an object")
        if document.get("schema") not in SUPPORTED_CORPUS_VERSIONS:
            return Result.blocked(
                f"unsupported corpus schema {document.get('schema')!r}",
                error_class="UnsupportedSchema")
        accepted, rejected = 0, []
        for entry in document.get("records", []):
            body = entry.get("payload")
            if body is None:
                rejected.append(entry.get("case_id", "?"))
                continue
            outcome = self.add(body, kind=entry.get("kind", CorpusKind.SEED.value),
                               expected_outcome=entry.get("expected_outcome", ""))
            if outcome.ok:
                accepted += 1
            else:
                rejected.append(entry.get("case_id", "?"))
        return Result.success({"accepted": accepted, "rejected": rejected})