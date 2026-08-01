#!/usr/bin/env python
"""TEST-TRACE-001 — static test quality scan (reports only)."""
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "reports", "opencode_batch_20260802")
UNCOND = {"return True", "return \"PASS\"", "return 'PASS'", "return \"OK\"",
          "return 'OK'", "return None", "return []", "return {}"}
PASS_LIKE = re.compile(r"^\s*return\s+(True|\"PASS\"|'PASS'|\"OK\"|'OK'|None)\s*$")


def scan():
    weak = []
    files = []
    for base in ("ultimate_pipeline", "submission/infrastructure/ultimate_pipeline"):
        if not os.path.isdir(base):
            continue
        for root, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
            for f in names:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(root, f)
                files.append(p)
                lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
                for i, l in enumerate(lines, 1):
                    s = l.strip()
                    if s in UNCOND:
                        weak.append({"path": p, "line": i, "pattern": "unconditional-return", "text": s})
                    if re.match(r"^\s*pass\s*(#.*)?$", l):
                        window = "".join(lines[max(0, i - 4):i - 1])
                        if "def " not in window and "class " not in window:
                            weak.append({"path": p, "line": i, "pattern": "bare-pass", "text": s})
    # validator success-path detection: functions with 'ok'/'valid' returning True with no assert
    json.dump({"files_scanned": len(files), "findings": weak[:300]},
              open(os.path.join(OUT, "06B_WEAK_ASSERTIONS.json"), "w", encoding="utf-8"), indent=2)
    print("files scanned:", len(files), "weak candidates:", len(weak))


if __name__ == "__main__":
    scan()
