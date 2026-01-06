#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wire CrashClassifier/CrashIntake into main_pipeline.py (tile QA subprocess + optional SUMO).

This script edits files in-place using conservative regexes.

Run from repo root:
  python ultimate_pipeline/tools/patch_wire_crash_intake.py
"""

from __future__ import annotations

import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def patch_main_pipeline() -> bool:
    mp = os.path.join(REPO_ROOT, "ultimate_pipeline", "main_pipeline.py")
    if not os.path.exists(mp):
        print(f"[patch] main_pipeline.py not found: {mp}")
        return False

    txt = _read(mp)
    changed = False

    tile_block = re.compile(
        r"""(r\s*=\s*subprocess\.run\(\s*cmd\s*,\s*timeout\s*=\s*sp_timeout\s*\)\s*\n\s*if\s+r\.returncode\s*!=\s*0\s*:\s*\n)(\s*raise\s+RuntimeError\([^\n]*\)\s*)""",
        re.MULTILINE
    )

    def repl(m: re.Match) -> str:
        nonlocal changed
        changed = True
        head = m.group(1)
        injected = """            from ultimate_pipeline.core.crash_intake import crash_intake
            from ultimate_pipeline.core.carla_log_locator import locate_carla_log_path

            carla_log_path = locate_carla_log_path(self.settings, out_dir=os.path.join(self.out_dir, "logs"))
            sumo_log_path = getattr(self.settings, "SUMO_LOG_PATH", None)

            crash_record = crash_intake(
                out_dir=os.path.join(self.out_dir, "logs"),
                vreport=self.vreport,
                stage=f"tile_{name}",
                xodr_path=tile_path,
                carla_log_path=carla_log_path,
                sumo_log_path=sumo_log_path,
                extra={"returncode": r.returncode, "cmd": cmd},
            )
            raise RuntimeError(f"tile worker exit code {r.returncode} ({crash_record.get('category','UNKNOWN')})")
"""
        return head + injected

    txt2 = tile_block.sub(repl, txt, count=1)
    if txt2 != txt:
        txt = txt2
        print("[patch] Patched tile QA subprocess failure handling.")
    else:
        print("[patch] Tile QA subprocess pattern not found (maybe in-process QA or different code).")

    sumo_pat = re.compile(
        r"""(sumo_fixed_path\s*=\s*SUMORepair\.repair\([^\)]*\)\s*\n\s*if\s+sumo_fixed_path\s+is\s+None\s*:\s*\n)""",
        re.MULTILINE
    )
    if sumo_pat.search(txt):
        if "stage=\"sumo_repair\"" not in txt:
            txt = sumo_pat.sub(
                lambda m: m.group(1) + """                from ultimate_pipeline.core.crash_intake import crash_intake
                from ultimate_pipeline.core.carla_log_locator import locate_carla_log_path

                crash_intake(
                    out_dir=os.path.join(self.out_dir, "logs"),
                    vreport=self.vreport,
                    stage="sumo_repair",
                    xodr_path=sanitized,
                    carla_log_path=locate_carla_log_path(self.settings, out_dir=os.path.join(self.out_dir, "logs")),
                    sumo_log_path=getattr(self.settings, "SUMO_LOG_PATH", None),
                    extra={"note": "SUMO repair returned None"},
                )
""",
                txt,
                count=1
            )
            print("[patch] Patched SUMO repair failure intake.")
            changed = True

    if changed:
        _write(mp, txt)
    return changed

def main() -> int:
    ok = patch_main_pipeline()
    print("[patch] done" if ok else "[patch] nothing changed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
