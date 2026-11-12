"""Cooperating-controller CARLA port reservation, V94.1.

NOT an OS socket reservation and NOT a process-termination authority.
SQLite transactions serialize cooperating controllers across worktrees, while
preflight TCP checks still reject non-cooperating occupants. Crash remnants
fail closed and require operator-mediated reconciliation; never auto-delete.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


class PortLeaseConflict(RuntimeError):
    """The requested CARLA port namespace is already reserved or unverifiable."""


def default_lease_db() -> Path:
    # Worktree-independent per-user location. Operators running under a
    # different OS user need an explicit shared authority or network allocator.
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    if not base:
        base = str(Path.home() / ".local" / "share")
    return Path(base) / "carla-control-suite" / "runtime_port_leases.sqlite3"


@dataclass
class PortLease:
    ports: tuple[int, ...]
    db_path: Path = field(default_factory=default_lease_db)
    session_id: str = field(default_factory=lambda: secrets.token_hex(24))
    _active: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.ports = tuple(int(p) for p in self.ports)
        if len(set(self.ports)) != len(self.ports) or not self.ports:
            raise ValueError("CARLA namespace ports must be unique and nonempty")
        if any(p < 1 or p > 65535 for p in self.ports):
            raise ValueError("invalid CARLA port")
        if len(self.session_id) < 24:
            raise ValueError("session token too short")
        raw = Path(self.db_path).expanduser().absolute()
        if any(part.is_symlink() for part in (raw, *raw.parents)):
            raise PortLeaseConflict("symlinked reservation database path prohibited")
        self.db_path = raw

    def _connect(self) -> sqlite3.Connection:
        # Refuse symlinked DB paths. The file is a local authority and should
        # not be redirected into another agent's workspace or shared cache.
        if any(part.is_symlink() for part in (self.db_path, *self.db_path.parents)):
            raise PortLeaseConflict("symlinked reservation database prohibited")
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = sqlite3.connect(str(self.db_path), timeout=3.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("""CREATE TABLE IF NOT EXISTS reservations (
            port INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            controller_pid INTEGER NOT NULL
        )""")
        return conn

    def acquire(self) -> None:
        if self._active:
            raise PortLeaseConflict("lease already active")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            slots = ",".join("?" for _ in self.ports)
            occupied = conn.execute(
                f"SELECT port, session_id FROM reservations WHERE port IN ({slots})",
                self.ports,
            ).fetchall()
            if occupied:
                raise PortLeaseConflict(f"reserved CARLA port(s): {[p for p, _ in occupied]}")
            conn.executemany(
                "INSERT INTO reservations (port,session_id,controller_pid) VALUES (?,?,?)",
                ((port, self.session_id, os.getpid()) for port in self.ports),
            )
            conn.execute("COMMIT")
            self._active = True
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release(self) -> bool:
        if not self._active:
            return False
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            slots = ",".join("?" for _ in self.ports)
            rows = conn.execute(
                f"SELECT port,session_id,controller_pid FROM reservations WHERE port IN ({slots})",
                self.ports,
            ).fetchall()
            if (len(rows) != len(self.ports) or
                    any(token != self.session_id or pid != os.getpid() for _,token,pid in rows)):
                raise PortLeaseConflict("lease ownership mismatch; refusing release")
            cur = conn.execute(
                f"DELETE FROM reservations WHERE port IN ({slots}) AND session_id=? AND controller_pid=?",
                (*self.ports, self.session_id, os.getpid()),
            )
            if cur.rowcount != len(self.ports):
                raise PortLeaseConflict("lease changed during release")
            conn.execute("COMMIT")
            self._active = False
            return True
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def __enter__(self) -> "PortLease":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


def inspect_leases(db_path: Path | None = None) -> list[dict]:
    """Read-only diagnostics; never auto-recover leases from a stale PID."""
    path = Path(db_path) if db_path is not None else default_lease_db()
    if not path.exists():
        return []
    if path.is_symlink():
        raise PortLeaseConflict("symlinked lease database prohibited")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=3.0) as conn:
        return [{"port": port, "session_id": sid, "controller_pid": pid}
                for port, sid, pid in conn.execute("SELECT port,session_id,controller_pid FROM reservations ORDER BY port")]
