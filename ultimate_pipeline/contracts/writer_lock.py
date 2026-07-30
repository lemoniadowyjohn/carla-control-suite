from __future__ import annotations
import json
import os
import platform
import uuid
import time
from fnmatch import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


LOCK_DIR = ".agent_locks"
LOCK_FILE = "writer.lock"
CANONICAL_LOCK_PATH = Path(LOCK_DIR) / LOCK_FILE
SCHEMA_VERSION = "agent-writer-lock/v1"
DEFAULT_LEASE_MINUTES = 240


@dataclass
class WriterLock:
    schema: str = SCHEMA_VERSION
    status: str = "active"
    lock_type: str = "single_writer"
    owner: str = ""
    owner_account: str = ""
    host: str = ""
    created_at: str = ""
    lease_minutes: int = DEFAULT_LEASE_MINUTES
    expires_at: str = ""
    repository: str = ""
    branch: str = ""
    head_sha: str = ""
    purpose: str = ""
    model: str = ""
    task_id: str = ""
    pid: int = 0
    lock_id: str = ""
    read_only: bool = False
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    release_protocol: str = ""
    heartbeat_at: str = ""

    @classmethod
    def acquire(
        cls,
        root: Path,
        branch: str,
        head_sha: str,
        owner: str,
        purpose: str = "",
        model: str = "",
        task_id: str = "",
        lease_minutes: int = DEFAULT_LEASE_MINUTES,
        lock_id: str = "",
        read_only: bool = False,
        allowed_paths: Sequence[str] | None = None,
        forbidden_paths: Sequence[str] | None = None,
    ) -> WriterLock:
        lock_dir = root / LOCK_DIR
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / LOCK_FILE
        legacy_lock_path = root / ".agent_lock.json"
        if lock_path.exists():
            existing = cls.load(lock_path)
            if existing.is_live():
                raise RuntimeError(
                    f"Writer lock held by {existing.owner} "
                    f"(PID {existing.pid}, expires {existing.expires_at})"
                )
            if existing.is_malformed():
                lock_path.unlink(missing_ok=True)
        if legacy_lock_path.exists():
            legacy = cls.load(legacy_lock_path)
            if legacy.is_live():
                raise RuntimeError(
                    f"Legacy writer lock held by {legacy.owner} "
                    f"(PID {legacy.pid}, expires {legacy.expires_at})"
                )
            if legacy.is_malformed():
                raise RuntimeError("Legacy writer lock is malformed")
        now_utc = _now_iso()
        expires = _future_iso(lease_minutes)
        resolved_lock_id = lock_id or (task_id or uuid.uuid4().hex)
        lock = cls(
            owner=owner,
            owner_account=_owner_account(),
            host=platform.node(),
            created_at=now_utc,
            lease_minutes=lease_minutes,
            expires_at=expires,
            repository=str(root.resolve()),
            branch=branch,
            head_sha=head_sha,
            purpose=purpose,
            model=model,
            task_id=task_id,
            pid=os.getpid(),
            lock_id=resolved_lock_id,
            read_only=read_only,
            allowed_paths=list(allowed_paths) if allowed_paths else [],
            forbidden_paths=list(forbidden_paths) if forbidden_paths else [],
            release_protocol=(
                "Set status to 'released' with released_at and final SHA, "
                "or let the lease expire."
            ),
            heartbeat_at=now_utc,
        )
        lock.status = "read_only" if read_only else "active"
        lock.save(lock_path)
        return lock

    def save(self, path: Path | None = None) -> None:
        if path is None:
            path = self._default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path | None = None) -> WriterLock:
        if path is None:
            path = cls._default_path()
        if not path.exists():
            raise FileNotFoundError(f"Lock file not found: {path}")
        data = json.loads(path.read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> WriterLock:
        return cls(**data)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "status": self.status,
            "lock_type": self.lock_type,
            "owner": self.owner,
            "owner_account": self.owner_account,
            "host": self.host,
            "created_at": self.created_at,
            "lease_minutes": self.lease_minutes,
            "expires_at": self.expires_at,
            "repository": self.repository,
            "branch": self.branch,
            "head_sha": self.head_sha,
            "purpose": self.purpose,
            "model": self.model,
            "task_id": self.task_id,
            "pid": self.pid,
            "lock_id": self.lock_id,
            "read_only": self.read_only,
            "allowed_paths": list(self.allowed_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "release_protocol": self.release_protocol,
            "heartbeat_at": self.heartbeat_at,
        }

    def release(self, owner: str | None = None, lock_id: str | None = None) -> None:
        if owner is not None and not self.owned_by(owner):
            raise RuntimeError(
                f"Writer lock release rejected for owner {owner}; owned by {self.owner}"
            )
        expected_lock_id = self.lock_id or self.task_id
        if lock_id is not None and lock_id not in {expected_lock_id, self.task_id}:
            raise RuntimeError(
                f"Writer lock release rejected for lock_id {lock_id}; expected {expected_lock_id}"
            )
        self.status = "released"
        path = self._default_path()
        if path.exists():
            self.save(path)

    def heartbeat(self) -> None:
        self.heartbeat_at = _now_iso()
        self.save()

    def is_live(self) -> bool:
        if self.status != "active":
            return False
        expires = _parse_iso(self.expires_at)
        return time.time() < expires

    def is_expired(self) -> bool:
        return not self.is_live()

    def is_malformed(self) -> bool:
        required = ["owner", "branch", "head_sha", "created_at", "expires_at"]
        for field_name in required:
            if not getattr(self, field_name, None):
                return True
        return False

    def owned_by(self, owner: str) -> bool:
        return self.owner == owner

    def overlaps_path(self, path: Path) -> bool:
        candidate = path.resolve()
        repo_root = Path(self.repository).resolve() if self.repository else Path.cwd().resolve()
        try:
            relative = candidate.relative_to(repo_root)
        except ValueError:
            relative = candidate
        relative_text = relative.as_posix()

        def _matches(patterns: list[str]) -> bool:
            candidate = relative_text.strip("/")
            for pattern in patterns:
                normalized = pattern.replace("\\", "/").strip("/")
                if normalized.endswith("/**"):
                    prefix = normalized[:-3]
                    if candidate == prefix or candidate.startswith(prefix + "/"):
                        return True
                    continue
                if fnmatch(candidate, normalized):
                    return True
            return False

        if self.forbidden_paths and _matches(self.forbidden_paths):
            return True
        if self.allowed_paths and not _matches(self.allowed_paths):
            return True
        return False

    def _default_path(self) -> Path:
        repo = Path(self.repository) if self.repository else Path.cwd()
        return repo / LOCK_DIR / LOCK_FILE


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _future_iso(minutes: int) -> str:
    import datetime as _dt
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=minutes)).isoformat()


def _parse_iso(s: str) -> float:
    import datetime as _dt
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(s)
        return dt.timestamp()
    except Exception:
        return 0.0


def _owner_account() -> str:
    try:
        user = os.environ.get("USERNAME", os.environ.get("USER", "unknown"))
        domain = os.environ.get("USERDOMAIN", "")
        return f"{domain}\\{user}" if domain else user
    except Exception:
        return "unknown"
