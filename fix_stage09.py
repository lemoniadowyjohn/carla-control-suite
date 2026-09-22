#!/usr/bin/env python3
"""Fix stage_09_tiling.py get("ok", True) occurrences."""

import sys

filepath = "ultimate_pipeline/pipeline_stages/stage_09_tiling.py"

with open(filepath, "r") as f:
    content = f.read()

# Fix 1: line 262 occurrence
old1 = 'if isinstance(rep, dict) and not rep.get("ok", True):'
new1 = 'if isinstance(rep, dict) and not normalize_quality_result(rep).get("ok", False):'
if old1 in content:
    content = content.replace(old1, new1, 1)
    print(f"Fixed occurrence 1")
else:
    print(f"Occurrence 1 not found")

# Fix 2: line 308 occurrence  
old2 = 'and not seam_tiles_report.get("ok", True)'
new2 = 'and not normalize_quality_result(seam_tiles_report).get("ok", False)'
if old2 in content:
    content = content.replace(old2, new2, 1)
    print(f"Fixed occurrence 2")
else:
    print(f"Occurrence 2 not found")

with open(filepath, "w") as f:
    f.write(content)

print("Done fixing stage_09_tiling.py")