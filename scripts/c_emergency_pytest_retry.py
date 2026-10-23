"""Retry deletion of the 13 pytest scratch dirs that failed with WinError 5.

WinError 5 on rmtree is commonly a read-only attribute or a transient
antivirus/indexer handle. This clears the read-only attribute and retries,
then re-classifies anything still undeletable as UNKNOWN_PRESERVE rather than
forcing it.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c_emergency_pytest_cleanup import (  # noqa: E402
    PYTEST_ROOT, drive_free_mb, live_pytest_pids, tree_bytes,
)

OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"


def on_rm_error(func, path, _exc):
    """Clear read-only and retry once, in place."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except OSError:
        pass


def main():
    live = live_pytest_pids()
    if live:
        print("ABORT: live pytest %s" % live)
        return 1

    before = tree_bytes(PYTEST_ROOT)
    free_before = drive_free_mb()

    deleted, failed, reclaimed = [], [], 0
    for name in sorted(os.listdir(PYTEST_ROOT)):
        p = os.path.join(PYTEST_ROOT, name)
        if not os.path.isdir(p):
            continue
        size = tree_bytes(p)
        ok = False
        for attempt in range(3):
            try:
                import shutil
                shutil.rmtree(p, onerror=on_rm_error)
                ok = True
                break
            except OSError:
                time.sleep(0.4)
        if ok:
            deleted.append({"name": name, "bytes": size,
                            "classification": "INACTIVE_TEST_SCRATCH"})
            reclaimed += size
        else:
            failed.append({"name": name, "bytes": size,
                           "classification": "UNKNOWN_PRESERVE",
                           "reason": "WinError 5 persisted after 3 attempts "
                                     "with read-only clearing"})

    time.sleep(2)
    after = tree_bytes(PYTEST_ROOT)
    free_after = drive_free_mb()

    res = {
        "schema": "C_EMERGENCY_PYTEST_CLEANUP_RETRY/v1",
        "live_pytest_pids": live,
        "bytes_before_retry": before,
        "bytes_after_retry": after,
        "reclaimed_bytes": reclaimed,
        "reclaimed_gb": round(reclaimed / 1e9, 2),
        "dirs_deleted": len(deleted),
        "dirs_undeletable": len(failed),
        "undeletable_detail": failed,
        "undeletable_total_gb": round(sum(f["bytes"] for f in failed) / 1e9, 2),
        "C_FREE_MB_BEFORE_RETRY": round(free_before, 1),
        "C_FREE_MB_AFTER_RETRY": round(free_after, 1),
        "C_FREE_GB_AFTER_RETRY": round(free_after / 1000.0, 2),
        "classification_rule":
            "anything not removable is UNKNOWN_PRESERVE; no force-takeown, "
            "no ACL modification and no icacls was attempted",
        "force_takeown_used": False,
        "acl_modified": False,
    }
    with open(os.path.join(OUT, "C_EMERGENCY_PYTEST_CLEANUP_RETRY.json"),
              "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=2)
    print("deleted=%d reclaimed=%.2fGB undeletable=%d (%.2fGB)" % (
        res["dirs_deleted"], res["reclaimed_gb"], res["dirs_undeletable"],
        res["undeletable_total_gb"]))
    print("C: %.0f MB -> %.0f MB (%.2f GB)" % (
        res["C_FREE_MB_BEFORE_RETRY"], res["C_FREE_MB_AFTER_RETRY"],
        res["C_FREE_GB_AFTER_RETRY"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
