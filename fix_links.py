#!/usr/bin/env python3
"""Fix stage_06_links.py get("ok", True) occurrence."""

filepath = "ultimate_pipeline/pipeline_stages/stage_06_links.py"

with open(filepath, "r") as f:
    content = f.read()

# Fix the occurrence on line 693
old = 'and not seam_report.get("ok", True)'
new = 'and not normalize_quality_result(seam_report).get("ok", False)'
if old in content:
    content = content.replace(old, new, 1)
    print('Fixed stage_06_links occurrence')
else:
    print('Occurrence not found')

with open(filepath, "w") as f:
    f.write(content)

print("Done")