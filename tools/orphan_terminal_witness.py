#!/usr/bin/env python3
"""Read-only terminal witness for an orphaned-but-legitimate UE process.

Holds a Windows process handle opened with observation-only rights
(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION), waits natively
(WaitForSingleObject, no polling), then preserves the exact exit code,
exit time, CPU/I-O totals and a read-only output freeze.

Writes ONLY to its own out_dir (control-plane evidence). Never mutates
shared CARLA state, never kills, never acquires leases.

Usage:
  python tools/orphan_terminal_witness.py --pid 12312 \\
      --expected-creation "2026-10-05T18:38:44Z" \\
      --expected-cmd-substr "ImportAssets" \\
      --out-dir reports/control_plane
"""
from __future__ import annotations

import argparse
import ctypes
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0x00000000
STILL_ACTIVE = 259

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
_k.OpenProcess.restype = ctypes.c_void_p
_k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_k.WaitForSingleObject.restype = ctypes.c_uint32
_k.GetExitCodeProcess.argtypes = [ctypes.c_void_p,
                                  ctypes.POINTER(ctypes.c_uint32)]
_k.GetExitCodeProcess.restype = ctypes.c_bool


class _FT(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]


_k.GetProcessTimes.argtypes = [ctypes.c_void_p,
                               ctypes.POINTER(_FT), ctypes.POINTER(_FT),
                               ctypes.POINTER(_FT), ctypes.POINTER(_FT)]
_k.GetProcessTimes.restype = ctypes.c_bool


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in (
        "ReadOperationCount", "WriteOperationCount",
        "OtherOperationCount", "ReadTransferCount",
        "WriteTransferCount", "OtherTransferCount")]


_k.GetProcessIoCounters.argtypes = [ctypes.c_void_p,
                                     ctypes.POINTER(_IO)]
_k.GetProcessIoCounters.restype = ctypes.c_bool


def _utcnow() -> str:
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _ft_to_iso(ft: _FT) -> str:
    v = (ft.hi << 32) | ft.lo
    us = (v - 116444736000000000) // 10
    dt = datetime.datetime(1970, 1, 1) + datetime.timedelta(microseconds=us)
    return dt.replace(tzinfo=datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z")


EXIT_CLASSES = {
    0: "SUCCESS",
    1: "PROGRAM_NONZERO_EXIT",
    2: "PROGRAM_NONZERO_EXIT",
    0xC000013A: "CONTROL_C_EXIT",
    0xC0000005: "WINDOWS_EXCEPTION_ACCESS_VIOLATION",
    0xC00000FD: "WINDOWS_EXCEPTION_STACK_OVERFLOW",
    0xC0000409: "WINDOWS_EXCEPTION_STACK_BUFFER_OVERRUN",
    0xC0000374: "WINDOWS_EXCEPTION_HEAP_CORRUPTION",
}


def classify(code: int) -> str:
    if code in EXIT_CLASSES:
        return EXIT_CLASSES[code]
    if 0xC0000000 <= code <= 0xFFFFFFFF:
        return "WINDOWS_EXCEPTION"
    return "UNKNOWN_WINDOWS_EXIT"


def _sha256_file(p: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="read-only orphan terminal witness")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--expected-creation", required=True,
                    help="ISO UTC prefix the live creation time must start with")
    ap.add_argument("--expected-cmd-substr", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--content-root", default="",
                    help="read-only inventory root on termination")
    ap.add_argument("--log-path", default="")
    ap.add_argument("--importsettings-path", default="")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    handle = _k.OpenProcess(
        SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, args.pid)
    if not handle:
        # PID already gone -> postmortem path (§0 fallback).
        (out / "ORPHAN_TERMINAL_WITNESS.json").write_text(json.dumps({
            "pid": args.pid,
            "handle_acquired": False,
            "terminal": "PID_GONE_BEFORE_WITNESS",
            "watch_start_utc": _utcnow(),
        }, indent=2), encoding="utf-8")
        print("PID_GONE_BEFORE_WITNESS")
        return 2

    fc, fx, fk, fu = _FT(), _FT(), _FT(), _FT()
    if not _k.GetProcessTimes(handle, ctypes.byref(fc), ctypes.byref(fx),
                              ctypes.byref(fk), ctypes.byref(fu)):
        _k.CloseHandle(handle)
        (out / "ORPHAN_TERMINAL_WITNESS.json").write_text(json.dumps({
            "pid": args.pid,
            "handle_acquired": False,
            "terminal": "TIMES_UNREADABLE",
            "watch_start_utc": _utcnow(),
        }, indent=2), encoding="utf-8")
        print("TIMES_UNREADABLE")
        return 2

    creation_iso = _ft_to_iso(fc)
    if not creation_iso.startswith(args.expected_creation[:19]):
        _k.CloseHandle(handle)
        (out / "ORPHAN_TERMINAL_WITNESS.json").write_text(json.dumps({
            "pid": args.pid,
            "handle_acquired": False,
            "terminal": "PID_REUSE_DETECTED",
            "observed_creation_time": creation_iso,
            "expected_creation_prefix": args.expected_creation[:19],
            "PID_REUSE_DETECTED": True,
        }, indent=2), encoding="utf-8")
        print("PID_REUSE_DETECTED")
        return 3

    (out / "ORPHAN_TERMINAL_WITNESS.json").write_text(json.dumps({
        "pid": args.pid,
        "creation_time": creation_iso,
        "handle_acquired": True,
        "rights": "SYNCHRONIZE|PROCESS_QUERY_LIMITED_INFORMATION",
        "rights_note": "observation only; no TERMINATE/VM_WRITE/CREATE_THREAD",
        "watch_start_utc": _utcnow(),
        "expected_operation": "executor ImportAssets (NoSig discriminator import)",
        "expected_command_substr": args.expected_cmd_substr,
        "wait_mechanism": "WaitForSingleObject(INFINITE) on process handle",
    }, indent=2), encoding="utf-8")
    print(f"witness installed on {args.pid} created {creation_iso}",
          flush=True)

    # Native wait: no polling.
    _k.WaitForSingleObject(handle, INFINITE)
    detect_utc = _utcnow()

    code = ctypes.c_uint32()
    _k.GetExitCodeProcess(handle, ctypes.byref(code))
    exit_code = int(code.value)
    fc2, fx2, fk2, fu2 = _FT(), _FT(), _FT(), _FT()
    times_ok = bool(_k.GetProcessTimes(
        handle, ctypes.byref(fc2), ctypes.byref(fx2),
        ctypes.byref(fk2), ctypes.byref(fu2)))
    io, io_ok = _IO(), False
    try:
        io_ok = bool(_k.GetProcessIoCounters(handle, ctypes.byref(io)))
    except Exception:
        io_ok = False
    kernel_us = ((fk2.hi << 32) | fk2.lo) // 10 if times_ok else None
    user_us = ((fu2.hi << 32) | fu2.lo) // 10 if times_ok else None
    _k.CloseHandle(handle)

    terminal = {
        "pid": args.pid,
        "creation_time": creation_iso,
        "witness_detection_utc": detect_utc,
        "process_exit_time_utc": _ft_to_iso(fx2) if times_ok else None,
        "exit_time_source": "GetProcessTimes (kernel) — not log mtime",
        "exit_code_dec": exit_code,
        "exit_code_hex": hex(exit_code),
        "termination_class": classify(exit_code),
        "kernel_cpu_us": kernel_us,
        "user_cpu_us": user_us,
        "io_counters": {f: getattr(io, f) for f in (
            "ReadOperationCount", "WriteOperationCount",
            "OtherOperationCount", "ReadTransferCount",
            "WriteTransferCount", "OtherTransferCount")} if io_ok else None,
    }
    (out / "ORPHAN_PROCESS_TERMINAL_STATE.json").write_text(
        json.dumps(terminal, indent=2), encoding="utf-8")
    print(f"terminal: exit={exit_code} ({hex(exit_code)}) "
          f"class={terminal['termination_class']}", flush=True)

    # Read-only post-exit freeze (shared tree is quiescent: no mutator can
    # exist that we don't know about — but we take nothing for granted and
    # change nothing regardless).
    freeze: dict = {"frozen_at_utc": _utcnow(), "read_only": True}
    if args.content_root:
        croot = Path(args.content_root)
        files = [p for p in croot.rglob("*") if p.is_file()] \
            if croot.is_dir() else []
        freeze["content_total_files"] = len(files)
        try:
            freeze["latest_mtime"] = max(
                p.stat().st_mtime for p in files)
        except ValueError:
            freeze["latest_mtime"] = None
        umaps = [str(p) for p in files if p.suffix.lower() == ".umap"]
        freeze["all_umap_files"] = umaps
        freeze["tile_umap_count"] = sum(
            1 for u in umaps if "_Tile_" in u.replace("\\", "/").split("/")[-1]
            or "Tile" in u)
        sm = [str(p) for p in files if p.suffix.lower() == ".uasset"
              and "staticmesh" in str(p).lower()]
        freeze["staticmesh_hint_count"] = len(sm)
        freeze["staticmesh_hint_note"] = (
            "suffix-only heuristic; authoritative StaticMesh count needs "
            "AssetRegistry inspection")
    if args.log_path:
        lp = Path(args.log_path)
        try:
            freeze["log_bytes"] = lp.stat().st_size
            freeze["log_mtime"] = lp.stat().st_mtime
        except OSError as e:
            freeze["log_error"] = str(e)
        freeze["log_sha256"] = _sha256_file(lp)
    if args.importsettings_path:
        ip = Path(args.importsettings_path)
        freeze["importsettings_sha256"] = _sha256_file(ip)
        try:
            freeze["importsettings_bytes"] = ip.stat().st_size
        except OSError:
            pass
    (out / "ACTIVE_IMPORT_FINAL_RECEIPT.json").write_text(
        json.dumps({"terminal": terminal, "freeze": freeze,
                    "pipeline_classification": "PENDING_POST_EDITOR_AUDIT"},
                   indent=2), encoding="utf-8")
    print("freeze written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
