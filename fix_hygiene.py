#!/usr/bin/env python3
"""Fix stage_08_hygiene.py get("ok", True) occurrence."""

filepath = "ultimate_pipeline/pipeline_stages/stage_08_hygiene.py"

with open(filepath, "r") as f:
    content = f.read()

# Fix the occurrence
old = '        "ok": all(bool(r.get("ok", True)) for r in reports.values()),'
new = '        "ok": all(normalize_quality_result(r).get("ok", False) for r in reports.values()),'
if old in content:
    content = content.replace(old, new, 1)
    print(f"Fixed hygiene occurrence")
else:
    print(f"Occurrence not found, trying alternative...")

# Try alternative pattern
old2 = '        "ok": all(bool(r.get("ok", True)) for r in reports.values())'
new2 = '        "ok": all(normalize_quality_result(r).get("ok", False) for r in reports.values())'
if old2 in content:
    content = content.replace(old2, new2, 1)
    print(f"Fixed hygiene occurrence (alternative)")

with open(filepath, "w") as f:
    f.write(content)

print("Done fixing stage_08_hygiene.py")