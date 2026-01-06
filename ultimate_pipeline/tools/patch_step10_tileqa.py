#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch helper for Step 10 tile QA integration.

- ensures tile worker is called with --fix_s
- ensures returncode==2 (preflight_failed) skips the tile instead of retrying forever

Run from repo root:
  python -m ultimate_pipeline.tools.patch_step10_tileqa
"""

from __future__ import annotations

import re
from pathlib import Path


def main() -> None:
    mp = Path.cwd() / "ultimate_pipeline" / "main_pipeline.py"
    if not mp.exists():
        print("[patch_step10_tileqa] ultimate_pipeline/main_pipeline.py not found; nothing patched.")
        return

    txt = mp.read_text(encoding="utf-8")
    changed = False

    # add --fix_s if tile_worker used
    if "tile_worker" in txt and "--fix_s" not in txt:
        txt2 = re.sub(r"(tile_worker[^\n]*?\])", r"\1 + ['--fix_s']", txt, count=1)
        if txt2 != txt:
            txt = txt2
            changed = True

    # skip tile on exit code 2
    if "subprocess.run" in txt and "returncode == 2" not in txt:
        # insert after "if r.returncode != 0:"
        txt2, n = re.subn(
            r"(if\s+r\.returncode\s*!=\s*0\s*:\s*\n)",
            r"\1            if r.returncode == 2:\n                print('⚠ Tile preflight failed (S-invariants). Skipping tile.')\n                continue\n",
            txt,
            count=1,
            flags=re.MULTILINE,
        )
        if n:
            txt = txt2
            changed = True

    if changed:
        mp.write_text(txt, encoding="utf-8")
        print("[patch_step10_tileqa] patched.")
    else:
        print("[patch_step10_tileqa] no changes needed.")


if __name__ == "__main__":
    main()
