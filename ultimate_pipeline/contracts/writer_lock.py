from __future__ import annotations
import json
import os
import platform
import tempfile
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

# Cap on retries inside WriterLock.acquire()'s atomic create-exclusive loop.
# Each retry only happens when we lost a race to reclaim an expired/malformed
# lock slot; under real contention this converges in 1-2 iterations per
# contender since os.O_EXCL is the sole arbiter of who wins. The cap exists
# only to fail loudly instead of spinning forever in a pathological state.
_ACQUIRE_MAX_ATTEMPTS = 64

# GAP-028: bounded fresh-publication re-read budget. The winner's
# os.open(..., O_CREAT|O_EXCL) makes the lock pathname visible at size 0
# BEFORE the subsequent fdopen/write/flush/fsync populate it, so a losing
# contender's immediate load() can observe an empty or torn (partially
# written) file during that fresh-publication window. We re-read for up to
# _FRESH_PUBLISH_MAX_REREADS attempts spaced _FRESH_PUBLISH_REREAD_DELAY_S
# apart (100 x 0.005s = a ~500ms total wait ceiling) to ride out the
# winner's publication. If the content is still unreadable after the full
# budget, acquire() fails closed with a distinct RuntimeError -- it never
# unlinks the file and never misreports the condition as "Writer lock
# held by" (unreadable is not the same claim as live-held).
_FRESH_PUBLISH_MAX_REREADS = 100
_FRESH_PUBLISH_REREAD_DELAY_S = 0.005


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
        # The legacy-lock check is read-only and must happen before we ever
        # write to lock_path below, so a legacy conflict never leaves behind
        # a newly-created (and now orphaned) primary lock file.
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
        payload = json.dumps(lock.to_dict(), indent=2).encode("utf-8")
        open_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)

        # Atomic create-exclusive acquire: os.open(..., O_CREAT|O_EXCL) is a
        # single OS syscall that fails atomically if the path already
        # exists, so it remains the SOLE exclusivity authority -- unlike the
        # previous exists()-check-then-write() sequence, no two processes
        # can both observe "nobody holds this" and then both write.
        #
        # For *readers* (the losers of that O_EXCL race) the pathname
        # becomes visible at size 0 the instant the winner's os.open
        # returns, before fdopen/write/flush/fsync below have populated it,
        # so a loser's immediate load() can observe an empty or torn file
        # (JSONDecodeError / TypeError). Losers treat that unreadable fresh
        # content as a bounded-retry-then-fail-closed condition (the
        # fresh-publication re-read sub-loop below): they never unlink it
        # and never report it as "Writer lock held by". Content that stays
        # unreadable for the whole re-read budget is NOT reclaimable -- it
        # fails closed with a distinct RuntimeError so a human can inspect
        # the malformed lock rather than have it silently deleted.
        #
        # Reclaiming an expired/malformed-but-parseable lock is handled by
        # unlinking it and retrying the O_EXCL create; the unlink is not
        # itself the arbiter of exclusivity (it is safe/idempotent for two
        # racing reclaimers to both attempt it), only the next O_EXCL
        # create is. The unlink below is only ever reached after a
        # successful load() (fully parsed content) that is not live.
        for _attempt in range(_ACQUIRE_MAX_ATTEMPTS):
            try:
                fd = os.open(str(lock_path), open_flags)
            except FileExistsError:
                existing = None
                unreadable = False
                try:
                    existing = cls.load(lock_path)
                except FileNotFoundError:
                    # Raced with a concurrent release/cleanup between the
                    # failed O_EXCL create and this read; just retry.
                    continue
                except (ValueError, TypeError):
                    # Unreadable content: either a fresh winner still
                    # publishing (empty/torn JSON at the just-created path)
                    # or a persistently malformed lock. Enter the bounded
                    # fresh-publication re-read window before deciding.
                    unreadable = True

                if unreadable:
                    recovered = False
                    vanished = False
                    for _reread in range(_FRESH_PUBLISH_MAX_REREADS):
                        time.sleep(_FRESH_PUBLISH_REREAD_DELAY_S)
                        try:
                            existing = cls.load(lock_path)
                            recovered = True
                            break
                        except FileNotFoundError:
                            # File vanished mid-publication (release/cleanup
                            # won the race); retry the O_EXCL create.
                            vanished = True
                            break
                        except (ValueError, TypeError):
                            continue
                    if vanished:
                        continue
                    if not recovered:
                        # Still unreadable after the full re-read budget:
                        # fail closed with a DISTINCT error (mp worker maps
                        # RuntimeError -> "blocked"). Deliberately does NOT
                        # contain "Writer lock held by" (we could not parse
                        # it, so we cannot claim any owner holds it), and
                        # deliberately does NOT unlink the file (no silent
                        # delete of a malformed persistent lock).
                        raise RuntimeError(
                            f"writer.lock at {lock_path} exists but is not "
                            f"readable JSON; refusing to acquire or delete it"
                        )
                    # recovered: fall through to the normal path below with
                    # the successfully-parsed object.

                if existing.is_live():
                    raise RuntimeError(
                        f"Writer lock held by {existing.owner} "
                        f"(PID {existing.pid}, expires {existing.expires_at})"
                    )
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            else:
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(payload)
                        f.flush()
                        os.fsync(f.fileno())
                except BaseException:
                    lock_path.unlink(missing_ok=True)
                    raise
                return lock

        raise RuntimeError(
            f"Could not acquire writer lock at {lock_path} after "
            f"{_ACQUIRE_MAX_ATTEMPTS} attempts (persistent contention)"
        )

    def save(self, path: Path | None = None) -> None:
        if path is None:
            path = self._default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomically replace the file's contents (mkstemp + fsync +
        # os.replace), mirroring Manifest.save() in
        # ultimate_pipeline/artifacts/model.py. This is the right primitive
        # for "atomically replace this file's contents" -- unlike acquire(),
        # this method is only ever called by a caller that already believes
        # it owns the lock, so it is not itself the "acquire iff nobody else
        # has it" operation; that exclusivity is enforced by acquire()'s
        # O_CREAT|O_EXCL loop and by heartbeat()/release() re-validating
        # identity against the currently-persisted lock before calling this.
        payload = json.dumps(self.to_dict(), indent=2)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            try:
                dir_fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

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
        path = self._default_path()
        if path.exists():
            self._assert_still_current(path, action="release")
            self.status = "released"
            self.save(path)
        else:
            self.status = "released"

    def heartbeat(self) -> None:
        path = self._default_path()
        if path.exists():
            self._assert_still_current(path, action="heartbeat")
        self.heartbeat_at = _now_iso()
        self.save(path)

    def _assert_still_current(self, path: Path, action: str) -> None:
        """Re-read the currently-persisted lock at `path` and confirm it is
        still the same lock this handle acquired (by lock_id, falling back
        to task_id like the rest of this class does). A stale handle whose
        lease already expired and was legitimately reclaimed by a different
        owner must not be able to silently clobber that owner's active lock
        via heartbeat()/release() -- this re-validates against what is
        actually on disk right now, not just this object's own remembered
        state, which is what the prior implementation got wrong.
        """
        current = self.load(path)
        my_lock_id = self.lock_id or self.task_id
        current_lock_id = current.lock_id or current.task_id
        if current_lock_id != my_lock_id:
            raise RuntimeError(
                f"Writer lock {action} rejected: on-disk lock (lock_id="
                f"{current_lock_id!r}, owner={current.owner!r}) no longer matches "
                f"this handle's lock_id {my_lock_id!r}; refusing to clobber a lock "
                "that was reclaimed by another owner"
            )

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
