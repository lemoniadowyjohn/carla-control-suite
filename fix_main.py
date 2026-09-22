#!/usr/bin/env python3
"""Fix main_pipeline.py get("ok", True) occurrences."""

filepath = "ultimate_pipeline/main_pipeline.py"

with open(filepath, "r") as f:
    content = f.read()

# Add import
if 'from ultimate_pipeline.quality.result_normalizer import' not in content:
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('from __future__ import annotations'):
            lines.insert(i+1, 'from ultimate_pipeline.quality.result_normalizer import normalize_quality_result')
    content = '\n'.join(lines)
    with open(filepath, "w") as f:
        f.write(content)
    print('Added import')
else:
    print('Import already present')

# Fix occurrence 1: line 2238
old1 = 'if isinstance(seam_report, dict) and not seam_report.get("ok", True):'
new1 = 'if isinstance(seam_report, dict) and not normalize_quality_result(seam_report).get("ok", False):'
if old1 in content:
    content = content.replace(old1, new1, 1)
    print('Fixed main occurrence 1')
else:
    print('Main occurrence 1 not found')

# Fix occurrence 2: line 2279
old2 = 'if not seam_report.get("ok", True):'
new2 = 'if not normalize_quality_result(seam_report).get("ok", False):'
if old2 in content:
    content = content.replace(old2, new2, 1)
    print('Fixed main occurrence 2')
else:
    print('Main occurrence 2 not found')

# Fix occurrence 3: line 3307
old3 = 'report_ok = bool(report.get("ok", True)) if isinstance(report, dict) else False'
new3 = 'report_ok = normalize_quality_result(report).get("ok", False) if isinstance(report, dict) else False'
if old3 in content:
    content = content.replace(old3, new3, 1)
    print('Fixed main occurrence 3')
else:
    print('Main occurrence 3 not found')

# Fix occurrence 4: line 3367
old4 = 'if not report.get("ok", True):'
new4 = 'if not normalize_quality_result(report).get("ok", False):'
if old4 in content:
    content = content.replace(old4, new4, 1)
    print('Fixed main occurrence 4')
else:
    print('Main occurrence 4 not found')

with open(filepath, "w") as f:
    f.write(content)

print("Done fixing main_pipeline.py")