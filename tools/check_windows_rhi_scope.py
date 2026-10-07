#!/usr/bin/env python3
"""Regression: effective Windows TargetedRHIs must not contain PCD3D_ES31.

Reads the project DefaultEngine.ini section
[/Script/WindowsTargetPlatform.WindowsTargetSettings] plus the engine
BaseEngine.ini Windows scope. Paths via argv (no machine paths baked in).
Exit 0 = scope clean, 1 = ES31 present.
"""
from __future__ import annotations

import re
import sys


def effective_windows_rhis(project_ini: str) -> list:
    text = open(project_ini, encoding="utf-8", errors="replace").read()
    m = re.search(
        r"\[/Script/WindowsTargetPlatform\.WindowsTargetSettings\](.*?)(?=\n\[|\Z)",
        text, re.S)
    if not m:
        return []
    rhis: list = []
    for line in m.group(1).splitlines():
        line = line.strip()
        mm = re.match(r"[+-]?TargetedRHIs=(.+)", line)
        if mm:
            rhis.append(mm.group(1).strip())
    # UE semantics: a bare "-TargetedRHIs=X" line resets the list.
    effective: list = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("-TargetedRHIs="):
            effective = []
        mm = re.match(r"\+TargetedRHIs=(.+)", line)
        if mm:
            effective.append(mm.group(1).strip())
    return rhis if not effective else effective


def main() -> int:
    project_ini = sys.argv[1] if len(sys.argv) > 1 else None
    if not project_ini:
        print("usage: check_windows_rhi_scope.py <DefaultEngine.ini>")
        return 2
    rhis = effective_windows_rhis(project_ini)
    print("effective Windows TargetedRHIs:", rhis)
    bad = [r for r in rhis if "ES31" in r]
    if bad:
        print("FAIL: ES31 present:", bad)
        return 1
    if "PCD3D_SM5" not in rhis:
        print("FAIL: required PCD3D_SM5 missing")
        return 1
    print("PASS: no ES31; SM5 present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
