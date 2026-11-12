"""V94.1 targeted offline regressions (no CARLA/GPU/server used)."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import socket
import sqlite3
import subprocess
import time
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultimate_pipeline.carla_tools.v94_port_reservation import PortLease, PortLeaseConflict, inspect_leases
from ultimate_pipeline.carla_tools import carla_server as cs
from ultimate_pipeline.core import carla_utils as cu
from ultimate_pipeline.perception import run_capture_end2end as capture


def _spawn_reservation(db: str, signal, stop) -> None:
    """Separate OS process: verify sqlite port reservation interlocks."""
    lease = PortLease((28000, 28001, 28900), db_path=Path(db))
    try:
        lease.acquire()
        signal.put("acquired")
        stop.wait(timeout=8)
        lease.release()
    except BaseException as exc:
        signal.put(f"error:{type(exc).__name__}:{exc}")


def test_port_reservation_is_atomic_across_controllers(tmp_path):
    db = tmp_path / "leases.sqlite"
    ctx = mp.get_context("spawn")
    ready, stop = ctx.Queue(), ctx.Event()
    p = ctx.Process(target=_spawn_reservation, args=(str(db), ready, stop))
    p.start()
    try:
        assert ready.get(timeout=12) == "acquired"
        with pytest.raises(PortLeaseConflict, match="reserved"):
            PortLease((28001, 29000), db_path=db).acquire()
        assert sorted(x["port"] for x in inspect_leases(db)) == [28000, 28001, 28900]
    finally:
        stop.set()
        p.join(timeout=12)
        if p.is_alive():
            p.terminate()  # Only this test's own known helper process.
            p.join(timeout=5)
    assert p.exitcode == 0
    assert inspect_leases(db) == []


def test_duplicate_ports_refused(tmp_path):
    with pytest.raises(ValueError, match="unique"):
        PortLease((2000, 2000), db_path=tmp_path / "leases.sqlite")
    with pytest.raises(ValueError, match="invalid"):
        PortLease((0, 2001), db_path=tmp_path / "leases.sqlite")


def test_lease_token_mismatch_cannot_delete_foreign_rows(tmp_path):
    db=tmp_path / "leases.sqlite"
    lease=PortLease((31000,31001), db_path=db)
    lease.acquire()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE reservations SET session_id=? WHERE port=?", ("foreign_session",31001))
    with pytest.raises(PortLeaseConflict, match="ownership mismatch"):
        lease.release()
    assert sorted(x["port"] for x in inspect_leases(db)) == [31000,31001]


def test_session_leases_are_not_automatically_recovered(tmp_path):
    db=tmp_path/"leases.sqlite"
    first=PortLease((2000,2001), db_path=db)
    first.acquire()
    second=PortLease((2000,2001), db_path=db)
    with pytest.raises(PortLeaseConflict):
        second.acquire()
    assert first.release()
    assert second.acquire() is None
    assert second.release()


def test_wait_for_port_rejects_invalid_budget():
    for bad in (-1,float("nan"),float("inf")):
        with pytest.raises(ValueError):
            cs.wait_for_port("127.0.0.1", 2000, timeout_s=bad)
    assert not cs.wait_for_port("127.0.0.1", 0, timeout_s=0.0)


def test_wait_for_port_respects_small_deadline():
    started=time.monotonic()
    assert not cs.wait_for_port("127.0.0.1", 1, timeout_s=0.04)
    assert time.monotonic()-started < 0.5


@pytest.mark.parametrize("flags", [
    ("-carla-rpc-port=3000",),
    ("-carla-streaming-port=3005",),
    ("-carla-rpc-port=2000", "-carla-port=2000"),
    ("-carla-streaming-port=garbage",),
])
def test_managed_launcher_rejects_conflicting_flags(monkeypatch, tmp_path, flags):
    monkeypatch.setattr(cs,"wait_for_port",lambda *args,**kwargs: False)
    monkeypatch.setattr(cs,"start_carla",lambda *args,**kwargs:
                        (_ for _ in ()).throw(AssertionError("unsafe launch occurred")))
    with pytest.raises(ValueError):
        cs.ensure_carla_server(host="127.0.0.1",port=2000,carla_exe=tmp_path/"CarlaUE4.exe",extra_flags=flags)


def test_launcher_closes_parent_log_handles(monkeypatch,tmp_path):
    exe=tmp_path/"CarlaUE4.exe"
    exe.write_bytes(b"fake executable")
    seen=[]
    def fake_popen(cmd,**kwargs):
        seen.extend([kwargs["stdout"],kwargs["stderr"]])
        assert all(not f.closed for f in seen)
        return SimpleNamespace(pid=42)
    monkeypatch.setattr(cs.subprocess,"Popen",fake_popen)
    cs.start_carla(exe,stdout_path=tmp_path/"stdout.log",stderr_path=tmp_path/"stderr.log")
    assert len(seen)==2 and all(f.closed for f in seen)


def test_late_capture_rpc_never_reports_readiness(monkeypatch):
    clock=[0.0]
    class FakeTime:
        def monotonic(self): return clock[0]
        def time(self): return 0.0
        def sleep(self,seconds): clock[0]+=seconds
    class World:
        def get_map(self):
            clock[0] += 1.0
            return SimpleNamespace(name="OpenDriveMap")
        def get_settings(self): return SimpleNamespace(synchronous_mode=True)
    class Client:
        def __init__(self,*a): pass
        def set_timeout(self,s): assert s>0
        def get_world(self): return World()
    monkeypatch.setattr(capture,"time",FakeTime())
    monkeypatch.setattr(capture,"_try_import_carla",lambda:(SimpleNamespace(Client=Client),None))
    report=capture._ready_probe("127.0.0.1",2000,timeout_s=0.1,sleep_s=0.0)
    assert report["ok"] is False
    assert report["status"] == "RPC_READINESS_TIMEOUT"


def test_owned_process_cleanup_reports_failure(monkeypatch):
    proc=SimpleNamespace(poll=lambda:None,terminate=lambda:(_ for _ in ()).throw(PermissionError("denied")))
    assert capture._terminate_proc(proc) is False


def test_capture_exception_writes_failure_receipt(monkeypatch,tmp_path):
    args=Namespace(out_dir=str(tmp_path),carla_exe=None,attach_existing=True,
                   host="127.0.0.1",port=2000,tm_port=8000)
    monkeypatch.setattr(capture,"parse_args",lambda argv=None:args)
    monkeypatch.setattr(capture,"_start_carla_if_needed",lambda *a,**kw:
                        (_ for _ in ()).throw(RuntimeError("injected launch failure")))
    assert capture.main([]) == 1
    payload=json.loads((tmp_path/"carla_capture_failure.json").read_text())
    assert payload["ok"] is False and payload["status"] == "FAIL"
    assert "injected launch failure" in payload["error"]


def test_ready_timeout_rejects_invalid_values():
    class FakeClient:
        def set_timeout(self,s): raise AssertionError("should not enter RPC")
    with pytest.raises(ValueError):
        cu.ensure_carla_ready(FakeClient(),timeout_s=float("nan"))
    with pytest.raises(ValueError):
        cu.ensure_carla_ready(FakeClient(),delay_s=-1)


def test_managed_attach_only_never_launches_on_absent_listener(monkeypatch,tmp_path):
    monkeypatch.setattr(cs,"wait_for_port",lambda *a,**kw:False)
    monkeypatch.setattr(cs,"start_carla",lambda *a,**kw:
                        (_ for _ in ()).throw(AssertionError("must never launch")))
    with pytest.raises(RuntimeError, match="attach-only CARLA unavailable"):
        cs.ensure_carla_server(host="127.0.0.1",port=2000,
                               carla_exe=tmp_path/"CarlaUE4.exe",attach_only=True)
